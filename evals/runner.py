"""Eval runner (spec 004): execute a case through the real agent, capturing contract + trace.

Pure observer — it builds the agent and its compiled graph and invokes turns directly (like the
observability test), threading one `Session` across a multi-turn case, to read the per-turn `Trace`
without adding any API to `Agent`. A case that raises is recorded as an error (never aborts).
"""

from __future__ import annotations

from time import perf_counter

from zapp_assist.agent import Agent
from zapp_assist.config import AppConfig, load_config
from zapp_assist.graph.build import build_graph
from zapp_assist.graph.state import TurnState
from zapp_assist.memory.session_store import Session
from zapp_assist.obs.trace import Trace

from .models import EvalCase, RunRecord
from .scripted_llm import build_scripted_llm


def _config_for(case: EvalCase, base: AppConfig) -> AppConfig:
    # Per-case toggle of the guardrail semantic layer; everything else = the agent's config.
    guardrails = base.guardrails.model_copy(update={"semantic_enabled": case.semantic_enabled})
    return base.model_copy(update={"guardrails": guardrails})


def run_case(case: EvalCase, base_config: AppConfig | None = None) -> RunRecord:
    base = base_config or load_config()
    scripts = case.scripts()
    llm = build_scripted_llm(scripts)
    try:
        agent = Agent.create(config=_config_for(case, base), llm=llm)
        graph = build_graph(agent.deps)
        session = Session(session_id=case.id)
        traces: list[Trace] = []
        result = None
        for index, text in enumerate(case.turns):
            llm.use_turn(index)
            trace = Trace(turn_id=f"{case.id}-{index}", session_id=case.id)
            state = TurnState(turn_id=trace.turn_id, session=session, user_text=text, trace=trace)
            t0 = perf_counter()
            final = graph.invoke({"ts": state})
            ts: TurnState = final["ts"]
            ts.trace.total_latency_ms = (perf_counter() - t0) * 1000  # runner bypasses run_turn
            session = ts.session  # thread state across turns
            result = ts.result
            traces.append(ts.trace)
        return RunRecord(case_id=case.id, result=result, traces=traces)
    except Exception as exc:  # a broken case fails its metrics; the run continues (FR-004)
        return RunRecord(case_id=case.id, error=f"{type(exc).__name__}: {exc}")


def run_dataset(cases: list[EvalCase], base_config: AppConfig | None = None) -> list[RunRecord]:
    base = base_config or load_config()
    return [run_case(case, base) for case in cases]
