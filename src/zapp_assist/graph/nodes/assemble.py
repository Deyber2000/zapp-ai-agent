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
    REPETITION_TEMPLATES,
    SAFE_FALLBACK_TEMPLATES,
    add_span,
    now,
    tmpl,
)

_HISTORY_LIMIT = 10  # bounded recent turns kept on the session for multi-turn coherence (FR-015)
_REPEAT_WINDOW = 3  # repetition guard compares against the last N replies (not just the previous)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _norm_reply(text: str) -> str:
    """Case/whitespace-insensitive key, so near-duplicates (a casing diff) also count as repeats."""

    return " ".join(text.split()).casefold()


def _recent_replies(state: TurnState) -> set[str]:
    return {_norm_reply(t.reply) for t in state.session.history[-_REPEAT_WINDOW:]}


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
    # Never retain raw PII in the contract: if the input guardrail redacted it, use the masked text
    # for final_normalized_text on every path — including the degraded/error fallbacks (FR-008).
    retained_input = state.redacted_input if state.redacted_input is not None else state.user_text

    try:
        active = state.language.active_lang if state.language else fallback_lang
        detected = state.language.detected_lang if state.language else active
        lang_conf = state.language.lang_confidence if state.language else 0.0

        reply = state.draft_reply
        if state.blocked and not reply:
            reply = tmpl(GUARDRAIL_DECLINE_TEMPLATES, active)

        # Repetition guard: don't re-emit a reply we just sent (e.g. a completed onboarding re-run
        # when the user supplies an already-captured detail). Compare against the last few replies,
        # normalized for case/whitespace, so the agent can't ping-pong reply/nudge/reply or slip a
        # near-duplicate. Skipped while an action awaits confirmation, where re-asking the same
        # question verbatim is intentional (never say "already shared that" to a pending confirm).
        if (
            reply
            and state.session.pending_action is None
            and _norm_reply(reply) in _recent_replies(state)
        ):
            reply = tmpl(REPETITION_TEMPLATES, active)

        if not reply or not reply.strip():
            # No usable reply (degraded/empty) → safe, flagged fallback.
            state.result = TurnResult.safe_fallback(
                reply=tmpl(SAFE_FALLBACK_TEMPLATES, active),
                active_lang=active,
                detected_lang=detected,
                lang_confidence=lang_conf,
                final_normalized_text=retained_input,
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
        # A deliberately normalized value (e.g. onboarding's E.164 phone) wins; otherwise the
        # retained (PII-masked when redacted) input.
        final_norm = norm.canonical if (norm and norm.canonical) else retained_input
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
            final_normalized_text=retained_input,
            guardrails=guardrails,
        )
        add_span(
            state.trace, "assemble", start, status="error", attrs={"error": type(exc).__name__}
        )
    return _record_history(state)
