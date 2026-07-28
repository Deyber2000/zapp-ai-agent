"""US3 — state-changing actions with human-in-the-loop confirmation (SC-005).

The agent restates the action and asks for confirmation; NO backend change happens until an
explicit "yes". A confirmed action executes exactly once; a decline or an ambiguous answer never
mutates state. Read-only lookups answer at once; unknown orders are refused honestly (not faked).
"""

from __future__ import annotations

from tests.support.mock_llm import MockCall, MockLLMClient, agent_step
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.graph.nodes._action import ACTION_DONE
from zapp_assist.graph.nodes._util import LANG_MISMATCH_TEMPLATES
from zapp_assist.tools.mock_backend import MockBackend, register_backend_tools
from zapp_assist.tools.normalize import register_normalize_tools
from zapp_assist.tools.registry import ToolRegistry


def _action_llm(
    *,
    action: str = "cancel_order",
    order_id: str | None = "A1001",
    new_time: str | None = None,
    field: str | None = None,
    value: str | None = None,
    lang: str = "en",
) -> MockLLMClient:
    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang=lang, confidence=0.97)
        if name == "AgentStep":
            return agent_step(
                call.schema, call, intent="action", action=action, order_id=order_id,
                new_time=new_time, field=field, value=value,
            )
        return None

    return MockLLMClient(responder=responder)


def _agent(llm: MockLLMClient) -> tuple[Agent, MockBackend]:
    backend = MockBackend()
    tools = ToolRegistry()
    register_normalize_tools(tools)
    register_backend_tools(tools, backend)
    return Agent.create(config=load_config(), llm=llm, tools=tools), backend


def test_action_asks_confirmation_then_executes_exactly_once() -> None:
    agent, backend = _agent(_action_llm(action="cancel_order", order_id="A1001"))

    # AS1: restates + asks confirmation; NO backend change yet.
    r1 = agent.run_turn("s-cancel", "please cancel my order A1001")
    assert "confirm" in r1.reply.lower()
    assert backend.state_changes == 0
    assert backend.lookup("A1001").status == "scheduled"

    # AS2: explicit "yes" → executes exactly once.
    r2 = agent.run_turn("s-cancel", "yes")
    assert backend.state_changes == 1
    assert backend.lookup("A1001").status == "cancelled"
    assert r2.needs_review is False

    # Exactly-once: the pending action was cleared, and the backend op is idempotent anyway.
    backend.cancel("A1001")
    assert backend.state_changes == 1


def test_spanish_cancel_executes_and_reports_success_not_a_language_failure() -> None:
    # Defect B (mutate-then-report-failure): the short ES success line "Listo. Completé: cancelar
    # el pedido A1001." is mislabeled Portuguese by lingua; offline, the reply-language correction
    # can't repair it, so the verifier used to overwrite it with a language-failure note + review —
    # AFTER the backend had already committed. The action must report the success it actually did.
    # (Authored templates are now trusted and skip the reply-language check.)
    agent, backend = _agent(_action_llm(action="cancel_order", order_id="A1001", lang="es"))

    r1 = agent.run_turn("s-es-cancel", "quiero cancelar mi pedido A1001")
    assert backend.state_changes == 0  # proposal only, no mutation yet
    assert r1.active_lang == "es"

    r2 = agent.run_turn("s-es-cancel", "sí, confirmo")
    assert backend.state_changes == 1  # executed exactly once
    assert backend.lookup("A1001").status == "cancelled"
    assert r2.active_lang == "es"
    assert r2.reply == ACTION_DONE["es"].format(summary="cancelar el pedido A1001")
    assert r2.reply != LANG_MISMATCH_TEMPLATES["es"]  # NOT a language failure after a real mutation
    assert r2.needs_review is False


def test_reschedule_confirmed_updates_the_window() -> None:
    agent, backend = _agent(
        _action_llm(
            action="reschedule_delivery", order_id="A1002", new_time="Mon 10:00–12:00"
        )
    )
    agent.run_turn("s-resched", "reschedule order A1002 to monday morning")
    assert backend.state_changes == 0  # still just a proposal

    agent.run_turn("s-resched", "yes please")
    assert backend.state_changes == 1
    assert backend.lookup("A1002").status == "rescheduled"
    assert backend.lookup("A1002").window == "Mon 10:00–12:00"


