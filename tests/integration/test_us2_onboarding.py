"""US2 — onboarding intake with signal-fusion normalization (SC-003, SC-004).

(a) Messy phone + country hint → `final_normalized_text` in E.164 + correct `detected_country`.
(b) LLM-vs-deterministic divergence → deterministic value wins, confidence drops, `needs_review`.
(c) Partial data → asks only the missing field, in the active language, without fabricating.
(d) Slots fill across turns → a value given earlier is not re-requested.
"""

from __future__ import annotations

from tests.support.mock_llm import MockCall, MockLLMClient
from zapp_assist.agent import Agent
from zapp_assist.config import load_config

# Deterministic normalization target for a messy Mexican number (national digits + region hint).
MESSY_PHONE = "55 1234 5678"
EXPECTED_E164 = "+525512345678"
EXPECTED_COUNTRY = "MX"


def _last_user(call: MockCall) -> str:
    for msg in reversed(call.messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _onboarding_llm(
    *,
    lang: str,
    full_name: str | None = None,
    phone_raw: str | None = None,
    region_hint: str | None = None,
    phone_normalized: str | None = None,
) -> MockLLMClient:
    """A mock scripting language, onboarding intent, and a fixed onboarding extraction."""

    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang=lang, confidence=0.97)
        if name == "IntentSignal":
            return call.schema(intent="onboarding", confidence=0.95)
        if name == "OnboardingExtraction":
            return call.schema(
                full_name=full_name,
                phone_raw=phone_raw,
                region_hint=region_hint,
                phone_normalized=phone_normalized,
            )
        return None

    return MockLLMClient(responder=responder)


def _agent(llm: MockLLMClient) -> Agent:
    return Agent.create(config=load_config(), llm=llm)


def test_full_onboarding_normalizes_to_e164_and_country() -> None:
    # SC-003: messy phone + "MX" hint → canonical E.164 + detected country; LLM agrees → clean turn.
    llm = _onboarding_llm(
        lang="en",
        full_name="Ana Torres",
        phone_raw=MESSY_PHONE,
        region_hint=EXPECTED_COUNTRY,
        phone_normalized=EXPECTED_E164,
    )
    result = _agent(llm).run_turn(
        "us2-full", "Hi, I'm Ana Torres and my phone is 55 1234 5678."
    )

    assert result.active_lang == "en"
    assert result.final_normalized_text == EXPECTED_E164
    assert result.detected_country == EXPECTED_COUNTRY
    assert result.needs_review is False
    assert result.confidence_score >= 0.6
    assert EXPECTED_E164 in result.reply  # confirmation echoes the normalized number


def test_llm_deterministic_divergence_lowers_confidence_and_flags_review() -> None:
    # SC-004: same deterministic input, but the LLM's own normalization disagrees.
    text = "Hi, I'm Ana Torres and my phone is 55 1234 5678."

    agree = _agent(
        _onboarding_llm(
            lang="en",
            full_name="Ana Torres",
            phone_raw=MESSY_PHONE,
            region_hint=EXPECTED_COUNTRY,
            phone_normalized=EXPECTED_E164,
        )
    ).run_turn("us2-agree", text)

    diverge = _agent(
        _onboarding_llm(
            lang="en",
            full_name="Ana Torres",
            phone_raw=MESSY_PHONE,
            region_hint=EXPECTED_COUNTRY,
            phone_normalized="+525599999999",  # LLM disagrees with the deterministic value
        )
    ).run_turn("us2-diverge", text)

    # Deterministic value still wins for the correctness-critical fields (Principle X).
    assert diverge.final_normalized_text == EXPECTED_E164
    assert diverge.detected_country == EXPECTED_COUNTRY
    # Divergence flags the turn and lowers confidence relative to the agreeing case.
    assert diverge.needs_review is True
    assert agree.needs_review is False
    assert diverge.confidence_score < agree.confidence_score


def test_partial_data_asks_only_the_missing_field_in_active_language() -> None:
    # Name only, in Spanish → ask for the phone in Spanish; never invent or re-ask the name.
    llm = _onboarding_llm(lang="es", full_name="Ana Torres")
    result = _agent(llm).run_turn(
        "us2-partial", "Hola, quiero registrarme. Mi nombre es Ana Torres."
    )

    assert result.active_lang == "es"
    assert result.detected_country is None
    assert result.final_normalized_text == "Hola, quiero registrarme. Mi nombre es Ana Torres."
    reply = result.reply.lower()
    assert "teléfono" in reply or "número" in reply  # asks for the phone
    assert "nombre" not in reply  # does not re-ask for the already-collected name


def test_slots_fill_across_turns_without_re_requesting() -> None:
    # Turn 1 gives the name (no digits); turn 2 gives the phone (has digits). Same session persists.
    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang="en", confidence=0.97)
        if name == "IntentSignal":
            return call.schema(intent="onboarding", confidence=0.95)
        if name == "OnboardingExtraction":
            if any(ch.isdigit() for ch in _last_user(call)):
                return call.schema(
                    phone_raw=MESSY_PHONE,
                    region_hint=EXPECTED_COUNTRY,
                    phone_normalized=EXPECTED_E164,
                )
            return call.schema(full_name="Ana Torres")
        return None

    agent = _agent(MockLLMClient(responder=responder))

    turn1 = agent.run_turn("us2-multi", "Hi, I'd like to sign up. My name is Ana Torres.")
    assert "phone" in turn1.reply.lower()  # asks for the still-missing phone
    assert turn1.needs_review is False

    turn2 = agent.run_turn("us2-multi", "My number is 55 1234 5678")
    # Both slots now present → confirmation echoes the persisted name + normalized phone.
    assert "Ana Torres" in turn2.reply
    assert EXPECTED_E164 in turn2.reply
    assert turn2.final_normalized_text == EXPECTED_E164
    assert turn2.detected_country == EXPECTED_COUNTRY
    assert turn2.needs_review is False
