"""Language detection node: deterministic lingua + LLM fusion, with session lock (FR-021).

Language is resilient: if the LLM signal is degraded we simply fall back to the deterministic
detector — the turn is not marked degraded for a missing second opinion.
"""

from __future__ import annotations

from pydantic import BaseModel

from ...lang.detector import apply_switch_policy, fuse
from ..deps import Deps
from ..state import TurnState
from ._util import add_span, now

_LANG_SYSTEM = (
    "You identify the language of the user's message. Respond with the ISO 639-1 code "
    "(one of: es, en, pt) and a confidence between 0 and 1."
)


class LangSignal(BaseModel):
    """The LLM's language opinion, fused with the deterministic detector."""

    lang: str
    confidence: float = 0.5


def detect_language(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    cfg = deps.config
    deterministic = deps.detector.detect(state.user_text)

    llm_lang: str | None = None
    llm_conf: float | None = None
    res = deps.llm.complete(
        model=cfg.models.primary,
        system=_LANG_SYSTEM,
        messages=[{"role": "user", "content": state.user_text}],
        schema=LangSignal,
        effort=cfg.effort_for("detect_language", "low"),  # type: ignore[arg-type]
    )
    state.trace.record_llm(res.usage, res.cost_usd)
    if not res.degraded and isinstance(res.parsed, LangSignal):
        llm_lang = res.parsed.lang
        llm_conf = res.parsed.confidence

    fused = fuse(
        deterministic, llm_lang, llm_conf, cfg.languages.supported, cfg.languages.fallback
    )

    # Language lock/persist/switch policy (002). The deterministic detection drives the choice
    # (Principle X); an LLM disagreement only lowers `lang_confidence` via fuse(). A locked language
    # persists across weak/short turns and switches only on sustained, confident intent — a single
    # foreign phrase never flips it. Short turns cannot drive a switch (too little signal).
    thr = cfg.thresholds
    substantial = len(state.user_text.strip()) >= thr.language_switch_min_chars
    locked, pending_lang, pending_count, switched = apply_switch_policy(
        active_lang=state.session.active_lang,
        detected=deterministic.detected_lang,
        confidence=deterministic.lang_confidence,
        substantial=substantial,
        pending_lang=state.session.pending_switch_lang,
        pending_count=state.session.pending_switch_count,
        supported=cfg.languages.supported,
        lock_threshold=thr.language_lock,
        switch_min_confidence=thr.language_switch_min_confidence,
        switch_turns=thr.language_switch_turns,
    )
    state.session.active_lang = locked
    state.session.pending_switch_lang = pending_lang
    state.session.pending_switch_count = pending_count

    active = locked if locked is not None else cfg.languages.fallback
    if locked is None and fused.detected_lang not in cfg.languages.supported:
        state.needs_review_override = True

    fused.active_lang = active
    state.language = fused

    add_span(
        state.trace,
        "detect_language",
        start,
        attrs={
            "detected": fused.detected_lang,
            "active": active,
            "confidence": fused.lang_confidence,
            "switched": switched,
            "pending": pending_lang,
        },
    )
    return state
