"""Input guardrail node — runs before the turn is processed (FR-019/020)."""

from __future__ import annotations

from ...guardrails.registry import GuardrailContext
from ..deps import Deps
from ..state import TurnState
from ._util import add_span, now


def guardrail_in(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    ctx = GuardrailContext(
        stage="input",
        user_text=state.user_text,
        active_lang=state.session.active_lang or "en",
    )
    decisions = deps.guardrails.run("input", ctx)
    state.guardrails_in = decisions

    # A refuse/escalate decision blocks processing; the safe decline is finalised in `assemble`
    # once the active language is known. Escalations additionally flag the turn for review.
    if any(d.action in ("refuse", "escalate") for d in decisions):
        state.blocked = True
        if any(d.action == "escalate" for d in decisions):
            state.needs_review_override = True

    add_span(
        state.trace,
        "guardrail_in",
        start,
        attrs={"decisions": len(decisions), "blocked": state.blocked},
    )
    return state
