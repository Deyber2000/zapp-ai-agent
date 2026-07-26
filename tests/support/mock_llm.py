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
        text = _last_user(call)
        if name == "LangSignal":
            return call.schema(lang=_guess_lang(text), confidence=0.95)
        if name == "IntentSignal":
            return call.schema(intent=_guess_intent(text), confidence=0.9)
        if name == "GroundedAnswer":
            return call.schema(
                reply=f"(mock grounded answer) {text}".strip(), citations=[], grounded=True
            )
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
) -> MockLLMClient:
    """Build a mock whose LangSignal / IntentSignal / GroundedAnswer are fixed for a test case.

    Uses the schema class passed on each call, so no node schema needs importing here.
    """

    def responder(call: MockCall) -> Any:
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang=lang, confidence=lang_confidence)
        if name == "IntentSignal":
            return call.schema(intent=intent, confidence=intent_confidence)
        if name == "GroundedAnswer":
            text = reply if reply is not None else _last_user(call)
            return call.schema(reply=text, citations=citations or [], grounded=grounded)
        return None

    return MockLLMClient(responder=responder)


def _last_user(call: MockCall) -> str:
    for msg in reversed(call.messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


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
