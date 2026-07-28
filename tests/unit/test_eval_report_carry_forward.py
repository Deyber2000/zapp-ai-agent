"""A keyless `zapp-eval` run must not silently wipe a prior keyed run's live-tier metrics (004).

The committed report carries LLM-as-judge + deepeval numbers the brief asks for. A reviewer running
`zapp-eval` keyless (per the README) would otherwise overwrite report.{json,md} with the 7-metric
deterministic version, and the drift guard can't catch it — it excludes those three as
non-reproducible. `write_report` carries them forward, labelled.
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.models import EvalReport, MetricResult
from evals.report import write_report

_LIVE = ("llm_judge_quality", "rag_faithfulness", "rag_contextual_relevancy")


def _det() -> MetricResult:
    return MetricResult(name="task_success", score=1.0, threshold=0.9, passed=True)


def _keyed() -> EvalReport:
    live = [
        MetricResult(name="llm_judge_quality", score=4.588, threshold=3.5, passed=True),
        MetricResult(name="rag_faithfulness", score=0.938, threshold=0.7, passed=True),
        MetricResult(name="rag_contextual_relevancy", score=0.356, threshold=0.2, passed=True),
    ]
    return EvalReport(total_cases=20, metrics=[_det(), *live], overall_passed=True)


def _keyless() -> EvalReport:
    return EvalReport(total_cases=20, metrics=[_det()], overall_passed=True)


def _names(path: Path) -> dict[str, dict]:
    written = json.loads(path.read_text(encoding="utf-8"))
    return {m["name"]: m for m in written["metrics"]}


def test_keyless_run_preserves_prior_keyed_live_tier_metrics(tmp_path: Path) -> None:
    json_path, _ = write_report(_keyed(), tmp_path)  # the committed keyed report
    write_report(_keyless(), tmp_path)  # a reviewer's keyless run over the top

    metrics = _names(json_path)
    for name in _LIVE:
        assert name in metrics, f"{name} was silently dropped by the keyless run"
        assert "carried from a prior keyed run" in (metrics[name]["detail"] or "")
    # the stale carried metrics do NOT gate the fresh keyless run
    assert json.loads(json_path.read_text())["overall_passed"] is True


def test_carry_forward_is_idempotent_across_repeated_keyless_runs(tmp_path: Path) -> None:
    write_report(_keyed(), tmp_path)
    write_report(_keyless(), tmp_path)
    json_path, _ = write_report(_keyless(), tmp_path)  # second keyless run
    detail = _names(json_path)["rag_faithfulness"]["detail"] or ""
    assert detail.count("carried from a prior keyed run") == 1  # label not duplicated


def test_a_fresh_keyed_run_overwrites_rather_than_carrying(tmp_path: Path) -> None:
    write_report(_keyed(), tmp_path)
    fresh = _keyed()
    fresh.metrics = [m for m in fresh.metrics]  # a keyed run supplies its own live metrics
    json_path, _ = write_report(fresh, tmp_path)
    faith = _names(json_path)["rag_faithfulness"]["detail"] or ""
    assert "carried from a prior keyed run" not in faith  # its own value, not carried
