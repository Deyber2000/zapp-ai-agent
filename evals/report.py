"""Eval report (spec 004): assemble the single report artifact and write report.json + report.md.

US1 gates on task success and reports operational latency/cost (informational). US2–US4 append the
language-fidelity, guardrail precision/recall, and judge metrics to `metrics`.
"""

from __future__ import annotations

from pathlib import Path

from .judge import Judge, RuleBasedJudge
from .metrics import (
    cost_per_conversation,
    guardrail_precision,
    guardrail_recall,
    judge_quality,
    language_fidelity,
    latency_percentiles,
    task_success,
    task_success_by_capability,
)
from .models import EvalCase, EvalReport, EvalThresholds, MetricResult, RunRecord

_EVALS_DIR = Path(__file__).resolve().parent


def build_report(
    records: list[RunRecord],
    cases: list[EvalCase],
    thresholds: EvalThresholds,
    judge: Judge | None = None,
    extra_metrics: list[MetricResult] | None = None,
    note: str = "deterministic (scripted model + rule-based judge)",
) -> EvalReport:
    judge = judge or RuleBasedJudge()
    by_id = {c.id: c for c in cases}
    verdicts = [judge.score(by_id[rec.case_id], rec) for rec in records]

    metrics = [
        task_success(records, cases, thresholds),
        language_fidelity(records, cases, thresholds),
        guardrail_recall(records, cases, thresholds),
        guardrail_precision(records, cases, thresholds),
        judge_quality(verdicts, thresholds),
        *(extra_metrics or []),
    ]
    p50, p95 = latency_percentiles(records)
    overall = all(m.passed for m in metrics if m.applicable)
    return EvalReport(
        total_cases=len(records),
        metrics=metrics,
        by_capability=task_success_by_capability(records, cases),
        judge=verdicts,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        cost_per_convo=cost_per_conversation(records),
        overall_passed=overall,
        generated_note=note,
    )


def render_markdown(report: EvalReport) -> str:
    status = "✅ PASS" if report.overall_passed else "❌ FAIL"
    lines = [
        "# Zapp Assist — Evaluation Report",
        "",
        f"**Overall: {status}**  ·  cases: {report.total_cases}  ·  _{report.generated_note}_",
        "",
        "## Metrics",
        "",
        "| Metric | Score | Threshold | Result |",
        "| --- | --- | --- | --- |",
    ]
    for m in report.metrics:
        if not m.applicable:
            lines.append(f"| {m.name} | n/a | — | — |")
            continue
        arrow = "≥" if m.higher_is_better else "≤"
        verdict = "PASS" if m.passed else "FAIL"
        detail = f" ({m.detail})" if m.detail else ""
        lines.append(f"| {m.name} | {m.score}{detail} | {arrow} {m.threshold} | {verdict} |")
    lines += [
        "",
        "## Operational",
        "",
        f"- latency p50: {report.latency_p50_ms} ms · p95: {report.latency_p95_ms} ms",
        f"- estimated cost / conversation: ${report.cost_per_convo}",
        "",
        "## Task success by capability",
        "",
    ]
    for cap, score in report.by_capability.items():
        lines.append(f"- {cap}: {score}")
    if report.judge:
        avg = round(sum(v.mean() for v in report.judge) / len(report.judge), 3)
        lines += ["", "## LLM-as-judge", "", f"- average rubric score: {avg} / 5"]
    lines.append("")
    return "\n".join(lines)


def write_report(report: EvalReport, out_dir: Path | str | None = None) -> tuple[Path, Path]:
    directory = Path(out_dir) if out_dir else _EVALS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    md_path = directory / "report.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