def test_decline_abandons_without_changing_state() -> None:
    agent, backend = _agent(_action_llm(action="cancel_order", order_id="A1001"))
    agent.run_turn("s-decline", "cancel order A1001")
    agent.run_turn("s-decline", "no")
    assert backend.state_changes == 0
    assert backend.lookup("A1001").status == "scheduled"


def test_ambiguous_answer_keeps_action_pending_and_never_executes() -> None:
    agent, backend = _agent(_action_llm(action="cancel_order", order_id="A1001"))
    agent.run_turn("s-amb", "cancel order A1001")

    ambiguous = agent.run_turn("s-amb", "maybe")  # unclear → re-ask, no change
    assert backend.state_changes == 0
    assert backend.lookup("A1001").status == "scheduled"

    # Still pending → a later explicit "yes" executes it once.
    agent.run_turn("s-amb", "yes")
    assert backend.state_changes == 1
    assert backend.lookup("A1001").status == "cancelled"
    assert ambiguous.reply  # a valid re-ask was produced


def test_read_only_lookup_answers_without_confirmation() -> None:
    agent, backend = _agent(_action_llm(action="lookup_order", order_id="A1001"))
    result = agent.run_turn("s-lookup", "what's the status of order A1001?")
    assert backend.state_changes == 0
    assert "A1001" in result.reply
    assert "scheduled" in result.reply.lower()


def test_unknown_order_is_refused_not_faked() -> None:
    agent, backend = _agent(_action_llm(action="cancel_order", order_id="Z9999"))
    result = agent.run_turn("s-unknown", "cancel order Z9999")
    assert backend.state_changes == 0
    assert result.needs_review is True
    assert "Z9999" in result.reply


# ---- domain-parity actions (payments / returns / tracking / account / membership) ----------------


def test_refund_confirmed_marks_order_refunded() -> None:
    agent, backend = _agent(_action_llm(action="process_refund", order_id="A1001"))
    agent.run_turn("s-refund", "I want a refund for order A1001")
    assert backend.state_changes == 0  # proposal only
    agent.run_turn("s-refund", "yes")
    assert backend.state_changes == 1
    assert backend.lookup("A1001").status == "refunded"


def test_start_return_confirmed() -> None:
    agent, backend = _agent(_action_llm(action="start_return", order_id="A1002"))
    agent.run_turn("s-return", "start a return for order A1002")
    assert backend.state_changes == 0
    agent.run_turn("s-return", "yes please")
    assert backend.state_changes == 1
    assert backend.lookup("A1002").status == "return_started"


def test_track_order_reads_without_confirmation() -> None:
    agent, backend = _agent(_action_llm(action="track_order", order_id="A1001"))
    result = agent.run_turn("s-track", "where is my order A1001?")
    assert backend.state_changes == 0
    assert "A1001" in result.reply


def test_cancel_membership_confirmed_needs_no_order() -> None:
    agent, backend = _agent(_action_llm(action="cancel_membership", order_id=None))
    r1 = agent.run_turn("s-mem", "cancel my Zapp+ membership")
    assert "confirm" in r1.reply.lower()
    assert backend.state_changes == 0 and backend.account.membership_active is True
    agent.run_turn("s-mem", "yes")
    assert backend.state_changes == 1
    assert backend.account.membership_active is False


def test_update_contact_confirmed_updates_account() -> None:
    agent, backend = _agent(
        _action_llm(action="update_contact", order_id=None, field="email", value="new@zapp.test")
    )
    agent.run_turn("s-contact", "change my email to new@zapp.test")
    assert backend.state_changes == 0
    agent.run_turn("s-contact", "yes")
    assert backend.state_changes == 1
    assert backend.account.email == "new@zapp.test"


def test_update_contact_missing_value_asks_and_does_not_execute() -> None:
    agent, backend = _agent(_action_llm(action="update_contact", order_id=None, field=None))
    result = agent.run_turn("s-contact2", "I want to update my contact details")
    assert backend.state_changes == 0
    assert backend.account.membership_active is True  # nothing mutated
    assert result.reply  # a clarifying ask was produced
    assert backend.account.email == "user@example.com"
