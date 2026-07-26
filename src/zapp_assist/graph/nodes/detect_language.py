"""Language detection node: deterministic lingua + LLM fusion, with session lock (FR-021).

Language is resilient: if the LLM signal is degraded we simply fall back to the deterministic
detector — the turn is not marked degraded for a missing second opinion.
"""

from __future__ import annotations

from pydantic import BaseModel

from ...lang.detector import fuse
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

    # Session language lock: keep an already-locked language; otherwise lock on a confident
    # deterministic detection (deterministic wins for this correctness-critical choice, Principle
    # X — an LLM disagreement lowers `lang_confidence` but does not by itself flip active_lang).
    # Fall back to the default only when detection is genuinely unsupported/low-confidence.
    if state.session.active_lang:
        active = state.session.active_lang
    elif (
        fused.detected_lang in cfg.languages.supported
        and deterministic.lang_confidence >= cfg.thresholds.language_lock
    ):
        active = fused.detected_lang
        state.session.active_lang = active
    else:
        active = cfg.languages.fallback
        if fused.detected_lang not in cfg.languages.supported:
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
            "llm_agrees": llm_lang == fused.detected_lang if llm_lang else None,
        },
    )
    return state
