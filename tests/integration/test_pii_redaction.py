"""Input PII redaction is APPLIED, not just recorded (003, FR-008; "Redaction vs refusal" edge).

The input `pii` rule fires on emails / card-like numbers and its action is `redact`. Previously the
decision was recorded and the turn continued, but the raw text still reached the contract's
`final_normalized_text` — personal data retained in the output. The masked text is now what the turn
retains. A deliberately normalized value (onboarding's E.164 phone) still wins, so onboarding is
unaffected.
"""

from __future__ import annotations

from tests.support.mock_llm import MockCall, MockLLMClient, scripted_llm
from zapp_assist.agent import Agent
from zapp_assist.config import load_config


def _agent(llm: MockLLMClient) -> Agent:
    return Agent.create(config=load_config(), llm=llm)


def test_input_pii_is_masked_in_final_normalized_text() -> None:
    email = "jane.doe@example.com"
    result = _agent(scripted_llm(lang="en", intent="support")).run_turn(
        "pii", f"my email is {email}, how late can I reschedule my delivery?"
    )
    # The decision was recorded AND applied: the raw email is gone, the masked marker is present.
    assert any(d.action == "redact" for d in result.guardrails.input)
    assert email not in result.final_normalized_text
    assert "[redacted-email]" in result.final_normalized_text


def test_card_like_number_is_masked_in_retained_input() -> None:
    result = _agent(scripted_llm(lang="en", intent="support")).run_turn(
        "pii-card", "please charge card 4111 1111 1111 1111 for my order"
    )
    assert "4111 1111 1111 1111" not in result.final_normalized_text
    assert "[redacted-number]" in result.final_normalized_text


def test_onboarding_phone_is_not_over_redacted() -> None:
    # The phone triggers the same input rule, but onboarding's deterministic E.164 normalization is
    # the intended retained value — it must win over the raw-text redaction path.
    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang="en", confidence=0.97)
        if name == "IntentSignal":
            return call.schema(intent="onboarding", confidence=0.95)
        if name == "OnboardingExtraction":
            return call.schema(
                full_name="Ana Ruiz",
                phone_raw="+52 55 1234 5678",
                region_hint="MX",
                phone_normalized="+525512345678",
            )
        return None

    result = _agent(MockLLMClient(responder=responder)).run_turn(
        "pii-onb", "I'm Ana Ruiz, my phone is +52 55 1234 5678"
    )
    assert result.final_normalized_text == "+525512345678"  # the normalized phone, not a redaction
    assert "[redacted" not in result.final_normalized_text
