"""US1 (002) — reply-language verification node, in isolation.

The deterministic check passes an in-language reply untouched; a wrong-language reply is corrected
by exactly one re-ask; a persistent mismatch or a degraded correction fails safe to an in-language
template + needs_review; a too-short reply is skipped.
"""

from __future__ import annotations

from tests.support.mock_llm import MockCall, MockLLMClient
from zapp_assist.config import load_config
from zapp_assist.graph.deps import Deps
from zapp_assist.graph.nodes._util import LANG_MISMATCH_TEMPLATES
from zapp_assist.graph.nodes.verify_reply_language import verify_reply_language
from zapp_assist.graph.state import TurnState
from zapp_assist.guardrails.baseline import default_registry
from zapp_assist.lang.detector import LanguageResult, LinguaDetector
from zapp_assist.memory.session_store import Session
from zapp_assist.obs.trace import Trace
from zapp_assist.tools.registry import ToolRegistry

ES = "Puedes reprogramar tu entrega hasta dos horas antes de la ventana estimada."
EN = "You can reschedule your delivery up to two hours before the estimated window."


def _rewriter(rewrite: str | None) -> MockLLMClient:
    """A mock whose single correction re-ask returns `rewrite` (or degrades when None)."""

    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is not None and call.schema.__name__ == "RewrittenReply" and rewrite:
            return call.schema(reply=rewrite)
        return None

    return MockLLMClient(responder=responder)


def _deps(llm: MockLLMClient) -> Deps:
    cfg = load_config()
    return Deps(
        config=cfg,
        llm=llm,
        detector=LinguaDetector(cfg.languages.supported, cfg.languages.fallback),
        guardrails=default_registry(),
        tools=ToolRegistry(),
    )


def _state(active: str, reply: str) -> TurnState:
    state = TurnState(
        turn_id="t",
        session=Session(session_id="s"),
        user_text="",
        trace=Trace(turn_id="t", session_id="s"),
    )
    state.language = LanguageResult(detected_lang=active, active_lang=active, lang_confidence=0.9)
    state.draft_reply = reply
    return state


def test_reply_in_active_language_passes_without_correction() -> None:
    out = verify_reply_language(_state("es", ES), _deps(_rewriter(None)))
    assert out.reply_match is True
    assert out.reply_corrected is False
    assert out.draft_reply == ES
    assert out.needs_review_override is False


def test_wrong_language_is_corrected_once() -> None:
    out = verify_reply_language(_state("es", EN), _deps(_rewriter(ES)))
    assert out.reply_corrected is True
    assert out.reply_match is True
    assert out.draft_reply == ES  # corrected to Spanish


def test_persistent_mismatch_fails_safe() -> None:
    out = verify_reply_language(_state("es", EN), _deps(_rewriter(EN)))  # correction still English
    assert out.reply_match is False
    assert out.needs_review_override is True
    assert out.draft_reply == LANG_MISMATCH_TEMPLATES["es"]


def test_degraded_correction_fails_safe() -> None:
    out = verify_reply_language(_state("es", EN), _deps(_rewriter(None)))  # correction degrades
    assert out.reply_match is False
    assert out.needs_review_override is True
    assert out.draft_reply == LANG_MISMATCH_TEMPLATES["es"]


def test_short_reply_is_skipped() -> None:
    out = verify_reply_language(_state("es", "OK"), _deps(_rewriter(None)))
    assert out.reply_match is True  # too short to verify → treated as in-language
    assert out.reply_corrected is False
    assert out.draft_reply == "OK"
