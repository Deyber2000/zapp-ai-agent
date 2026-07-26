"""US3 — state-changing actions with human-in-the-loop confirmation (SC-005).

The agent restates the action and asks for confirmation; NO backend change happens until an
explicit "yes". A confirmed action executes exactly once; a decline or an ambiguous answer never
mutates state. Read-only lookups answer at once; unknown orders are refused honestly (not faked).
"""

from __future__ import annotations

from tests.support.mock_llm import MockCall, MockLLMClient
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.tools.mock_backend import MockBackend, register_backend_tools
from zapp_assist.tools.normalize import register_normalize_tools
from zapp_assist.tools.registry import ToolRegistry


def _action_llm(
    *,
    action: str = "cancel_order",
    order_id: str | None = "A1001",
    new_time: str | None = None,
    lang: str = "en",
) -> MockLLMClient:
    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang=lang, confidence=0.97)
        if name == "IntentSignal":
            return call.schema(intent="action", confidence=0.95)
        if name == "ActionRequest":
            return call.schema(action=action, order_id=order_id, new_time=new_time)
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
