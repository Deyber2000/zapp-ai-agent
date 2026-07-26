"""002 multilingual — end-to-end integration.

US1: a reply that is actually in the user's language (corrected or safe-flagged, never shipped bad).
US2: coherence across turns — language persists across short turns and switches only on sustained
confident intent, never on a one-off phrase.
"""

from __future__ import annotations

import pytest

from tests.support.mock_llm import MockCall, MockLLMClient, scripted_llm
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


# ---- US2: coherence & sustained-switch policy -------------------------------------------------

# Real sentences whose deterministic detection + confidence are verified to clear the thresholds.
PT1 = "Olá, preciso reagendar a minha entrega para amanhã de manhã, por favor."
PT2 = "Obrigado pela ajuda com o meu pedido de hoje."
PT3 = "Preciso de ajuda com a minha entrega de amanhã de manhã."
EN1 = "I would like to continue this conversation in English now please."
EN2 = "Can you help me reschedule my delivery for tomorrow afternoon?"
EN3 = "Thanks a lot for your help today, I really appreciate it."


def _last_user(call: MockCall) -> str:
    for msg in reversed(call.messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _coherence_llm() -> MockLLMClient:
    """LangSignal mirrors the real deterministic detection; every turn is a clarify (reply is a
    per-language template, so reply verification is transparent and no grounding is needed)."""

    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            lang, conf = _DET.language_of(_last_user(call))
            return call.schema(lang=lang, confidence=conf)
        if name == "IntentSignal":
            return call.schema(intent="clarify", confidence=0.9)
        return None

    return MockLLMClient(responder=responder)


def test_language_persists_across_short_and_matching_turns() -> None:
    agent = _agent(_coherence_llm())
    r1 = agent.run_turn("coh", PT1)  # locks pt
    r2 = agent.run_turn("coh", "ok")  # short → keeps pt (SC-003)
    r3 = agent.run_turn("coh", PT2)  # pt again → keeps pt
    assert [r1.active_lang, r2.active_lang, r3.active_lang] == ["pt", "pt", "pt"]
    # replies stay Portuguese too — not just the active_lang field
    assert _lang_of(r1.reply) == "pt" and _lang_of(r3.reply) == "pt"


def test_sustained_switch_updates_active_language_and_reply() -> None:
    agent = _agent(_coherence_llm())
    r1 = agent.run_turn("sw", PT1)  # locked pt
    r2 = agent.run_turn("sw", EN1)  # 1st EN → still pt (accumulating)
    r3 = agent.run_turn("sw", EN2)  # 2nd EN → sustained switch (SC-004)
    assert [r1.active_lang, r2.active_lang, r3.active_lang] == ["pt", "pt", "en"]
    # the REPLY follows the policy: Portuguese before the switch, English after
    assert _lang_of(r2.reply) == "pt"
    assert _lang_of(r3.reply) == "en"


def test_one_off_foreign_phrase_does_not_switch() -> None:
    agent = _agent(_coherence_llm())
    r1 = agent.run_turn("one", PT1)  # locked pt
    r2 = agent.run_turn("one", EN3)  # single EN phrase → still pt
    r3 = agent.run_turn("one", PT3)  # back to pt → never switched (SC-004)
    assert [r1.active_lang, r2.active_lang, r3.active_lang] == ["pt", "pt", "pt"]
    assert _lang_of(r3.reply) == "pt"  # reply stays Portuguese throughout


# ---- US3: graceful degradation on unsupported / low-confidence --------------------------------

FR = "Bonjour, je voudrais reprogrammer ma livraison pour demain matin s'il vous plaît."
DE = "Ich möchte meine Lieferung auf morgen verschieben, bitte."


@pytest.mark.parametrize("iso,text", [("fr", FR), ("de", DE)])
def test_unsupported_language_degrades_to_fallback(iso: str, text: str) -> None:
    result = _agent(scripted_llm(lang="en", intent="support")).run_turn(f"oos-{iso}", text)

    assert result.active_lang == "en"  # fallback — never the unsupported language (SC-005)
    assert result.detected_lang == iso  # honestly reports the detected (unsupported) language
    assert result.needs_review is True
    assert _lang_of(result.reply) == "en"  # reply is in a supported language, not fr/de


def test_low_confidence_input_uses_fallback_safely() -> None:
    # Undetectable input (no real language signal) → fallback, safe reply, no asserted language.
    result = _agent(scripted_llm(lang="en", intent="clarify")).run_turn("lowconf", "?!?")

    assert result.active_lang == "en"
    assert result.reply
    assert _lang_of(result.reply) == "en"
