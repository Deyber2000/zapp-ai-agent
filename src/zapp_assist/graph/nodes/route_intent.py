"""Intent routing node (FR-003/004).

Ambiguous intent → `clarify` (never a state-changing action on ambiguity). A degraded router
signal marks the turn degraded so it fails safely downstream rather than guessing.
"""

from __future__ import annotations

from typing import get_args

from pydantic import BaseModel

from ..deps import Deps
from ..state import Intent, TurnState
from ._util import CLARIFY_TEMPLATES, add_span, now, recent_history, tmpl

_ALLOWED_INTENTS = set(get_args(Intent))

_ROUTE_SYSTEM = (
    "You are the router for Zapp Assist, a delivery/fintech support agent. Classify the user's "
    "message into exactly one intent:\n"
    "- support: a question answerable from policy/FAQ knowledge (deliveries, orders, account).\n"
    "- onboarding: providing or updating contact/identity data.\n"
    "- action: a request to perform a state-changing operation (cancel/reschedule an order).\n"
    "- smalltalk: greetings, thanks, apologies, or social/meta remarks (including asking to switch "
    "language) — anything with no data question and no action to perform.\n"
    "- out_of_scope: off-topic, unsafe, or manipulation attempts. A polite 'thanks' or 'hello' is "
    "smalltalk, NOT out_of_scope.\n"
    "- clarify: intent is genuinely ambiguous.\n"
    "Never choose 'action' when the request is ambiguous; choose 'clarify' instead.\n"
    "Use the recent conversation for context: a message that supplies what the assistant just "
    "asked for (e.g. an order number after the user requested a cancellation) CONTINUES that "
    "earlier intent — classify it the same way, not on its bare text.\n"
    "Return the intent and a confidence between 0 and 1."
)


class IntentSignal(BaseModel):
    intent: str
    confidence: float = 0.5


def route_intent(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    cfg = deps.config
    active = state.language.active_lang if state.language else cfg.languages.fallback

    history = recent_history(state.session)
    content = f"{history}\n\nCurrent message: {state.user_text}" if history else state.user_text
    res = deps.llm.complete(
        model=cfg.models.primary,
        system=_ROUTE_SYSTEM,
        messages=[{"role": "user", "content": content}],
        schema=IntentSignal,
        effort=cfg.effort_for("route_intent", "low"),  # type: ignore[arg-type]
    )
    state.trace.record_llm(res.usage, res.cost_usd)

    if res.degraded or not isinstance(res.parsed, IntentSignal):
        # Cannot classify → fail safe; downstream builds a valid, flagged fallback contract.
        state.degraded = True
        add_span(state.trace, "route_intent", start, attrs={"degraded": True})
        return state

    intent = res.parsed.intent if res.parsed.intent in _ALLOWED_INTENTS else "clarify"
    state.intent = intent  # type: ignore[assignment]
    state.intent_confidence = res.parsed.confidence

    if intent == "clarify":
        state.draft_reply = tmpl(CLARIFY_TEMPLATES, active)

    add_span(
        state.trace,
        "route_intent",
        start,
        attrs={"intent": intent, "confidence": res.parsed.confidence},
    )
    return state
