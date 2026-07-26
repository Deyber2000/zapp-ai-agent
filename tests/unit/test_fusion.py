"""Unit tests for language signal fusion (Constitution IX/X).

Agreement raises confidence; disagreement lowers it and the deterministic detection wins; an
unsupported language degrades to the fallback with reduced confidence.
"""

from __future__ import annotations

from zapp_assist.lang.detector import LanguageResult, fuse

_SUPPORTED = ["es", "en", "pt"]
_FALLBACK = "en"


def _det(lang: str, conf: float) -> LanguageResult:
    return LanguageResult(detected_lang=lang, active_lang=lang, lang_confidence=conf)


def test_agreement_raises_confidence() -> None:
    fused = fuse(_det("es", 0.70), "es", 0.90, _SUPPORTED, _FALLBACK)
    assert fused.detected_lang == "es"
    assert fused.lang_confidence > 0.70  # agreement boost


def test_divergence_lowers_confidence_and_deterministic_wins() -> None:
    fused = fuse(_det("es", 0.80), "en", 0.95, _SUPPORTED, _FALLBACK)
    assert fused.detected_lang == "es"  # deterministic wins despite a confident LLM disagreement
    assert fused.lang_confidence < 0.80


def test_unsupported_language_degrades_to_fallback() -> None:
    fused = fuse(_det("fr", 0.90), None, None, _SUPPORTED, _FALLBACK)
    assert fused.detected_lang == _FALLBACK
    assert fused.lang_confidence <= 0.5


def test_missing_llm_signal_keeps_deterministic_result() -> None:
    fused = fuse(_det("pt", 0.66), None, None, _SUPPORTED, _FALLBACK)
    assert fused.detected_lang == "pt"
    assert fused.lang_confidence == 0.66
