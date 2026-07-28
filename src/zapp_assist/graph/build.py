"""The ONLY LangGraph-aware module (Constitution II/V: orchestration engine isolated here).

Wires the stateless nodes into a `StateGraph` over `TurnState`. A node runner wraps every node to:
  * skip processing nodes once the turn is degraded (recording a `skipped` span), while always
    running `assemble` so a valid contract is still produced;
  * catch any exception → an `error` span + degraded route (never a crash).

The entire `TurnState` rides in a single graph channel, so nodes keep their `(state) -> state`
shape and LangGraph's per-field channel semantics never leak into node code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..obs.trace import Span
from .deps import Deps
from .nodes import (
    action_execute,
    agent,
    assemble,
    detect_language,
    guardrail_in,
    guardrail_out,
    onboarding,
    out_of_scope,
    smalltalk,
    verify_confidence,
    verify_reply_language,
)
from .state import TurnState

NodeFn = Callable[[TurnState, Deps], TurnState]


class GraphState(TypedDict):
    ts: TurnState


Runner = Callable[[GraphState], dict[str, TurnState]]


def _wrap(name: str, fn: NodeFn, deps: Deps, *, always: bool = False) -> Runner:
    """Wrap a pure node with skip-on-degraded + exception-to-degraded handling."""

    def runner(state: GraphState) -> dict[str, TurnState]:
        ts = state["ts"]
        if ts.degraded and not always:
            ts.trace.add_span(Span(node=name, status="skipped"))
            return {"ts": ts}
        try:
            ts = fn(ts, deps)
        except Exception as exc:  # never crash — degrade and record
            ts.degraded = True
            ts.trace.add_span(
                Span(node=name, status="error", attrs={"error": type(exc).__name__})
            )
        return {"ts": ts}

    return runner


def _route_after_language(state: GraphState) -> str:
    ts = state["ts"]
    if ts.blocked:
        return "assemble"
    # A pending action awaiting confirmation makes THIS turn a confirmation response — routed
    # deterministically straight to execution, never back through the agent. This is the single
    # human-in-the-loop gate: nothing irreversible runs without an explicit yes (FR-012/013).
    pending = ts.session.pending_action
    if pending is not None and pending.status == "awaiting_confirmation":
        return "action_execute"
    return "agent"


def _after_agent(state: GraphState) -> str:
    ts = state["ts"]
    if ts.degraded:
        return "verify"
    # The agent defers onboarding / smalltalk / out_of_scope to their specialist nodes; support,
    # action proposals, and clarify are already answered by the agent → go straight to verify.
    if ts.intent == "onboarding":
        return "onboarding"
    if ts.intent == "out_of_scope":
        return "out_of_scope"
    if ts.intent == "smalltalk":
        return "smalltalk"
    return "verify"


def build_graph(deps: Deps) -> Any:
    """Compile the turn graph. Returns a LangGraph runnable invoked with `{"ts": TurnState}`."""

    # Typed `Any` at this isolated LangGraph seam: the engine's `add_node` overloads are
    # version-specific and would otherwise leak vendor typing into our build code.
    graph: Any = StateGraph(GraphState)

    graph.add_node("guardrail_in", _wrap("guardrail_in", guardrail_in, deps))
    graph.add_node("detect_language", _wrap("detect_language", detect_language, deps))
    # The tool-calling agent: one reasoning loop that understands the turn and chooses a tool.
    graph.add_node("agent", _wrap("agent", agent, deps))
    graph.add_node("onboarding", _wrap("onboarding", onboarding, deps))
    graph.add_node("action_execute", _wrap("action_execute", action_execute, deps))
    graph.add_node("out_of_scope", _wrap("out_of_scope", out_of_scope, deps))
    graph.add_node("smalltalk", _wrap("smalltalk", smalltalk, deps))
    graph.add_node(
        "verify_reply_language", _wrap("verify_reply_language", verify_reply_language, deps)
    )
    graph.add_node("verify_confidence", _wrap("verify_confidence", verify_confidence, deps))
    graph.add_node("guardrail_out", _wrap("guardrail_out", guardrail_out, deps))
    # `assemble` always runs, even under degradation, so every path yields a valid contract.
    graph.add_node("assemble", _wrap("assemble", assemble, deps, always=True))

    graph.add_edge(START, "guardrail_in")
    graph.add_edge("guardrail_in", "detect_language")
    graph.add_conditional_edges(
        "detect_language",
        _route_after_language,
        {"assemble": "assemble", "action_execute": "action_execute", "agent": "agent"},
    )
    graph.add_conditional_edges(
        "agent",
        _after_agent,
        {
            "onboarding": "onboarding",
            "out_of_scope": "out_of_scope",
            "smalltalk": "smalltalk",
            "verify": "verify_reply_language",
        },
    )
    # Every path that produces a reply flows through reply-language verification before confidence.
    graph.add_edge("onboarding", "verify_reply_language")
    graph.add_edge("action_execute", "verify_reply_language")
    graph.add_edge("out_of_scope", "verify_reply_language")
    graph.add_edge("smalltalk", "verify_reply_language")
    graph.add_edge("verify_reply_language", "verify_confidence")
    graph.add_edge("verify_confidence", "guardrail_out")
    graph.add_edge("guardrail_out", "assemble")
    graph.add_edge("assemble", END)

    return graph.compile()
