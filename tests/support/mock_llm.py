"""Deterministic mock `LLMClient` — the ONLY LLM used in tests (zero live API calls).

Scriptable per schema (by `schema.__name__`) or via a global `responder`. Honors the fault-injection
env flag `ZAPP_FAULT`:
  * ``timeout``    → returns a degraded result (as the real adapter would after exhausting retries);
  * ``malformed``  → returns a degraded result with no parsed output (repair failed);
  * ``tool_error`` → raises, to exercise the graph node runner's exception handling.

Unscripted known node schemas fall back to sensible, deterministic defaults so the full pipeline can
be driven end-to-end without bespoke scripting on every test.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from zapp_assist.llm.client import LLMResult, Msg, Usage
from zapp_assist.tools.mock_backend import READ_ONLY, STATE_CHANGING

# Distinctive markers only (avoid ES/PT-shared words like "entrega"/"pedido"/"conta").
_ES_HINTS = re.compile(
    r"\b(hola|reprogramar|cuenta|contraseña|gracias|puedo|número|numero|mi|cómo|como)\b", re.I
)
_PT_HINTS = re.compile(
    r"\b(olá|ola|você|voce|reagendar|senha|obrigado|até|ate|minha|meu|conta)\b", re.I
)
_ACTION_HINTS = re.compile(r"\b(cancel|cancelar|reschedule|reagendar|refund|reembolso)\b", re.I)
_ONBOARD_HINTS = re.compile(
    r"\b(my (number|phone|email)|mi (numero|número|correo)|onboard|sign ?up)\b", re.I
)


@dataclass
class MockCall:
    model: str
    system: str
    messages: list[Msg]
    schema: type[BaseModel] | None
    tools: Any


Responder = Callable[[MockCall], Any]


@dataclass
class MockLLMClient:
    """A scriptable, deterministic LLM client implementing the `LLMClient` protocol."""

    by_schema: dict[str, Any] = field(default_factory=dict)
    responder: Responder | None = None
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=90, output_tokens=45))
    cost_usd: float = 0.0009

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Msg],
        schema: type[BaseModel] | None = None,
        tools: Any = None,
        effort: str = "medium",
        temperature: float | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult:
        fault = os.environ.get("ZAPP_FAULT")
        if fault == "timeout":
            return LLMResult(degraded=True, stop_reason="timeout")
        if fault == "malformed":
            return LLMResult(degraded=True, stop_reason="malformed")
        if fault == "tool_error":
            raise RuntimeError("ZAPP_FAULT=tool_error simulated failure")

        call = MockCall(model, system, list(messages), schema, tools)
        out = self._resolve(call)

        if schema is not None:
            if isinstance(out, schema):
                return LLMResult(parsed=out, usage=self.usage, cost_usd=self.cost_usd)
            # Could not produce a valid parsed object → fail closed (degraded).
            return LLMResult(
                degraded=True, stop_reason="malformed", usage=self.usage, cost_usd=self.cost_usd
            )
        if isinstance(out, str):
            return LLMResult(text=out, usage=self.usage, cost_usd=self.cost_usd)
        return LLMResult(text="", usage=self.usage, cost_usd=self.cost_usd, degraded=out is None)

    # -- internals ---------------------------------------------------------------------------

    def _resolve(self, call: MockCall) -> Any:
        if self.responder is not None:
            result = self.responder(call)
            if result is not None:
                return result
        if call.schema is not None:
            key = call.schema.__name__
            if key in self.by_schema:
                value = self.by_schema[key]
                if callable(value) and not isinstance(value, type):
                    return value(call)
                return value
            return self._default_for(call)
        return None

    def _default_for(self, call: MockCall) -> Any:
        assert call.schema is not None
        name = call.schema.__name__
        cur = _current_message(call)
        if name == "LangSignal":
            return call.schema(lang=_guess_lang(cur), confidence=0.95)
        if name == "AgentStep":
            # No script: onboarding-looking input hands off; everything else answers from the KB.
            intent = "onboarding" if _ONBOARD_HINTS.search(cur) else "support"
            return agent_step(call.schema, call, intent=intent)
        return None


def scripted_llm(
    *,
    lang: str,
    lang_confidence: float = 0.97,
    intent: str = "support",
    intent_confidence: float = 0.95,
    reply: str | None = None,
    citations: list[str] | None = None,
    grounded: bool = True,
    action: str | None = None,
    order_id: str | None = None,
    new_time: str | None = None,
    field: str | None = None,
    value: str | None = None,
) -> MockLLMClient:
    """Build a mock whose LangSignal + AgentStep are fixed for a test case.

    `intent`/`action` map onto the tool the agent would choose (support → search_kb then answer;
    action → a read/state-change tool; onboarding/smalltalk/out_of_scope → handoff). Uses the schema
    class passed on each call, so no node schema needs importing here.
    """

    def responder(call: MockCall) -> Any:
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang=lang, confidence=lang_confidence)
        if name == "AgentStep":
            return agent_step(
                call.schema, call, intent=intent, action=action, reply=reply, grounded=grounded,
                order_id=order_id, new_time=new_time, field=field, value=value,
            )
        return None

    return MockLLMClient(responder=responder)


def agent_step(
    schema: type[BaseModel],
    call: MockCall,
    *,
    intent: str = "support",
    action: str | None = None,
    reply: str | None = None,
    grounded: bool = True,
    order_id: str | None = None,
    new_time: str | None = None,
    field: str | None = None,
    value: str | None = None,
) -> BaseModel:
    """Synthesize the agent's next `AgentStep` from a legacy-style script, conversation-driven.

    Support answers take two steps (search_kb, then answer once snippets are present); reads and
    state-changes are a single tool step; onboarding/smalltalk/out_of_scope/clarify hand off.
    """

    cur = _current_message(call)
    if intent in ("onboarding", "smalltalk", "out_of_scope", "clarify"):
        return schema(tool="handoff", target=intent)
    if intent == "action":
        if action in READ_ONLY:
            return schema(tool=action, order_id=order_id)
        if action in STATE_CHANGING:
            return schema(
                tool=action, order_id=order_id, new_time=new_time, field=field, value=value
            )
        return schema(tool="handoff", target="clarify")  # action intent with no concrete tool
    if not _kb_done(call):  # support: retrieve first
        return schema(tool="search_kb", query=cur)
    text = reply if reply is not None else f"(mock grounded answer) {cur}".strip()
    # Empty retrieval → nothing to ground on, so the model declines (grounded=false), as the old
    # support node did before ever calling the LLM.
    return schema(tool="answer", reply=text, grounded=grounded and not _kb_empty(call))


def _last_user(call: MockCall) -> str:
    for msg in reversed(call.messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _current_message(call: MockCall) -> str:
    """The turn's current message — the agent prepends recent history as 'Current message: <x>'."""

    for msg in call.messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            marker = "Current message: "
            return content.split(marker, 1)[1] if marker in content else content
    return ""


def _kb_done(call: MockCall) -> bool:
    """True once a search_kb observation has been fed back into the working context."""

    return any(
        msg.get("role") == "user" and str(msg.get("content", "")).startswith("KB snippets:")
        for msg in call.messages
    )


def _kb_empty(call: MockCall) -> bool:
    """True when search_kb returned nothing — the observation is the literal 'none'."""

    return any(
        msg.get("role") == "user" and str(msg.get("content", "")) == "KB snippets:\nnone"
        for msg in call.messages
    )


def _guess_lang(text: str) -> str:
    if _PT_HINTS.search(text):
        return "pt"
    if _ES_HINTS.search(text):
        return "es"
    return "en"


def _guess_intent(text: str) -> str:
    if _ACTION_HINTS.search(text):
        return "action"
    if _ONBOARD_HINTS.search(text):
        return "onboarding"
    return "support"
