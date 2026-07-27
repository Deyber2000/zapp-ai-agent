"""Node-level: detect_language's word-count switch gate (002 US2).

Closes the coverage gap that hid the miscalibrated gate — `test_switch_policy` exercises
`apply_switch_policy` directly (it takes `substantial: bool`), so the text→bool computation in the
node was never tested. A single-word borrowed token must NOT accumulate a switch; a genuine
multi-word turn must. A stub detector keeps this deterministic (no embedding, no lingua variance).
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
    """Fixed (lang, confidence); never 'foreign' (a supported language). Deterministic."""

    def __init__(self, lang: str, confidence: float) -> None:
        self._lang, self._conf = lang, confidence

    def detect(self, text: str) -> LanguageResult:
        return LanguageResult(
            detected_lang=self._lang, active_lang=self._lang, lang_confidence=self._conf
        )

    def language_of(self, text: str) -> tuple[str, float]:
        return self._lang, self._conf

    def is_foreign(self, text: str, min_confidence: float = 0.75) -> None:
        return None


def _pending_after(text: str, active_lang: str) -> int:
    # detect_language uses only config / detector / llm; guardrails/tools/rag are unused here.
    deps = Deps(
        config=load_config(),
        llm=MockLLMClient(),
        detector=_StubDetector("en", 0.9),
        guardrails=None,  # not touched by this node
        tools=None,  # not touched by this node
    )
    session = Session(session_id="t", active_lang=active_lang)
    state = TurnState(
        turn_id="t-0", session=session, user_text=text, trace=Trace(turn_id="t-0", session_id="t")
    )
    detect_language(state, deps)
    return state.session.pending_switch_count


def test_single_word_borrowed_token_does_not_accumulate_switch() -> None:
    # "thanks": confidently English in an es session, but ONE word → not a switch signal.
    assert _pending_after("thanks", "es") == 0


def test_multi_word_confident_turn_accumulates_switch() -> None:
    # "i need help": confidently English, three words → starts the sustained-switch accumulator.
    # (11 chars — the old char >= 12 floor wrongly blocked this; the word floor allows it.)
    assert _pending_after("i need help", "es") == 1
