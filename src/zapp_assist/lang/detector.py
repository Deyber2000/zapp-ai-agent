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

# Common languages OUTSIDE the supported set. Used only by the broad guard so a genuinely
# unsupported language is recognised (US3) instead of being forced into the nearest supported one.
_GUARD_DISTRACTORS = (Language.FRENCH, Language.GERMAN, Language.ITALIAN)


class LanguageResult(BaseModel):
    """Detected language plus the (session-locked) active language and confidence."""

    detected_lang: str
    active_lang: str
    lang_confidence: float
    # Gap between the top language's confidence and the runner-up. lingua normalises mass across
    # candidates, so es/pt split it and rarely clear an absolute floor even when unambiguous; a
    # clear margin is the stronger signal that a detection is decisive.
    margin: float = 0.0


@runtime_checkable
class LanguageDetector(Protocol):
    def detect(self, text: str) -> LanguageResult: ...

    def language_of(self, text: str) -> tuple[str, float]: ...

    def is_foreign(self, text: str, min_confidence: float = 0.75) -> tuple[str, float] | None: ...


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
        self._supported = {_LANGUAGE_TO_ISO[lang] for lang in langs}
        # Broad guard: supported + a few common distractors, so a genuinely unsupported language is
        # recognised (US3) rather than silently mapped to the nearest supported one.
        guard_langs = list(dict.fromkeys([*langs, *_GUARD_DISTRACTORS]))
        self._guard = LanguageDetectorBuilder.from_languages(*guard_langs).build()

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
        runner_up = float(values[1].value) if len(values) > 1 else 0.0
        lang = _LANGUAGE_TO_ISO.get(top.language, self._fallback)
        return LanguageResult(
            detected_lang=lang,
            active_lang=lang,
            lang_confidence=float(top.value),
            margin=round(float(top.value) - runner_up, 4),
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

    def is_foreign(self, text: str, min_confidence: float = 0.75) -> tuple[str, float] | None:
        """Detect a confidently UNSUPPORTED language (US3). Returns (iso, confidence) or None.

        Uses the broad guard (supported + common distractors); returns a result only when the top
        language is outside the supported set with confidence at or above `min_confidence` — so an
        unsupported language degrades safely instead of being forced into the nearest supported one.
        """

        cleaned = (text or "").strip()
        if not cleaned:
            return None
        values = self._guard.compute_language_confidence_values(cleaned)
        if not values:
            return None
        top = values[0]
        iso = top.language.iso_code_639_1.name.lower()
        if iso not in self._supported and top.value >= min_confidence:
            return iso, float(top.value)
        return None


def apply_switch_policy(
    *,
    active_lang: str | None,
    detected: str,
    confidence: float,
    margin: float,
    substantial: bool,
    pending_lang: str | None,
    pending_count: int,
    supported: list[str],
    lock_threshold: float,
    switch_min_confidence: float,
    min_margin: float,
    switch_turns: int,
) -> tuple[str | None, str | None, int, bool]:
    """Language lock / persist / switch policy (002). Pure and deterministic (Principle X).

    Returns ``(locked_lang, pending_lang, pending_count, switched)``:
      * ``locked_lang`` — the session's ``active_lang`` after this turn (``None`` = not yet locked;
        the caller uses the fallback for the turn but does not persist a lock).
      * ``pending_lang`` / ``pending_count`` — the sustained-switch accumulator after this turn.
      * ``switched`` — ``True`` iff a sustained switch changed the locked language this turn.

    Not-yet-locked: lock on the first confident supported detection (parity with 001) — where a high
    absolute confidence locks even a one-word message, but the weaker margin rescue locks only when
    the message is substantial, so a lone ambiguous token never locks the session. Locked: a
    matching / weak / short / unsupported turn keeps the lock and resets the accumulator; a
    confident, substantial turn in a *different* supported language accumulates, and switches at
    ``switch_turns`` consecutive such turns — so a single foreign phrase never flips the language.

    "Confident" is ``confidence >= threshold`` OR ``margin >= min_margin``: lingua normalises mass
    across candidates, so es/pt split it and rarely clear an absolute floor even when unambiguous —
    a clear margin over the runner-up rescues those (a right answer the absolute rule discards).
    """

    def confident(threshold: float) -> bool:
        return confidence >= threshold or margin >= min_margin

    if active_lang is None:
        # First lock: a high ABSOLUTE confidence locks even a one-word message (parity with 001),
        # but the margin rescue — which over-fires on short ambiguous tokens ("vale"/"sim"/"ya") —
        # locks only on a substantial message, so a single ambiguous token never locks the session.
        strong = confidence >= lock_threshold
        if detected in supported and (strong or (substantial and margin >= min_margin)):
            return detected, None, 0, False  # first lock (not a "switch")
        return None, None, 0, False  # stay unlocked; caller uses fallback

    if (
        not substantial
        or detected == active_lang
        or detected not in supported
        or not confident(switch_min_confidence)
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
        detected_lang=lang,
        active_lang=lang,
        lang_confidence=round(confidence, 4),
        margin=deterministic.margin,
    )
