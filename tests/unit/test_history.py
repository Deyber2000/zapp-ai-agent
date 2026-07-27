"""Multi-turn history: recorded on the session and fed into routing (001 FR-015; defect #3).

`session.history` was defined but never written or read, so routing classified every turn on its
bare text (a cancel → order-number → confirm thread collapsed). These cover both halves: history is
now recorded per turn, and the router's prompt carries the prior turns.
"""

from __future__ import annotations

from tests.support.mock_llm import MockCall, MockLLMClient
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.graph.nodes._util import recent_history
from zapp_assist.memory.session_store import InMemorySessionStore, Session, TurnRef


def test_recent_history_is_empty_without_turns() -> None:
    assert recent_history(Session(session_id="s")) == ""


def test_recent_history_formats_user_text_intent_and_reply() -> None:
    session = Session(
        session_id="s",
        history=[
            TurnRef(user_text="cancel my order", reply="What's your order #?", intent="action"),
            TurnRef(user_text="it's A1001", reply="Confirm cancel A1001?", intent="action"),
        ],
    )
    out = recent_history(session, limit=3)
    assert "cancel my order" in out and "[action]" in out and "A1001" in out


def _last_user(call: MockCall) -> str:
    for message in reversed(call.messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def test_history_is_recorded_and_fed_to_the_router() -> None:
    router_prompts: list[str] = []

    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang="en", confidence=0.97)
        if name == "IntentSignal":
            router_prompts.append(_last_user(call))  # capture what the router actually saw
            return call.schema(intent="support", confidence=0.95)
        if name == "GroundedAnswer":
            return call.schema(reply="You can reschedule up to 2 hours before.", grounded=True)
        return None

    store = InMemorySessionStore()
    agent = Agent.create(config=load_config(), llm=MockLLMClient(responder=responder), store=store)
    agent.run_turn("h", "how late can I reschedule?")
    agent.run_turn("h", "and what about tracking?")

    history = store.load("h").history
    assert len(history) == 2
    assert history[0].user_text == "how late can I reschedule?" and history[0].intent == "support"
    assert history[0].reply  # the assistant reply was recorded too

    # Turn 2's router prompt carried turn 1 (history-aware routing) plus the new message.
    assert "how late can I reschedule?" in router_prompts[1]
    assert "and what about tracking?" in router_prompts[1]
