"""Grounded support answer node (US1, FR-005/006).

Retrieve from the KB; if nothing clears the grounding threshold, decline and flag for review rather
than inventing. Otherwise ask the LLM to answer strictly from the retrieved context, in the active
language, and contribute a grounding-confidence signal.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..deps import Deps
from ..state import TurnState
from ._util import DECLINE_TEMPLATES, add_span, now, tmpl

_LANG_NAMES = {"es": "Spanish", "en": "English", "pt": "Portuguese"}


class GroundedAnswer(BaseModel):
    """The responder's structured answer. `grounded=False` forces a decline."""

    reply: str
    citations: list[str] = []
    grounded: bool = True


def _grounded_system(active_lang: str) -> str:
    language = _LANG_NAMES.get(active_lang, "English")
    return (
        "You are Zapp Assist, a delivery/fintech support agent. Answer the user's question using "
        "ONLY the provided context snippets. Do not invent policy or add facts that are not in the "
        f"context. Reply in {language}. Cite the ids of the snippets you used. If the context does "
        "not contain the answer, set grounded=false and do not answer."
    )


def _format_context(state: TurnState) -> str:
    docs = state.retrieval or []
    return "\n\n".join(f"[{doc.id}] {doc.title}: {doc.text}" for doc in docs)


def _score_to_confidence(score: float) -> float:
    # Map a positive BM25 score onto a bounded grounding confidence.
    return round(min(1.0, 0.6 + 0.05 * score), 4)


def _decline(
    state: TurnState, active: str, confidence: float, start: float, attrs: dict
) -> TurnState:
    state.draft_reply = tmpl(DECLINE_TEMPLATES, active)
    state.grounding_confidence = confidence
    state.needs_review_override = True
    add_span(state.trace, "support_rag", start, attrs=attrs)
    return state


def support_rag(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    cfg = deps.config
    active = state.language.active_lang if state.language else cfg.languages.fallback

    # `on_llm` folds any query-expansion (RAG-Fusion / HyDE) token cost into this turn's trace.
    hits = deps.rag.search(state.user_text, on_llm=state.trace.record_llm) if deps.rag else []
    if not hits:
        state.retrieval = []
        return _decline(state, active, 0.2, start, {"grounded": False, "hits": 0})

    docs = [doc for doc, _ in hits]
    top_score = hits[0][1]
    state.retrieval = docs

    res = deps.llm.complete(
        model=cfg.models.primary,
        system=_grounded_system(active),
        messages=[
            {
                "role": "user",
                "content": f"Question: {state.user_text}\n\nContext:\n{_format_context(state)}",
            }
        ],
        schema=GroundedAnswer,
        effort=cfg.effort_for("support_rag", "medium"),  # type: ignore[arg-type]
    )
    state.trace.record_llm(res.usage, res.cost_usd)

    answer = res.parsed if isinstance(res.parsed, GroundedAnswer) else None
    if res.degraded or answer is None or not answer.grounded or not answer.reply.strip():
        return _decline(state, active, 0.3, start, {"grounded": False, "hits": len(docs)})

    state.draft_reply = answer.reply.strip()
    state.reply_from_model = True  # free text — must pass reply-language verification (002)
    state.grounding_confidence = _score_to_confidence(top_score)
    add_span(
        state.trace,
        "support_rag",
        start,
        attrs={"grounded": True, "hits": len(docs), "top_score": round(top_score, 3)},
    )
    return state
