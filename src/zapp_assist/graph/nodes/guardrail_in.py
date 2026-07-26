"""Input guardrail node — runs before the turn is processed (FR-019/020)."""

from __future__ import annotations

from ...guardrails.registry import GuardrailContext, governing_action
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

    # Most severe action governs (003): refuse/escalate block processing; the safe decline is
    # finalised in `assemble` once the active language is known. Escalations also flag for review.
    if governing_action(decisions) in ("refuse", "escalate"):
        state.blocked = True
    if any(d.action == "escalate" for d in decisions):
        state.needs_review_override = True
    # Fail-safe: if the semantic layer was enabled but degraded, we could not fully check → flag.
    if deps.guardrails.semantic_degraded:
        state.needs_review_override = True

    add_span(
        state.trace,
        "guardrail_in",
        start,
        attrs={
            "decisions": len(decisions),
            "blocked": state.blocked,
            "semantic_degraded": deps.guardrails.semantic_degraded,
        },
    )
    return state
