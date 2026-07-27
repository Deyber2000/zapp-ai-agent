"""US4 (004) — the committed report stays consistent with a fresh deterministic run.

Guards against the committed `evals/report.json` drifting from the code/dataset. Correctness metrics
(task success, language fidelity, guardrail P/R, judge, cost) and the overall pass/fail are
byte-stable; only latency is environment-dependent, so it is excluded from the comparison.
"""

from __future__ import annotations

import json
from pathlib import Path

import evals
from evals.models import load_dataset, load_thresholds
from evals.report import build_report
from evals.runner import run_dataset

_STABLE = lambda metrics: {  # noqa: E731 — compact local helper
    m["name"]: (m["score"], m["passed"])
    for m in metrics
    if m["name"] != "latency_p95_ms"  # wall-clock varies by environment
}


def test_committed_report_matches_a_fresh_deterministic_run() -> None:
    report_path = Path(evals.__file__).resolve().parent / "report.json"
    committed = json.loads(report_path.read_text(encoding="utf-8"))

    cases = load_dataset()
    fresh = build_report(run_dataset(cases), cases, load_thresholds()).model_dump()

    assert fresh["overall_passed"] == committed["overall_passed"] is True
    assert fresh["total_cases"] == committed["total_cases"]
    assert fresh["by_capability"] == committed["by_capability"]
    assert _STABLE(fresh["metrics"]) == _STABLE(committed["metrics"])
