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

# Metrics excluded from the byte-stable comparison: wall-clock latency, and the key-adaptive quality
# tier (LLM-judged over live outputs — present only in a keyed committed run, not a keyless CI run).
_UNSTABLE = frozenset(
    {"latency_p95_ms", "llm_judge_quality", "rag_faithfulness", "rag_contextual_relevancy"}
)

_STABLE = lambda metrics: {  # noqa: E731 — compact local helper
    m["name"]: (m["score"], m["passed"]) for m in metrics if m["name"] not in _UNSTABLE
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
