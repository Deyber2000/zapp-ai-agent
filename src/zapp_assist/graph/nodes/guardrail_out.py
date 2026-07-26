"""Output guardrail node — runs before the result is returned (FR-019/020).

PII-leak → redact the reply; ungrounded/policy violations → replace with a safe decline and flag
for review. Decisions are recorded in the contract's `guardrails.output`.
"""

from __future__ import annotations

from ...guardrails.baseline import mask_pii
from ...guardrails.registry import GuardrailContext, governing_action
from ..deps import Deps
from ..state import TurnState
from ._util import GUARDRAIL_DECLINE_TEMPLATES, add_span, now, tmpl


def guardrail_out(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    active = state.language.active_lang if state.language else deps.config.languages.fallback
    reply = state.draft_reply

    ctx = GuardrailContext(
        stage="output",
        user_text=state.user_text,
        draft_reply=reply,
        active_lang=active,
        retrieval=state.retrieval,
    )
    decisions = deps.guardrails.run("output", ctx)
    state.guardrails_out = decisions

    # Most severe action governs (003): a refuse/escalate replaces the reply with a safe decline; a
    # redact masks PII spans. The offending content is never returned.
    if reply:
        gov = governing_action(decisions)
        if gov in ("refuse", "escalate"):
            reply = tmpl(GUARDRAIL_DECLINE_TEMPLATES, active)
            state.needs_review = True
        elif gov == "redact":
            reply = mask_pii(reply)
        state.draft_reply = reply

    # Fail-safe: an enabled-but-degraded semantic layer means the reply was not fully checked.
    if deps.guardrails.semantic_degraded:
        state.needs_review = True

    add_span(
        state.trace,
        "guardrail_out",
        start,
        attrs={"decisions": len(decisions), "sem_degraded": deps.guardrails.semantic_degraded},
    )
    return state
