"""Language detection: deterministic `lingua` baseline fused with the LLM signal.

(Constitution IX/X, FR-021.) `detect()` is the deterministic detector; `fuse()` combines it with the
LLM's language opinion — agreement raises confidence, disagreement lowers it and the deterministic
result wins (deterministic safety). Full language policy is deepened in spec `002`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from lingua import Language, LanguageDetectorBuilder
from pydantic import BaseModel

_ISO_TO_LANGUAGE = {
    "es": Language.SPANISH,
    "en": Language.ENGLISH,
    "pt": Language.PORTUGUESE,
}
_LANGUAGE_TO_ISO = {v: k for k, v in _ISO_TO_LANGUAGE.items()}


class LanguageResult(BaseModel):
    """Detected language plus the (session-locked) active language and confidence."""

    detected_lang: str
    active_lang: str
    lang_confidence: float


@runtime_checkable
class LanguageDetector(Protocol):
    def detect(self, text: str) -> LanguageResult: ...

    def language_of(self, text: str) -> tuple[str, float]: ...


class LinguaDetector:
    """Deterministic, offline detector over the supported languages."""

    def __init__(
        self, supported: tuple[str, ...] | list[str] = ("es", "en", "pt"), fallback: str = "en"
    ) -> None:
        langs = [_ISO_TO_LANGUAGE[c] for c in supported if c in _ISO_TO_LANGUAGE]
        if len(langs) < 2:  # lingua needs >= 2 languages to build a detector
            langs = [Language.SPANISH, Language.ENGLISH, Language.PORTUGUESE]
        self._detector = LanguageDetectorBuilder.from_languages(*langs).build()
        self._fallback = fallback

    def detect(self, text: str) -> LanguageResult:
        cleaned = (text or "").strip()
        if not cleaned:
            return LanguageResult(
                detected_lang=self._fallback, active_lang=self._fallback, lang_confidence=0.0
            )
        values = self._detector.compute_language_confidence_values(cleaned)
        if not values:
            return LanguageResult(
                detected_lang=self._fallback, active_lang=self._fallback, lang_confidence=0.0
            )
        top = values[0]
        lang = _LANGUAGE_TO_ISO.get(top.language, self._fallback)
        return LanguageResult(
            detected_lang=lang, active_lang=lang, lang_confidence=float(top.value)
        )

    def language_of(self, text: str) -> tuple[str, float]:
        """Detect the (supported) language of an arbitrary string + confidence (002 reply check).

        Returns the top supported language + confidence; empty/undetectable text → (fallback, 0.0).
        """

        cleaned = (text or "").strip()
        if not cleaned:
            return self._fallback, 0.0
        values = self._detector.compute_language_confidence_values(cleaned)
        if not values:
            return self._fallback, 0.0
        top = values[0]
        return _LANGUAGE_TO_ISO.get(top.language, self._fallback), float(top.value)


def apply_switch_policy(
    *,
    active_lang: str | None,
    detected: str,
    confidence: float,
    substantial: bool,
    pending_lang: str | None,
    pending_count: int,
    supported: list[str],
    lock_threshold: float,
    switch_min_confidence: float,
    switch_turns: int,
) -> tuple[str | None, str | None, int, bool]:
    """Language lock / persist / switch policy (002). Pure and deterministic (Principle X).

    Returns ``(locked_lang, pending_lang, pending_count, switched)``:
      * ``locked_lang`` — the session's ``active_lang`` after this turn (``None`` = not yet locked;
        the caller uses the fallback for the turn but does not persist a lock).
      * ``pending_lang`` / ``pending_count`` — the sustained-switch accumulator after this turn.
      * ``switched`` — ``True`` iff a sustained switch changed the locked language this turn.

    Not-yet-locked: lock on the first confident supported detection (parity with 001). Locked: a
    matching / weak / short / unsupported turn keeps the lock and resets the accumulator; a
    confident, substantial turn in a *different* supported language accumulates, and switches at
    ``switch_turns`` consecutive such turns — so a single foreign phrase never flips the language.
    """

    if active_lang is None:
        if detected in supported and confidence >= lock_threshold:
            return detected, None, 0, False  # first lock (not a "switch")
        return None, None, 0, False  # stay unlocked; caller uses fallback

    if (
        not substantial
        or detected == active_lang
        or detected not in supported
        or confidence < switch_min_confidence
    ):
        return active_lang, None, 0, False  # weak / match → keep lock, reset accumulator

    if detected == pending_lang:
        count = pending_count + 1
        if count >= switch_turns:
            return detected, None, 0, True  # sustained switch
        return active_lang, detected, count, False
    return active_lang, detected, 1, False  # new candidate language → start accumulating


def fuse(
    deterministic: LanguageResult,
    llm_lang: str | None,
    llm_confidence: float | None,
    supported: list[str],
    fallback: str,
) -> LanguageResult:
    """Fuse deterministic + LLM signals; deterministic wins, disagreement lowers confidence."""

    lang = deterministic.detected_lang
    confidence = deterministic.lang_confidence

    if lang not in supported:
        # Unsupported language → graceful fallback with reduced confidence.
        return LanguageResult(
            detected_lang=fallback, active_lang=fallback, lang_confidence=min(confidence, 0.5)
        )

    if llm_lang and llm_lang in supported:
        if llm_lang == lang:
            second = llm_confidence if llm_confidence is not None else confidence
            confidence = min(1.0, (confidence + second) / 2 + 0.05)  # agreement boost
        else:
            confidence = max(0.0, confidence * 0.6)  # divergence lowers confidence

    return LanguageResult(
        detected_lang=lang, active_lang=lang, lang_confidence=round(confidence, 4)
    )
