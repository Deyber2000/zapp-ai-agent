"""US1 — grounded support answer (SC-002, SC-007).

(a) In-domain question in ES/EN/PT → grounded, same-language reply, valid contract,
    needs_review=false.
(b) No-grounding question → decline (does not invent) + needs_review=true.
"""

from __future__ import annotations

import pytest

from tests.support.mock_llm import MockLLMClient, scripted_llm
from zapp_assist.agent import Agent
from zapp_assist.config import load_config

# Per-language in-domain question + the grounded reply we script the responder to emit.
IN_DOMAIN = {
    "es": (
        "¿hasta cuándo puedo reprogramar mi entrega?",
        "Puedes reprogramar tu entrega hasta 2 horas antes de la ventana estimada.",
        "delivery_reschedule_es",
    ),
    "en": (
        "How late can I reschedule a delivery?",
        "You can reschedule a delivery up to 2 hours before the estimated window.",
        "delivery_reschedule_en",
    ),
    "pt": (
        "Até quando posso reagendar minha entrega?",
        "Você pode reagendar sua entrega até 2 horas antes da janela estimada.",
        "delivery_reschedule_pt",
    ),
}


def _agent(llm: MockLLMClient) -> Agent:
    return Agent.create(config=load_config(), llm=llm)


@pytest.mark.parametrize("lang", ["es", "en", "pt"])
def test_in_domain_question_is_grounded_and_same_language(lang: str) -> None:
    question, reply, doc_id = IN_DOMAIN[lang]
    llm = scripted_llm(lang=lang, intent="support", reply=reply, citations=[doc_id])
    result = _agent(llm).run_turn(f"us1-{lang}", question)

    assert result.active_lang == lang
    assert result.detected_lang == lang
    assert result.reply == reply  # grounded, same-language reply
    assert result.needs_review is False
    assert result.confidence_score >= 0.6
    assert result.guardrails.input == []
    assert result.guardrails.output == []


def test_no_grounding_declines_and_flags_review() -> None:
    # Genuinely absent from the KB (no loyalty/rewards doc) → retrieval returns nothing → the model
    # declines rather than inventing. (Payments IS covered now, so crypto would be answered.)
    llm = scripted_llm(lang="en", intent="support", grounded=False)
    result = _agent(llm).run_turn("us1-nogrounding", "Do you offer a loyalty rewards program?")

    assert result.active_lang == "en"
    assert result.needs_review is True
    # The reply must be a decline, not an invented policy answer.
    assert "loyalty" not in result.reply.lower()
    assert "can't confirm" in result.reply.lower()


def test_grounded_answer_populates_every_contract_field() -> None:
    question, reply, doc_id = IN_DOMAIN["en"]
    llm = scripted_llm(lang="en", intent="support", reply=reply, citations=[doc_id])
    result = _agent(llm).run_turn("us1-fields", question)

    dumped = result.model_dump()
    assert dumped["final_normalized_text"] == question  # no normalization applies → raw text
    assert dumped["detected_country"] is None
    assert dumped["needs_review"] is False
