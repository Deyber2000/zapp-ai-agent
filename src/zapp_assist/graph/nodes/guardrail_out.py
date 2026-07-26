"""Output guardrail node — runs before the result is returned (FR-019/020).

PII-leak → redact the reply; ungrounded/policy violations → replace with a safe decline and flag
for review. Decisions are recorded in the contract's `guardrails.output`.
"""

from __future__ import annotations

from ...guardrails.baseline import mask_pii
from ...guardrails.registry import GuardrailContext
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

    if reply:
        for decision in decisions:
            if decision.action == "redact":
                reply = mask_pii(reply)
            elif decision.action in ("refuse", "escalate"):
                reply = tmpl(GUARDRAIL_DECLINE_TEMPLATES, active)
                state.needs_review = True
        state.draft_reply = reply

    add_span(
        state.trace,
        "guardrail_out",
        start,
        attrs={"decisions": len(decisions)},
    )
    return state
