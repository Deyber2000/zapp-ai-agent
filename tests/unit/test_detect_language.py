"""Node-level: detect_language's word gate (002 US2) and margin-based lock (002 first-lock fix).

Closes the coverage gap that hid the miscalibrated gates — `test_switch_policy` exercises
`apply_switch_policy` directly (it takes `substantial`/`margin`), so the node's text→bool and
detector→margin plumbing was never tested. A stub detector keeps this deterministic (no embedding).
"""

from __future__ import annotations

from tests.support.mock_llm import MockLLMClient
from zapp_assist.config import load_config
from zapp_assist.graph.deps import Deps
from zapp_assist.graph.nodes.detect_language import detect_language
from zapp_assist.graph.state import TurnState
from zapp_assist.lang.detector import LanguageResult
from zapp_assist.memory.session_store import Session
from zapp_assist.obs.trace import Trace


class _StubDetector:
    """Fixed (lang, confidence, margin); never 'foreign' (a supported language). Deterministic."""

    def __init__(self, lang: str, confidence: float, margin: float = 0.0) -> None:
        self._lang, self._conf, self._margin = lang, confidence, margin

    def detect(self, text: str) -> LanguageResult:
        return LanguageResult(
            detected_lang=self._lang,
            active_lang=self._lang,
            lang_confidence=self._conf,
            margin=self._margin,
        )

    def language_of(self, text: str) -> tuple[str, float]:
        return self._lang, self._conf

    def is_foreign(self, text: str, min_confidence: float = 0.75) -> None:
        return None


def _run(text: str, active_lang: str | None, detector: _StubDetector) -> Session:
    # detect_language uses only config / detector / llm; guardrails/tools/rag are unused here.
    deps = Deps(
        config=load_config(),
        llm=MockLLMClient(),
        detector=detector,
        guardrails=None,  # not touched by this node
        tools=None,  # not touched by this node
    )
    session = Session(session_id="t", active_lang=active_lang)
    state = TurnState(
        turn_id="t-0", session=session, user_text=text, trace=Trace(turn_id="t-0", session_id="t")
    )
    detect_language(state, deps)
    return state.session


def test_single_word_borrowed_token_does_not_accumulate_switch() -> None:
    # "thanks": confidently English in an es session, but ONE word → not a switch signal.
    assert _run("thanks", "es", _StubDetector("en", 0.9)).pending_switch_count == 0


def test_multi_word_confident_turn_accumulates_switch() -> None:
    # "i need help": confidently English, three words → starts the sustained-switch accumulator.
    # (11 chars — the old char >= 12 floor wrongly blocked this; the word floor allows it.)
    assert _run("i need help", "es", _StubDetector("en", 0.9)).pending_switch_count == 1


def test_first_turn_locks_on_margin_below_absolute_floor() -> None:
    # es@0.672 (< the 0.75 lock floor) but a clear margin over the runner-up → locks es on turn 1.
    # Under the absolute-only rule this Spanish opener ran the whole conversation in English (~35%
    # of es first-turns).
    session = _run(
        "hola, necesito cancelar mi pedido por favor", None, _StubDetector("es", 0.672, margin=0.46)
    )
    assert session.active_lang == "es"
