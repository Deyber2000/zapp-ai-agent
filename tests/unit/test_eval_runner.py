"""US1 (004) — the runner produces one report + a CI exit code; errors are isolated.

The runner executes the real agent over the labeled dataset (deterministic scripted model), a broken
case is recorded as an error without aborting the run, and the overall pass/fail (→ CLI exit code)
flips when a threshold changes on the same records.
"""

from __future__ import annotations

import evals.runner as runner_mod
import pytest
from evals.models import EvalCase, EvalThresholds, MockScript, load_dataset, load_thresholds
from evals.report import build_report
from evals.runner import run_case, run_dataset


def _boom(deps: object) -> object:
    raise RuntimeError("boom")


def test_run_case_isolates_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "build_graph", _boom)
    case = EvalCase(id="boom", capability="support", turns=["hello there"], script=MockScript())
    record = run_case(case)
    assert record.result is None
    assert record.error is not None and "boom" in record.error


def test_run_dataset_produces_a_record_per_case_and_runs_clean() -> None:
    cases = load_dataset()
    records = run_dataset(cases)
    assert len(records) == len(cases)
    assert all(r.error is None for r in records)  # the seed dataset runs cleanly


def test_seed_dataset_passes_and_reports_one_result_per_metric() -> None:
    cases = load_dataset()
    report = build_report(run_dataset(cases), cases, load_thresholds())
    assert report.total_cases == len(cases)
    assert report.overall_passed is True
    task = next(m for m in report.metrics if m.name == "task_success")
    assert task.score == 1.0 and task.passed is True


def test_threshold_change_flips_overall_pass_fail() -> None:
    cases = load_dataset()
    records = run_dataset(cases)
    # An impossible threshold makes the SAME run fail → overall False (→ CLI exits non-zero).
    report = build_report(records, cases, EvalThresholds(task_success_min=1.01))
    assert report.overall_passed is False
    assert next(m for m in report.metrics if m.name == "task_success").passed is False
