"""The ONLY Anthropic-specific module (Constitution II/V: vendor code isolated here).

Implements `LLMClient` using the `anthropic` SDK. Key provider facts encoded here (and nowhere
else in the codebase):

* Default model ``claude-sonnet-5``.
* ``temperature`` is forwarded ONLY to models the config marks ``temperature_capable`` (e.g.
  ``claude-haiku-4-5``); current frontier models (``claude-sonnet-5`` / ``claude-opus-5``) reject
  it with HTTP 400, so it is never sent to them.
* Structured output via ``client.messages.parse(..., output_format=<PydanticModel>)`` →
  ``response.parsed_output``.
* Usage read from ``response.usage.input_tokens`` / ``.output_tokens`` /
  ``.cache_read_input_tokens``; cost computed from the config pricing table.
* Explicit request timeout; the SDK's ``max_retries`` handles 429 / 5xx / connection errors.
* ``stop_reason == "refusal"`` handled; malformed/parse failures get ONE bounded repair re-ask,
  then fail closed to ``LLMResult(degraded=True)``. Expected API failures are never raised to the
  caller.

The SDK client is intentionally typed ``Any`` so this vendor boundary cannot leak version-specific
type mismatches into the rest of the codebase.
"""

from __future__ import annotations

from typing import Any

import anthropic
from pydantic import BaseModel

from ..config import AppConfig
from ..obs.trace import compute_cost
from .client import LLMResult, Msg, Usage

_EFFORT_MAX_TOKENS = {"low": 512, "medium": 1024, "high": 2048}

_REPAIR_HINT = (
    "Your previous response could not be parsed. Reply again, strictly matching the required "
    "output schema and nothing else."
)

# Expected, recoverable API failures — mapped to a safe degraded result, never re-raised.
_EXPECTED_ERRORS = (
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.APIStatusError,
    anthropic.BadRequestError,
)


class AnthropicAdapter:
    """Claude implementation of the provider-agnostic `LLMClient`."""

    def __init__(
        self,
        *,
        api_key: str | None,
        config: AppConfig,
        timeout_s: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        # `Any` so `messages.parse`, `parsed_output`, and usage fields don't have to line up with a
        # specific SDK stub version — this is the isolated vendor seam.
        self._client: Any = anthropic.Anthropic(
            api_key=api_key, timeout=timeout_s, max_retries=max_retries
        )
        self._config = config

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Msg],
        schema: type[BaseModel] | None = None,
        tools: list[Any] | None = None,
        effort: str = "medium",
        temperature: float | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult:
        kwargs = self._build_kwargs(model, system, messages, effort, temperature, timeout_s, tools)
        try:
            if schema is not None:
                return self._parse(model, kwargs, schema)
            return self._message(model, kwargs)
        except _EXPECTED_ERRORS:
            return LLMResult(degraded=True, stop_reason="error")
        except Exception:  # unexpected — still fail closed, never crash the node
            return LLMResult(degraded=True, stop_reason="error")

    # -- internals ---------------------------------------------------------------------------

    def _build_kwargs(
        self,
        model: str,
        system: str,
        messages: list[Msg],
        effort: str,
        temperature: float | None,
        timeout_s: float | None,
        tools: list[Any] | None,
    ) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": model,
            "max_tokens": _EFFORT_MAX_TOKENS.get(effort, 1024),
            "system": system,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        }
        if tools:
            kw["tools"] = tools
        # Forward temperature ONLY where the model accepts it.
        if temperature is not None and self._config.temperature_capable(model):
            kw["temperature"] = temperature
        if timeout_s is not None:
            kw["timeout"] = timeout_s
        return kw

    def _parse(self, model: str, kwargs: dict[str, Any], schema: type[BaseModel]) -> LLMResult:
        resp = self._client.messages.parse(output_format=schema, **kwargs)
        if getattr(resp, "stop_reason", None) == "refusal":
            return LLMResult(
                stop_reason="refusal",
                degraded=True,
                usage=self._usage(resp),
                cost_usd=self._cost(model, resp),
            )
        parsed = getattr(resp, "parsed_output", None)
        if parsed is None:
            # ONE bounded repair re-ask, then fail closed.
            repaired = dict(kwargs)
            repaired["messages"] = [*kwargs["messages"], {"role": "user", "content": _REPAIR_HINT}]
            try:
                resp2 = self._client.messages.parse(output_format=schema, **repaired)
                parsed2 = getattr(resp2, "parsed_output", None)
                if parsed2 is not None:
                    return LLMResult(
                        parsed=parsed2,
                        usage=self._usage(resp2),
                        cost_usd=self._cost(model, resp2),
                        stop_reason=getattr(resp2, "stop_reason", "end_turn"),
                    )
            except _EXPECTED_ERRORS:
                pass
            return LLMResult(
                degraded=True,
                stop_reason="malformed",
                usage=self._usage(resp),
                cost_usd=self._cost(model, resp),
            )
        return LLMResult(
            parsed=parsed,
            usage=self._usage(resp),
            cost_usd=self._cost(model, resp),
            stop_reason=getattr(resp, "stop_reason", "end_turn"),
        )

    def _message(self, model: str, kwargs: dict[str, Any]) -> LLMResult:
        resp = self._client.messages.create(**kwargs)
        if getattr(resp, "stop_reason", None) == "refusal":
            return LLMResult(
                stop_reason="refusal",
                degraded=True,
                usage=self._usage(resp),
                cost_usd=self._cost(model, resp),
            )
        return LLMResult(
            text=_extract_text(resp),
            usage=self._usage(resp),
            cost_usd=self._cost(model, resp),
            stop_reason=getattr(resp, "stop_reason", "end_turn"),
        )

    def _usage(self, resp: Any) -> Usage:
        u = getattr(resp, "usage", None)
        if u is None:
            return Usage()
        return Usage(
            input_tokens=int(getattr(u, "input_tokens", 0) or 0),
            output_tokens=int(getattr(u, "output_tokens", 0) or 0),
            cache_read_input_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
        )

    def _cost(self, model: str, resp: Any) -> float:
        pricing = self._config.pricing_for(model)
        if pricing is None:
            return 0.0
        u = self._usage(resp)
        return compute_cost(u.input_tokens, u.output_tokens, pricing)


def _extract_text(resp: Any) -> str | None:
    content = getattr(resp, "content", None)
    if not content:
        return None
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts) if parts else None
