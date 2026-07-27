"""Eval metrics (spec 004). Pure functions over run records + labeled cases → MetricResult / values.

US1 ships task success + the operational computations the report needs (latency percentiles, cost).
Language fidelity and guardrail precision/recall arrive with US2; the judge metric with US3.
"""

from __future__ import annotations

from collections import defaultdict

from .models import EvalCase, EvalThresholds, MetricResult, RunRecord


def flagged(record: RunRecord) -> bool:
    """A turn is 'flagged' if an input guardrail refused/escalated it (blocked)."""

    if record.result is None:
        return False
    return any(d.action in ("refuse", "escalate") for d in record.result.guardrails.input)


def case_succeeded(record: RunRecord, case: EvalCase) -> bool:
    """Did the observed outcome match the case's labels? (Only set labels are checked.)"""

    if record.error or record.result is None:
        return False
    r, e = record.result, case.expected
    if e.needs_review is not None and r.needs_review != e.needs_review:
        return False
    if e.lang is not None and r.active_lang != e.lang:
        return False
    if e.final_normalized_text is not None and r.final_normalized_text != e.final_normalized_text:
        return False
    if e.detected_country is not None and r.detected_country != e.detected_country:
        return False
    if e.reply_contains is not None and e.reply_contains.lower() not in r.reply.lower():
        return False
    if e.blocked is not None and flagged(record) != e.blocked:
        return False
    return True


def task_success(
    records: list[RunRecord], cases: list[EvalCase], thresholds: EvalThresholds
) -> MetricResult:
    by_id = {c.id: c for c in cases}
    total = len(records)
    matches = sum(1 for rec in records if case_succeeded(rec, by_id[rec.case_id]))
    score = matches / total if total else 0.0
    return MetricResult(
        name="task_success",
        score=round(score, 4),
        threshold=thresholds.task_success_min,
        passed=total > 0 and score >= thresholds.task_success_min,
        detail=f"{matches}/{total} cases",
        applicable=total > 0,
    )


def task_success_by_capability(
    records: list[RunRecord], cases: list[EvalCase]
) -> dict[str, float]:
    by_id = {c.id: c for c in cases}
    total: dict[str, int] = defaultdict(int)
    ok: dict[str, int] = defaultdict(int)
    for rec in records:
        cap = by_id[rec.case_id].capability
        total[cap] += 1
        if case_succeeded(rec, by_id[rec.case_id]):
            ok[cap] += 1
    return {cap: round(ok[cap] / total[cap], 4) for cap in sorted(total)}


def _latencies(records: list[RunRecord]) -> list[float]:
    return sorted(t.total_latency_ms for rec in records for t in rec.traces)


def latency_percentiles(records: list[RunRecord]) -> tuple[float, float]:
    """(p50, p95) of per-turn latency in ms; (0, 0) when there is no data."""

    values = _latencies(records)
    if not values:
        return 0.0, 0.0

    def pct(p: float) -> float:
        idx = min(len(values) - 1, round((p / 100) * (len(values) - 1)))
        return round(values[idx], 3)

    return pct(50), pct(95)


def cost_per_conversation(records: list[RunRecord]) -> float:
    """Mean estimated cost per case (sum of per-turn trace costs)."""

    costs = [sum(t.cost_usd for t in rec.traces) for rec in records if rec.traces]
    return round(sum(costs) / len(costs), 6) if costs else 0.0
