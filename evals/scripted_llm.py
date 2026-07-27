"""Deterministic scripted LLM for the eval (spec 004) — eval-owned, no dependency on `tests/`.

Implements the agent's `LLMClient` protocol. Each turn supplies a `MockScript`; this client answers
whatever structured schema the agent requests (dispatch by schema name) from the current turn's
script. The runner advances via `use_turn`. Unknown schemas → a safe degraded result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from zapp_assist.llm.client import LLMResult, Msg, Usage

from .models import MockScript

# Modest, fixed accounting so cost/latency metrics have realistic (deterministic) data.
_USAGE = Usage(input_tokens=90, output_tokens=45)
_COST = 0.0009


class ScriptedLLM:
    """A deterministic `LLMClient` driven by a list of per-turn `MockScript`s."""

    def __init__(self, scripts: list[MockScript]) -> None:
        self._scripts = scripts or [MockScript()]
        self._turn = 0

    def use_turn(self, index: int) -> None:
        self._turn = min(max(index, 0), len(self._scripts) - 1)

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
        script = self._scripts[self._turn]
        parsed = self._build(schema, script) if schema is not None else None
        if schema is not None and parsed is None:
            return LLMResult(degraded=True, stop_reason="malformed", usage=_USAGE, cost_usd=_COST)
        return LLMResult(parsed=parsed, text=script.reply or "", usage=_USAGE, cost_usd=_COST)

    def _build(self, schema: type[BaseModel], s: MockScript) -> BaseModel | None:
        name = schema.__name__
        if name == "LangSignal":
            return schema(lang=s.lang, confidence=0.96)
        if name == "IntentSignal":
            return schema(intent=s.intent, confidence=0.95)
        if name == "GroundedAnswer":
            return schema(reply=s.reply or "", citations=s.citations, grounded=s.grounded)
        if name == "OnboardingExtraction":
            return schema(
                full_name=s.full_name,
                phone_raw=s.phone_raw,
                region_hint=s.region_hint,
                phone_normalized=s.phone_normalized,
            )
        if name == "ActionRequest":
            return schema(action=s.action or "unknown", order_id=s.order_id, new_time=s.new_time)
        if name == "SafetyAssessment":
            return schema(findings=[{"category": c} for c in s.safety_findings])
        if name == "RewrittenReply":
            return schema(reply=s.rewritten or s.reply or "")
        return None


def build_scripted_llm(scripts: list[MockScript]) -> ScriptedLLM:
    return ScriptedLLM(scripts)
