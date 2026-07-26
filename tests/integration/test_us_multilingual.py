"""002 multilingual — end-to-end integration (US1 first; US2/US3 added in later increments).

US1: a reply that is actually in the user's language. A wrong-language reply is corrected before the
user sees it; a persistent mismatch is replaced by a safe in-language message + needs_review — the
mismatched text is never shipped (SC-002).
"""

from __future__ import annotations

import pytest

from tests.support.mock_llm import MockCall, MockLLMClient
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.graph.nodes._util import LANG_MISMATCH_TEMPLATES
from zapp_assist.lang.detector import LinguaDetector

EN_Q = "How late can I reschedule a delivery?"
ES_Q = "¿hasta cuándo puedo reprogramar mi entrega?"
ES_REPLY = "Puedes reprogramar tu entrega hasta dos horas antes de la ventana estimada."
EN_REPLY = "You can reschedule your delivery up to two hours before the estimated window."

_DET = LinguaDetector(["es", "en", "pt"], "en")


def _lang_of(text: str) -> str:
    return _DET.language_of(text)[0]


def _agent(llm: MockLLMClient) -> Agent:
    return Agent.create(config=load_config(), llm=llm)


def _mm_llm(
    *,
    lang: str,
    grounded_reply: str,
    citations: list[str] | None = None,
    rewrite: str | None = None,
) -> MockLLMClient:
    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang=lang, confidence=0.97)
        if name == "IntentSignal":
            return call.schema(intent="support", confidence=0.95)
        if name == "GroundedAnswer":
            return call.schema(reply=grounded_reply, citations=citations or [], grounded=True)
        if name == "RewrittenReply":
            return call.schema(reply=rewrite) if rewrite else None
        return None

    return MockLLMClient(responder=responder)


def test_wrong_language_reply_is_corrected_end_to_end() -> None:
    # Active language is English, but the grounded answer comes back in Spanish → corrected to EN.
    llm = _mm_llm(
        lang="en", grounded_reply=ES_REPLY, citations=["delivery_reschedule_en"], rewrite=EN_REPLY
    )
    result = _agent(llm).run_turn("ml-correct", EN_Q)

    assert result.active_lang == "en"
    assert result.reply == EN_REPLY  # the Spanish draft was corrected
    assert _lang_of(result.reply) == "en"  # the user never sees a Spanish reply
    assert result.needs_review is False


def test_persistent_wrong_language_is_flagged_end_to_end() -> None:
    # The one correction still comes back in Spanish → safe in-language message + needs_review.
    llm = _mm_llm(
        lang="en", grounded_reply=ES_REPLY, citations=["delivery_reschedule_en"], rewrite=ES_REPLY
    )
    result = _agent(llm).run_turn("ml-flag", EN_Q)

    assert result.active_lang == "en"
    assert result.needs_review is True
    assert result.reply == LANG_MISMATCH_TEMPLATES["en"]
    assert _lang_of(result.reply) == "en"  # never the mismatched Spanish text


@pytest.mark.parametrize(
    "lang,question,reply,doc",
    [
        ("es", ES_Q, ES_REPLY, "delivery_reschedule_es"),
        ("en", EN_Q, EN_REPLY, "delivery_reschedule_en"),
    ],
)
def test_correct_in_language_reply_passes_verification(
    lang: str, question: str, reply: str, doc: str
) -> None:
    # A correct in-language grounded reply is unchanged and not flagged (verification is invisible).
    llm = _mm_llm(lang=lang, grounded_reply=reply, citations=[doc])  # rewrite never needed
    result = _agent(llm).run_turn(f"ml-ok-{lang}", question)

    assert result.active_lang == lang
    assert result.reply == reply
    assert _lang_of(result.reply) == lang
    assert result.needs_review is False
