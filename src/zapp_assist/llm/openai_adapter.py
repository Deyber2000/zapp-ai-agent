"""The ONLY OpenAI-specific module (Constitution II/V: vendor code isolated here).

Implements `LLMClient` using the `openai` SDK — the second provider behind the same protocol,
proving the adapter pattern. Key provider facts encoded here (and nowhere else):

* Structured output via ``client.chat.completions.parse(response_format=<PydanticModel>)`` →
  ``choices[0].message.parsed``; refusals via ``message.refusal``.
* System prompt is sent as a leading ``role="system"`` message.
* Effort maps to ``max_tokens``; ``temperature`` is forwarded only to models the config marks
  ``temperature_capable``.
* Usage from ``usage.prompt_tokens`` / ``.completion_tokens``; cost from the config pricing table.
* Expected API failures map to a safe degraded result, never re-raised; a missing parse gets ONE
  bounded repair re-ask, then fails closed.

The SDK client is intentionally typed ``Any`` so this vendor boundary cannot leak version-specific
type mismatches into the rest of the codebase.
"""

from __future__ import annotations

from typing import Any

import openai
from pydantic import BaseModel

from ..config import AppConfig
from ..obs.trace import compute_cost
from .client import LLMResult, Msg, Usage

_EFFORT_MAX_TOKENS = {"low": 512, "medium": 1024, "high": 2048}

_REPAIR_HINT = (
    "Your previous response could not be parsed. Reply again, strictly matching the required "
    "output schema and nothing else."
)

_EXPECTED_ERRORS = (
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APIStatusError,
    openai.BadRequestError,
)


class OpenAIAdapter:
    """OpenAI implementation of the provider-agnostic `LLMClient`."""

    def __init__(
        self,
        *,
        api_key: str | None,
        config: AppConfig,
        timeout_s: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self._client: Any = openai.OpenAI(
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
        kwargs = self._build_kwargs(model, system, messages, effort, temperature)
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
    ) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": model,
            "max_tokens": _EFFORT_MAX_TOKENS.get(effort, 1024),
            "messages": [
                {"role": "system", "content": system},
                *[{"role": m["role"], "content": m["content"]} for m in messages],
            ],
        }
        if temperature is not None and self._config.temperature_capable(model):
            kw["temperature"] = temperature
        return kw

    def _parse(self, model: str, kwargs: dict[str, Any], schema: type[BaseModel]) -> LLMResult:
        resp = self._client.chat.completions.parse(response_format=schema, **kwargs)
        message = resp.choices[0].message
        if getattr(message, "refusal", None):
            return LLMResult(
                stop_reason="refusal",
                degraded=True,
                usage=self._usage(resp),
                cost_usd=self._cost(model, resp),
            )
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            repaired = dict(kwargs)
            repaired["messages"] = [*kwargs["messages"], {"role": "user", "content": _REPAIR_HINT}]
            try:
                resp2 = self._client.chat.completions.parse(response_format=schema, **repaired)
                parsed2 = getattr(resp2.choices[0].message, "parsed", None)
                if parsed2 is not None:
                    return LLMResult(
                        parsed=parsed2,
                        usage=self._usage(resp2),
                        cost_usd=self._cost(model, resp2),
                        stop_reason=resp2.choices[0].finish_reason or "stop",
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
            stop_reason=resp.choices[0].finish_reason or "stop",
        )

    def _message(self, model: str, kwargs: dict[str, Any]) -> LLMResult:
        resp = self._client.chat.completions.create(**kwargs)
        message = resp.choices[0].message
        if getattr(message, "refusal", None):
            return LLMResult(
                stop_reason="refusal",
                degraded=True,
                usage=self._usage(resp),
                cost_usd=self._cost(model, resp),
            )
        return LLMResult(
            text=message.content or "",
            usage=self._usage(resp),
            cost_usd=self._cost(model, resp),
            stop_reason=resp.choices[0].finish_reason or "stop",
        )

    def _usage(self, resp: Any) -> Usage:
        u = getattr(resp, "usage", None)
        if u is None:
            return Usage()
        return Usage(
            input_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(u, "completion_tokens", 0) or 0),
        )

    def _cost(self, model: str, resp: Any) -> float:
        pricing = self._config.pricing_for(model)
        if pricing is None:
            return 0.0
        u = self._usage(resp)
        return compute_cost(u.input_tokens, u.output_tokens, pricing)
