"""Reply-language verification node (002, FR-004/005; Constitution IX/X).

Turns "reply in the user's language" from a request into a verified guarantee. The check is
DETERMINISTIC (lingua, offline — no LLM): detect the draft reply's language and compare it to
`active_lang`. On a mismatch, make exactly ONE LLM correction re-ask to rewrite the reply in the
active language, then re-check; a persistent mismatch (or a degraded correction) is replaced by a
safe in-language message and flagged for review. The reply-language facts are recorded on the trace
for the `004` eval suite; the turn contract is unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..deps import Deps
from ..state import TurnState
from ._util import LANG_MISMATCH_TEMPLATES, add_span, now, tmpl

_LANG_NAMES = {"es": "Spanish", "en": "English", "pt": "Portuguese"}


class RewrittenReply(BaseModel):
    """The single correction re-ask: the same message rewritten in the active language."""

    reply: str


def _correction_system(active_lang: str) -> str:
    language = _LANG_NAMES.get(active_lang, "English")
    return (
        f"Rewrite the assistant's message in {language}, preserving its meaning and every detail "
        "exactly (numbers, names, ids unchanged). Do not answer anything new, add, or remove "
        f"information — only render the same message in {language}. Return just the rewritten text."
    )


def _span(state: TurnState, start: float, **attrs: object) -> TurnState:
    add_span(state.trace, "verify_reply_language", start, attrs=attrs)
    return state


def verify_reply_language(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    cfg = deps.config
    active = state.language.active_lang if state.language else cfg.languages.fallback
    reply = (state.draft_reply or "").strip()

    # Skip cleanly: no reply, or too short to detect a language reliably (treated as in-language).
    if not reply or len(reply) < cfg.thresholds.reply_verify_min_chars:
        state.reply_match = True if reply else None
        return _span(state, start, active=active, skipped_short=bool(reply))

    # Authored per-language templates are already in `active_lang` by construction; only free text
    # the model produced can drift. Verifying a template can only mislabel it (lingua confuses es/pt
    # on short strings) and, offline, replace a correct reply with a review message — e.g. overwrite
    # a completed state-changing action's success confirmation *after* the backend committed. So we
    # trust templates and verify only model-generated replies.
    if not state.reply_from_model:
        state.reply_lang, state.reply_match = active, True
        return _span(
            state, start, active=active, reply_lang=active, reply_match=True, trusted_template=True
        )

    reply_lang, _conf = deps.detector.language_of(reply)
    state.reply_lang = reply_lang
    if reply_lang == active:
        state.reply_match = True
        return _span(
            state, start, active=active, reply_lang=reply_lang, reply_match=True, corrected=False
        )

    # Mismatch → exactly ONE correction re-ask.
    state.reply_corrected = True
    res = deps.llm.complete(
        model=cfg.models.primary,
        system=_correction_system(active),
        messages=[{"role": "user", "content": reply}],
        schema=RewrittenReply,
        effort=cfg.effort_for("verify_reply_language", "low"),  # type: ignore[arg-type]
    )
    state.trace.record_llm(res.usage, res.cost_usd)

    rewritten = res.parsed.reply.strip() if isinstance(res.parsed, RewrittenReply) else ""
    if not res.degraded and rewritten:
        new_lang, _c2 = deps.detector.language_of(rewritten)
        if new_lang == active:
            state.draft_reply = rewritten
            state.reply_lang, state.reply_match = new_lang, True
            return _span(
                state, start, active=active, reply_lang=new_lang, reply_match=True, corrected=True
            )

    # Persistent mismatch (or degraded correction) → safe in-language message + flag for review.
    state.draft_reply = tmpl(LANG_MISMATCH_TEMPLATES, active)
    state.reply_match = False
    state.needs_review_override = True
    return _span(
        state, start, active=active, reply_lang=reply_lang, reply_match=False, corrected=True
    )
