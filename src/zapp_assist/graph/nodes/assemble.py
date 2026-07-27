"""Contract assembly node (FR-002) — always returns a valid `TurnResult`.

Builds the canonical contract from the accumulated signals; on ANY error, or when no usable reply
was produced, it substitutes `TurnResult.safe_fallback(...)` (a guaranteed-valid contract with
`needs_review=true`). This is the fail-closed boundary of the whole turn.
"""

from __future__ import annotations

from ...contracts import Guardrails, TurnResult
from ...memory.session_store import TurnRef
from ..deps import Deps
from ..state import TurnState
from ._util import (
    GUARDRAIL_DECLINE_TEMPLATES,
    SAFE_FALLBACK_TEMPLATES,
    add_span,
    now,
    tmpl,
)

_HISTORY_LIMIT = 10  # bounded recent turns kept on the session for multi-turn coherence (FR-015)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _record_history(state: TurnState) -> TurnState:
    """Append this turn to the session's bounded history (so later turns have context)."""

    if state.result is not None:
        state.session.history.append(
            TurnRef(user_text=state.user_text, reply=state.result.reply, intent=state.intent)
        )
        del state.session.history[:-_HISTORY_LIMIT]  # keep only the most recent turns
    return state


def assemble(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    fallback_lang = deps.config.languages.fallback
    guardrails = Guardrails(input=state.guardrails_in, output=state.guardrails_out)

    try:
        active = state.language.active_lang if state.language else fallback_lang
        detected = state.language.detected_lang if state.language else active
        lang_conf = state.language.lang_confidence if state.language else 0.0

        reply = state.draft_reply
        if state.blocked and not reply:
            reply = tmpl(GUARDRAIL_DECLINE_TEMPLATES, active)

        if not reply or not reply.strip():
            # No usable reply (degraded/empty) → safe, flagged fallback.
            state.result = TurnResult.safe_fallback(
                reply=tmpl(SAFE_FALLBACK_TEMPLATES, active),
                active_lang=active,
                detected_lang=detected,
                lang_confidence=lang_conf,
                final_normalized_text=state.user_text,
                guardrails=guardrails,
            )
            add_span(state.trace, "assemble", start, attrs={"fallback": True})
            return _record_history(state)

        # A cleanly handled guardrail block is high-confidence and not degraded.
        if state.confidence is not None:
            score = state.confidence.score
        elif state.blocked:
            score = 0.9
        else:
            score = 0.3

        needs_review = state.needs_review or state.degraded or state.needs_review_override

        norm = state.normalization
        final_norm = norm.canonical if (norm and norm.canonical) else state.user_text
        country = norm.country if norm else None

        state.result = TurnResult(
            reply=reply,
            detected_lang=detected,
            active_lang=active,
            lang_confidence=_clamp(lang_conf),
            final_normalized_text=final_norm,
            detected_country=country,
            confidence_score=_clamp(score),
            needs_review=bool(needs_review),
            guardrails=guardrails,
        )
        add_span(state.trace, "assemble", start, attrs={"needs_review": bool(needs_review)})
    except Exception as exc:  # fail closed — never emit an invalid contract
        state.result = TurnResult.safe_fallback(
            reply=tmpl(SAFE_FALLBACK_TEMPLATES, fallback_lang),
            active_lang=fallback_lang,
            final_normalized_text=state.user_text,
            guardrails=guardrails,
        )
        add_span(
            state.trace, "assemble", start, status="error", attrs={"error": type(exc).__name__}
        )
    return _record_history(state)
