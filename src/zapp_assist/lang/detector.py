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
