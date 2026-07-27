"""US1 (002) — reply-language verification node, in isolation.

The check runs only on model-generated free text (`reply_from_model`): an in-language reply passes
untouched; a wrong-language reply is corrected by exactly one re-ask; a persistent mismatch or a
degraded correction fails safe to an in-language template + needs_review; a too-short reply is
skipped. Authored templates are trusted (correct-by-construction) and skip the check entirely.
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


def _state(active: str, reply: str, from_model: bool = False) -> TurnState:
    state = TurnState(
        turn_id="t",
        session=Session(session_id="s"),
        user_text="",
        trace=Trace(turn_id="t", session_id="s"),
    )
    state.language = LanguageResult(detected_lang=active, active_lang=active, lang_confidence=0.9)
    state.draft_reply = reply
    state.reply_from_model = from_model
    return state


def test_reply_in_active_language_passes_without_correction() -> None:
    out = verify_reply_language(_state("es", ES, from_model=True), _deps(_rewriter(None)))
    assert out.reply_match is True
    assert out.reply_corrected is False
    assert out.draft_reply == ES
    assert out.needs_review_override is False


def test_wrong_language_is_corrected_once() -> None:
    out = verify_reply_language(_state("es", EN, from_model=True), _deps(_rewriter(ES)))
    assert out.reply_corrected is True
    assert out.reply_match is True
    assert out.draft_reply == ES  # corrected to Spanish


def test_persistent_mismatch_fails_safe() -> None:
    # correction still English → fail safe
    out = verify_reply_language(_state("es", EN, from_model=True), _deps(_rewriter(EN)))
    assert out.reply_match is False
    assert out.needs_review_override is True
    assert out.draft_reply == LANG_MISMATCH_TEMPLATES["es"]


def test_degraded_correction_fails_safe() -> None:
    # correction degrades → fail safe
    out = verify_reply_language(_state("es", EN, from_model=True), _deps(_rewriter(None)))
    assert out.reply_match is False
    assert out.needs_review_override is True
    assert out.draft_reply == LANG_MISMATCH_TEMPLATES["es"]


def test_short_reply_is_skipped() -> None:
    out = verify_reply_language(_state("es", "OK", from_model=True), _deps(_rewriter(None)))
    assert out.reply_match is True  # too short to verify → treated as in-language
    assert out.reply_corrected is False
    assert out.draft_reply == "OK"


def test_authored_template_is_trusted_and_never_overwritten() -> None:
    # A short Spanish action-done template lingua mislabels as Portuguese. Because it is an authored
    # template (not model free text), it must be trusted verbatim and never rewritten to a review
    # note — otherwise a completed action reports failure after the backend already committed.
    done_es = "Listo. Completé: cancelar el pedido A1001."
    detector = _deps(_rewriter(None)).detector
    assert detector.language_of(done_es)[0] == "pt"  # the misdetection that used to trip the check

    out = verify_reply_language(_state("es", done_es, from_model=False), _deps(_rewriter(None)))
    assert out.reply_match is True
    assert out.reply_corrected is False
    assert out.needs_review_override is False
    assert out.draft_reply == done_es  # the success confirmation survives untouched
