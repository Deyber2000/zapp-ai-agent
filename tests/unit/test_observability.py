"""Unit test for observability (T046, Constitution XI, FR-022).

Every node that runs on a turn emits exactly one `Span`, and the turn's tokens/cost are recorded —
the signal source the `004` evaluation suite consumes. Verified by invoking the compiled graph
directly and inspecting the trace (the trace is internal to `run_turn`).
"""

from __future__ import annotations

from tests.support.mock_llm import scripted_llm
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.graph.build import build_graph
from zapp_assist.graph.state import TurnState
from zapp_assist.memory.session_store import Session
from zapp_assist.obs.trace import Trace

_EXPECTED_NODES = {
    "guardrail_in",
    "detect_language",
    "agent",  # the tool-calling core (was route_intent + support_rag)
    "verify_reply_language",
    "verify_confidence",
    "guardrail_out",
    "assemble",
}


def test_every_node_emits_a_span_and_cost_is_recorded() -> None:
    llm = scripted_llm(
        lang="en",
        intent="support",
        reply="You can reschedule up to 2 hours before the window.",
        citations=["delivery_reschedule_en"],
    )
    agent = Agent.create(config=load_config(), llm=llm)
    graph = build_graph(agent.deps)

    trace = Trace(turn_id="t-obs", session_id="obs")
    state = TurnState(
        turn_id="t-obs",
        session=Session(session_id="obs"),
        user_text="How late can I reschedule a delivery?",
        trace=trace,
    )
    final = graph.invoke({"ts": state})
    result_trace = final["ts"].trace

    emitted = [span.node for span in result_trace.spans]
    assert _EXPECTED_NODES <= set(emitted)
    # Each expected node emits exactly one span (no duplicates, no missing node).
    for node in _EXPECTED_NODES:
        assert emitted.count(node) == 1
    for span in result_trace.spans:
        assert span.status in ("ok", "error", "skipped")
        assert span.latency_ms >= 0.0

    # Token + cost accounting recorded across the turn's LLM calls.
    assert result_trace.tokens.output > 0
    assert result_trace.cost_usd > 0.0
