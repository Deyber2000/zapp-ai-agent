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
    assemble,
    detect_language,
    guardrail_in,
    guardrail_out,
    onboarding,
    placeholder,
    route_intent,
    support_rag,
    verify_confidence,
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


def _after_detect(state: GraphState) -> str:
    return "assemble" if state["ts"].blocked else "route"


def _after_intent(state: GraphState) -> str:
    ts = state["ts"]
    if ts.degraded or ts.intent is None:
        return "verify"
    if ts.intent == "support":
        return "support"
    if ts.intent == "onboarding":
        return "onboarding"
    if ts.intent == "clarify":
        return "verify"
    # action / out_of_scope → placeholder seam (US3/US4)
    return "placeholder"


def build_graph(deps: Deps) -> Any:
    """Compile the turn graph. Returns a LangGraph runnable invoked with `{"ts": TurnState}`."""

    # Typed `Any` at this isolated LangGraph seam: the engine's `add_node` overloads are
    # version-specific and would otherwise leak vendor typing into our build code.
    graph: Any = StateGraph(GraphState)

    graph.add_node("guardrail_in", _wrap("guardrail_in", guardrail_in, deps))
    graph.add_node("detect_language", _wrap("detect_language", detect_language, deps))
    graph.add_node("route_intent", _wrap("route_intent", route_intent, deps))
    graph.add_node("support_rag", _wrap("support_rag", support_rag, deps))
    graph.add_node("onboarding", _wrap("onboarding", onboarding, deps))
    graph.add_node("placeholder", _wrap("placeholder", placeholder, deps))
    graph.add_node("verify_confidence", _wrap("verify_confidence", verify_confidence, deps))
    graph.add_node("guardrail_out", _wrap("guardrail_out", guardrail_out, deps))
    # `assemble` always runs, even under degradation, so every path yields a valid contract.
    graph.add_node("assemble", _wrap("assemble", assemble, deps, always=True))

    graph.add_edge(START, "guardrail_in")
    graph.add_edge("guardrail_in", "detect_language")
    graph.add_conditional_edges(
        "detect_language", _after_detect, {"assemble": "assemble", "route": "route_intent"}
    )
    graph.add_conditional_edges(
        "route_intent",
        _after_intent,
        {
            "support": "support_rag",
            "onboarding": "onboarding",
            "placeholder": "placeholder",
            "verify": "verify_confidence",
        },
    )
    graph.add_edge("support_rag", "verify_confidence")
    graph.add_edge("onboarding", "verify_confidence")
    graph.add_edge("placeholder", "verify_confidence")
    graph.add_edge("verify_confidence", "guardrail_out")
    graph.add_edge("guardrail_out", "assemble")
    graph.add_edge("assemble", END)

    return graph.compile()
