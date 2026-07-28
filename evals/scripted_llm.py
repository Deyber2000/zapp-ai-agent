"""Deterministic scripted LLM for the eval (spec 004) — eval-owned, no dependency on `tests/`.

Implements the agent's `LLMClient` protocol. Each turn supplies a `MockScript`; this client answers
whatever structured schema the agent requests (dispatch by schema name) from the current turn's
script. The runner advances via `use_turn`. Unknown schemas → a safe degraded result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from zapp_assist.llm.client import LLMResult, Msg, Usage
from zapp_assist.tools.mock_backend import READ_ONLY, STATE_CHANGING

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
        parsed = self._build(schema, script, messages) if schema is not None else None
        if schema is not None and parsed is None:
            return LLMResult(degraded=True, stop_reason="malformed", usage=_USAGE, cost_usd=_COST)
        return LLMResult(parsed=parsed, text=script.reply or "", usage=_USAGE, cost_usd=_COST)

    def _build(
        self, schema: type[BaseModel], s: MockScript, messages: list[Msg]
    ) -> BaseModel | None:
        name = schema.__name__
        if name == "LangSignal":
            return schema(lang=s.lang, confidence=0.96)
        if name == "AgentStep":
            return _agent_step(schema, s, messages)
        if name == "OnboardingExtraction":
            return schema(
                full_name=s.full_name,
                phone_raw=s.phone_raw,
                region_hint=s.region_hint,
                phone_normalized=s.phone_normalized,
            )
        if name == "SafetyAssessment":
            return schema(findings=[{"category": c} for c in s.safety_findings])
        if name == "RewrittenReply":
            return schema(reply=s.rewritten or s.reply or "")
        return None


def _agent_step(schema: type[BaseModel], s: MockScript, messages: list[Msg]) -> BaseModel:
    """Synthesize the agent's next `AgentStep` from a per-turn script (conversation-driven).

    Mirrors the tests' mock: support answers retrieve then answer; reads / state-changes are one
    tool step; onboarding / smalltalk / out_of_scope / clarify hand off to a specialist.
    """

    if s.intent in ("onboarding", "smalltalk", "out_of_scope", "clarify"):
        return schema(tool="handoff", target=s.intent)
    if s.intent == "action":
        if s.action in READ_ONLY:
            return schema(tool=s.action, order_id=s.order_id)
        if s.action in STATE_CHANGING:
            return schema(
                tool=s.action, order_id=s.order_id, new_time=s.new_time, field=s.field,
                value=s.value,
            )
        return schema(tool="handoff", target="clarify")
    if not _kb_done(messages):
        return schema(tool="search_kb", query=_current_message(messages))
    empty = any(str(m.get("content", "")) == "KB snippets:\nnone" for m in messages)
    return schema(tool="answer", reply=s.reply or "", grounded=s.grounded and not empty)


def _current_message(messages: list[Msg]) -> str:
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            marker = "Current message: "
            return content.split(marker, 1)[1] if marker in content else content
    return ""


def _kb_done(messages: list[Msg]) -> bool:
    return any(
        msg.get("role") == "user" and str(msg.get("content", "")).startswith("KB snippets:")
        for msg in messages
    )


def build_scripted_llm(scripts: list[MockScript]) -> ScriptedLLM:
    return ScriptedLLM(scripts)
