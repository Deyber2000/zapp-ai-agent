"""The tool-calling agent core, exercised as real multi-turn conversations.

The agent replaced the blind router + planner. Its correctness bet is architectural, not a pile of
validators: the ONLY path to a backend mutation is `action_execute`, reached only when a pending
action already awaits an explicit confirmation. So across a whole conversation, a question — or a
contentless "yes" with nothing pending — can never execute anything. These conversations pin that,
including the two live history-poisoning scenarios that motivated the rebuild.
"""

from __future__ import annotations

from typing import Any

from tests.support.mock_llm import MockCall, MockLLMClient, agent_step
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.memory.session_store import InMemorySessionStore
from zapp_assist.tools.mock_backend import MockBackend, register_backend_tools
from zapp_assist.tools.normalize import register_normalize_tools
from zapp_assist.tools.registry import ToolRegistry

_RESCHEDULE = "You can reschedule your delivery up to two hours before the window."
_ACCOUNT = "You can close your account in Settings; it is permanent after a 14-day grace period."


def _current(call: MockCall) -> str:
    for msg in call.messages:
        if msg.get("role") == "user":
            c = msg.get("content", "")
            return (c.split("Current message: ", 1)[1] if "Current message: " in c else c).lower()
    return ""


def _brain() -> MockLLMClient:
    """A small deterministic 'agent brain': maps each message to the tool a good agent would pick.

    It reasons on the CURRENT message only — exactly the property the live gpt-4o-mini run showed,
    so 'close my account?' is answered and a bare 'yes' with nothing pending is a clarify.
    """

    def responder(call: MockCall) -> Any:
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang="en", confidence=0.97)
        if name != "AgentStep":
            return None
        msg = _current(call)
        if "cancel" in msg and "a1001" in msg:
            return agent_step(
                call.schema, call, intent="action", action="cancel_order", order_id="A1001"
            )
        if "close my account" in msg:
            return agent_step(call.schema, call, intent="support", reply=_ACCOUNT)
        if "reschedule" in msg:
            return agent_step(call.schema, call, intent="support", reply=_RESCHEDULE)
        return agent_step(call.schema, call, intent="clarify")  # a bare ack → clarify

    return MockLLMClient(responder=responder)


def _agent() -> tuple[Agent, MockBackend, InMemorySessionStore]:
    backend = MockBackend()
    tools = ToolRegistry()
    register_normalize_tools(tools)
    register_backend_tools(tools, backend)
    store = InMemorySessionStore()
    agent = Agent.create(config=load_config(), llm=_brain(), tools=tools, store=store)
    return agent, backend, store


def test_support_then_action_then_confirm_conversation() -> None:
    agent, backend, store = _agent()
    sid = "convo"

    r1 = agent.run_turn(sid, "How late can I reschedule a delivery?")
    assert r1.reply == _RESCHEDULE
    assert backend.state_changes == 0 and store.load(sid).pending_action is None

    r2 = agent.run_turn(sid, "Actually, please cancel my order A1001")
    assert "confirm" in r2.reply.lower()
    assert backend.state_changes == 0  # proposed, not executed
    assert store.load(sid).pending_action is not None  # armed, awaiting the explicit yes

    r3 = agent.run_turn(sid, "yes, go ahead")  # routed straight to the deterministic gate
    assert backend.state_changes == 1  # executed exactly once
    assert backend.lookup("A1001").status == "cancelled"
    assert store.load(sid).pending_action is None and r3.needs_review is False


def test_history_never_arms_a_destructive_action_across_a_conversation() -> None:
    # The two live defects, as one conversation: after real action turns, a QUESTION about closing
    # the account is answered (not a membership cancel), and a bare 'yes' with nothing pending does
    # nothing. Nothing irreversible happens without an explicit confirmation of a pending action.
    agent, backend, store = _agent()
    sid = "poison"

    agent.run_turn(sid, "please cancel my order A1001")  # proposes
    agent.run_turn(sid, "yes")  # executes the cancel — one legitimate mutation
    assert backend.state_changes == 1

    r_q = agent.run_turn(sid, "Can I also close my account permanently?")  # a QUESTION
    assert "confirm" not in r_q.reply.lower()  # answered, not a membership-cancel proposal
    assert store.load(sid).pending_action is None
    assert backend.account.membership_active is True

    r_ack = agent.run_turn(sid, "yes go ahead")  # bare ack, nothing pending
    assert store.load(sid).pending_action is None
    assert backend.account.membership_active is True
    assert backend.state_changes == 1  # still exactly the one confirmed cancel — nothing re-armed
    assert r_ack.reply  # a valid contract is still produced
