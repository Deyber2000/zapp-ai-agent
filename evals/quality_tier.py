"""Key-adaptive quality tier (spec 004): LLM-as-judge + deepeval RAG metrics over LIVE outputs.

Runs ONLY when an OpenAI key is present AND deepeval is importable; otherwise it is skipped and the
deterministic core (scripted model + rule-based judge) stays the keyless CI gate — no `--live` flag,
activation is automatic. It re-runs each case through the REAL agent (real provider + the configured
retrieval), then scores the live replies with an LLM-as-judge (our adapter, a 1-5 rubric) plus
deepeval **faithfulness** and **contextual relevancy** over the actually-retrieved
context. These metrics are EXCLUDED from the byte-stable committed-report drift guard (like latency)
because LLM judgments are not reproducible. Every step degrades safely: a failing case or metric is
skipped, never aborting the run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from time import perf_counter

from zapp_assist.agent import Agent
from zapp_assist.config import AppConfig, Settings
from zapp_assist.graph.build import build_graph
from zapp_assist.graph.state import TurnState
from zapp_assist.memory.session_store import Session
from zapp_assist.obs.trace import Trace

from .judge import LLMJudge
from .models import EvalCase, EvalThresholds, JudgeVerdict, MetricResult, RunRecord

# deepeval's RAG metrics are slow (many sub-calls each); cap them to a representative sample of
# grounded cases so the one-off keyed report stays a few minutes, not tens. The LLM-as-judge runs
# over every live case (one cheap call each).
_MAX_DEEPEVAL_CASES = 5


@dataclass
class _Live:
    case: EvalCase
    record: RunRecord
    context: list[str] = field(default_factory=list)  # retrieval_context (doc texts), final turn


def quality_tier_available(settings: Settings) -> bool:
    """True when a key is present and deepeval is importable — the tier runs, else it is skipped."""

    if not settings.openai_api_key:
        return False
    try:
        import deepeval  # noqa: F401
    except Exception:
        return False
    return True


def _live_config(config: AppConfig) -> AppConfig:
    """Use the configured retrieval (config-as-data) — NOT the bm25-pinned deterministic path."""

    return config


def _run_live_case(case: EvalCase, graph, agent: Agent) -> _Live:  # type: ignore[no-untyped-def]
    """Run one case through the real agent, capturing the final reply + retrieved context."""

    session = Session(session_id=case.id)
    traces: list[Trace] = []
    result = None
    context: list[str] = []
    try:
        for index, text in enumerate(case.turns):
            trace = Trace(turn_id=f"{case.id}-{index}", session_id=case.id)
            state = TurnState(turn_id=trace.turn_id, session=session, user_text=text, trace=trace)
            t0 = perf_counter()
            final = graph.invoke({"ts": state})
            ts: TurnState = final["ts"]
            ts.trace.total_latency_ms = (perf_counter() - t0) * 1000
            session = ts.session
            result = ts.result
            context = [doc.text for doc in (ts.retrieval or [])]
            traces.append(ts.trace)
        return _Live(case, RunRecord(case_id=case.id, result=result, traces=traces), context)
    except Exception as exc:  # a broken live case is skipped; the tier continues
        return _Live(case, RunRecord(case_id=case.id, error=f"{type(exc).__name__}: {exc}"))


def _judge_metric(verdicts: list[JudgeVerdict], thresholds: EvalThresholds) -> MetricResult | None:
    if not verdicts:
        return None
    avg = sum(v.mean() for v in verdicts) / len(verdicts)
    return MetricResult(
        name="llm_judge_quality",
        score=round(avg, 3),
        threshold=thresholds.llm_judge_min,
        passed=avg >= thresholds.llm_judge_min,
        detail=f"LLM-as-judge over {len(verdicts)} live replies (out of 5)",
    )


def _avg_metric(name: str, scores: list[float], minimum: float, detail: str) -> MetricResult | None:
    if not scores:
        return None
    avg = sum(scores) / len(scores)
    return MetricResult(
        name=name, score=round(avg, 3), threshold=minimum, passed=avg >= minimum, detail=detail
    )


def _deepeval_metrics(
    live: list[_Live], model: str, thresholds: EvalThresholds
) -> list[MetricResult]:
    """deepeval faithfulness + contextual relevancy over cases that actually retrieved context."""

    from deepeval.metrics import ContextualRelevancyMetric, FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    grounded = [
        lv for lv in live if not lv.record.error and lv.record.result is not None and lv.context
    ][:_MAX_DEEPEVAL_CASES]
    faiths: list[float] = []
    ctxs: list[float] = []
    for lv in grounded:
        assert lv.record.result is not None
        tc = LLMTestCase(
            input=lv.case.turns[-1],
            actual_output=lv.record.result.reply,
            retrieval_context=lv.context,
        )
        try:
            f = FaithfulnessMetric(model=model, threshold=thresholds.faithfulness_min)
            f.measure(tc)
            faiths.append(float(f.score))
        except Exception:
            pass
        try:
            c = ContextualRelevancyMetric(
                model=model, threshold=thresholds.contextual_relevancy_min
            )
            c.measure(tc)
            ctxs.append(float(c.score))
        except Exception:
            pass

    out = [
        _avg_metric(
            "rag_faithfulness", faiths, thresholds.faithfulness_min,
            f"deepeval, {len(faiths)} grounded cases [0-1]",
        ),
        _avg_metric(
            "rag_contextual_relevancy", ctxs, thresholds.contextual_relevancy_min,
            f"deepeval, {len(ctxs)} grounded cases [0-1]",
        ),
    ]
    return [m for m in out if m is not None]


def run_quality_tier(
    cases: list[EvalCase], config: AppConfig, settings: Settings, thresholds: EvalThresholds
) -> list[MetricResult]:
    """Run the live LLM-judged + deepeval tier. Returns [] if unavailable/failed (i.e. skipped)."""

    if not quality_tier_available(settings):
        return []
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

    try:
        live_cfg = _live_config(config)
        agent = Agent.create(config=live_cfg)  # one real agent; the KB is embedded once
        graph = build_graph(agent.deps)
        live = [_run_live_case(case, graph, agent) for case in cases]

        judge = LLMJudge(agent.deps.llm, live_cfg)
        verdicts = [judge.score(lv.case, lv.record) for lv in live if lv.record.result is not None]
        metrics: list[MetricResult] = []
        judge_metric = _judge_metric(verdicts, thresholds)
        if judge_metric is not None:
            metrics.append(judge_metric)
        metrics.extend(_deepeval_metrics(live, config.models.primary, thresholds))
        return metrics
    except Exception:  # the tier is best-effort — never break the core report
        return []
