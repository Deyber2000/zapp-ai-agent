"""US5 — graceful degradation under failure or low confidence (SC-006, FR-017/018).

Injected faults (timeout / malformed model output / tool error) and a low-confidence turn must all
still yield a schema-valid contract with a safe reply and `needs_review=true` — never a crash/hang.
Faults are injected via the `ZAPP_FAULT` env flag the mock LLM honors on every call.
"""

from __future__ import annotations

import pytest

from tests.support.mock_llm import MockLLMClient, scripted_llm
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.contracts import TurnResult

_QUESTION = "How late can I reschedule a delivery?"


def _agent(llm: MockLLMClient | None = None) -> Agent:
    return Agent.create(config=load_config(), llm=llm or scripted_llm(lang="en", intent="support"))


@pytest.mark.parametrize("fault", ["timeout", "malformed", "tool_error"])
def test_injected_fault_yields_valid_flagged_contract(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    monkeypatch.setenv("ZAPP_FAULT", fault)

    result = _agent().run_turn("s-fault", _QUESTION)

    # Schema-valid by construction, safe non-empty reply, flagged for review, no crash/hang.
    assert isinstance(result, TurnResult)
    assert result.reply.strip()
    assert result.needs_review is True
    assert result.active_lang == "en"
    assert result.guardrails.input == [] or isinstance(result.guardrails.input, list)


def test_every_fault_still_populates_all_contract_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZAPP_FAULT", "timeout")
    dumped = _agent().run_turn("s-fields", _QUESTION).model_dump()
    for field in (
        "reply",
        "detected_lang",
        "active_lang",
        "lang_confidence",
        "final_normalized_text",
        "confidence_score",
        "needs_review",
        "guardrails",
    ):
        assert field in dumped
    assert dumped["needs_review"] is True


def test_confidence_below_configured_threshold_flags_review() -> None:
    # Config-driven threshold (T043): raise it so a normally-clean turn is flagged for review.
    base = load_config()
    strict = base.model_copy(
        update={"thresholds": base.thresholds.model_copy(update={"review_confidence": 0.99})}
    )
    reply = "You can reschedule a delivery up to 2 hours before the estimated window."
    llm = scripted_llm(
        lang="en", intent="support", reply=reply, citations=["delivery_reschedule_en"]
    )

    result = Agent.create(config=strict, llm=llm).run_turn("s-lowconf", _QUESTION)

    assert result.needs_review is True
    assert result.confidence_score < 0.99


def test_low_confidence_reply_avoids_asserting_uncertain_facts() -> None:
    # No grounding for this question → the agent hedges (declines) rather than asserting a fact.
    llm = scripted_llm(lang="en", intent="support")
    result = _agent(llm).run_turn("s-noground", "Can I pay with cryptocurrency?")

    assert result.needs_review is True
    assert "can't confirm" in result.reply.lower()
    assert "cryptocurrency" not in result.reply.lower()
