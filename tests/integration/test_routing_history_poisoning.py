"""Live defects: conversation history must never SUPPLY a state-changing action (Constitution X).

Two reproductions from live testing, both rooted in history-aware routing feeding prose history to
the LLM router/planner with a "carry the earlier action forward" instruction:

  1. after action-shaped turns, an interrogative ("can I close my account?") was classified `action`
     and armed a membership cancellation the user never requested;
  2. after a completed cancel, a contentless "yes go ahead" re-armed the cancel with the order id
     recovered from history.

Both are driven here by a *deliberately poisoned* router mock that always returns `action` — proving
the deterministic guard pulls each back to a safe intent so nothing is armed on disk.
"""

from __future__ import annotations

from typing import Any

from tests.support.mock_llm import MockCall, MockLLMClient
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.memory.session_store import InMemorySessionStore, Session, TurnRef
from zapp_assist.tools.mock_backend import MockBackend, register_backend_tools
from zapp_assist.tools.normalize import register_normalize_tools
from zapp_assist.tools.registry import ToolRegistry


def _poisoned_router(
    *, action: str = "cancel_membership", order_id: str | None = "A1001"
) -> MockLLMClient:
    """A router that always says `action` (the live failure), and a planner that would map the
    request onto a destructive op with an id recovered from history."""

    grounded = "Account closure is self-service in Settings, with a 14-day grace period."

    def responder(call: MockCall) -> Any:
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang="en", confidence=0.97)
        if name == "IntentSignal":
            return call.schema(intent="action", confidence=0.95)  # the poisoned verdict
        if name == "ActionRequest":
            return call.schema(action=action, order_id=order_id)
        if name == "GroundedAnswer":
            return call.schema(reply=grounded, citations=[], grounded=True)
        return None

    return MockLLMClient(responder=responder)


def _agent(llm: MockLLMClient, store: InMemorySessionStore) -> tuple[Agent, MockBackend]:
    backend = MockBackend()
    tools = ToolRegistry()
    register_normalize_tools(tools)
    register_backend_tools(tools, backend)
    agent = Agent.create(config=load_config(), llm=llm, tools=tools, store=store)
    return agent, backend


def test_interrogative_question_does_not_arm_a_membership_cancellation() -> None:
    store = InMemorySessionStore()
    agent, backend = _agent(_poisoned_router(action="cancel_membership", order_id=None), store)

    # Prior turns are action-shaped; the current turn is a QUESTION.
    store.save(
        Session(
            session_id="live-ml",
            history=[
                TurnRef(user_text="can I get a refund?", reply="Refunds take 5–10 days.",
                        intent="action"),
                TurnRef(user_text="and cancel my order?", reply="Confirm cancel?",
                        intent="action"),
            ],
        )
    )
    r = agent.run_turn("live-ml", "can I also close my account permanently?")

    assert backend.state_changes == 0  # nothing executed
    assert backend.account.membership_active is True  # membership untouched
    assert store.load("live-ml").pending_action is None  # and nothing armed on disk
    assert "confirm" not in r.reply.lower()  # answered the question, did not propose a cancel


def test_bare_yes_after_completion_does_not_rearm_the_cancel() -> None:
    store = InMemorySessionStore()
    agent, backend = _agent(_poisoned_router(action="cancel_order", order_id="A1001"), store)

    # A completed cancel sits in history; there is NO pending action; the user sends a bare "yes".
    store.save(
        Session(
            session_id="live-hitl",
            history=[
                TurnRef(user_text="cancel order A1001", reply="Confirm cancel A1001?",
                        intent="action"),
                TurnRef(
                    user_text="yes",
                    reply="Done. I've completed: cancel order A1001.",
                    intent="action",
                ),
            ],
        )
    )
    r = agent.run_turn("live-hitl", "yes go ahead")

    assert backend.state_changes == 0  # nothing re-armed, nothing executed
    assert store.load("live-hitl").pending_action is None
    assert "confirm" not in r.reply.lower()  # a clarify, not a fresh cancel proposal


def test_the_same_guard_still_lets_a_grounded_action_through() -> None:
    # Control: a real action stated in the current message (order id present) is unaffected.
    store = InMemorySessionStore()
    agent, backend = _agent(_poisoned_router(action="cancel_order", order_id="A1001"), store)
    r = agent.run_turn("live-ok", "please cancel order A1001")
    assert "confirm" in r.reply.lower()  # proposed + asked, as designed
    assert backend.state_changes == 0  # still just a proposal (HITL)
    assert store.load("live-ok").pending_action is not None  # armed, awaiting confirmation
