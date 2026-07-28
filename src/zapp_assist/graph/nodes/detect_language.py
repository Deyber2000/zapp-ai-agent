"""Language detection node: deterministic lingua + LLM fusion, with session lock (FR-021).

Language is resilient: if the LLM signal is degraded we simply fall back to the deterministic
detector — the turn is not marked degraded for a missing second opinion.
"""

from __future__ import annotations

from pydantic import BaseModel

from ...lang.detector import (
    LanguageResult,
    apply_switch_policy,
    detect_switch_request,
    fuse,
)
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

    # US3: a confidently UNSUPPORTED language degrades safely — reply in the fallback language, flag
    # for review, and do NOT lock/switch onto a misclassified supported language. Interrupts any
    # pending switch. The reply-language node then guarantees the reply is in the fallback language.
    foreign = deps.detector.is_foreign(state.user_text, cfg.thresholds.language_lock)
    if foreign is not None:
        iso, conf = foreign
        state.needs_review_override = True
        state.session.pending_switch_lang = None
        state.session.pending_switch_count = 0
        state.language = LanguageResult(
            detected_lang=iso, active_lang=cfg.languages.fallback, lang_confidence=round(conf, 4)
        )
        add_span(
            state.trace,
            "detect_language",
            start,
            attrs={"detected": iso, "active": cfg.languages.fallback, "unsupported": True},
        )
        return state

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

    # An explicit request to switch language ("reply in English") is honored at once, over the
    # sustained-switch accumulator: a direct instruction shouldn't need repeating. It flips the
    # active language (and resets any in-progress switch), while `detected_lang` still reports the
    # language this message was written in. smalltalk then confirms the switch in the new language.
    requested = (
        detect_switch_request(state.user_text, cfg.languages.supported)
        if cfg.languages.honor_explicit_switch
        else None
    )
    if requested is not None:
        state.session.active_lang = requested
        state.session.pending_switch_lang = None
        state.session.pending_switch_count = 0
        state.lang_switch_to = requested
        fused.active_lang = requested
        state.language = fused
        add_span(
            state.trace,
            "detect_language",
            start,
            attrs={
                "detected": fused.detected_lang,
                "active": requested,
                "switch_requested": requested,
            },
        )
        return state

    # Language lock/persist/switch policy (002). The deterministic detection drives the choice
    # (Principle X); an LLM disagreement only lowers `lang_confidence` via fuse(). A locked language
    # persists across weak/short turns and switches only on sustained, confident intent — a single
    # foreign phrase never flips it. A switch needs >= min_words: single-word borrowed tokens
    # (ok/thanks/obrigado) read as confident in another language but are socially borrowed.
    thr = cfg.thresholds
    substantial = len(state.user_text.split()) >= thr.language_switch_min_words
    locked, pending_lang, pending_count, switched = apply_switch_policy(
        active_lang=state.session.active_lang,
        detected=deterministic.detected_lang,
        confidence=deterministic.lang_confidence,
        margin=deterministic.margin,
        substantial=substantial,
        pending_lang=state.session.pending_switch_lang,
        pending_count=state.session.pending_switch_count,
        supported=cfg.languages.supported,
        lock_threshold=thr.language_lock,
        switch_min_confidence=thr.language_switch_min_confidence,
        min_margin=thr.language_confident_min_margin,
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
