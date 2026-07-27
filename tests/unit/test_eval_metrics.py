"""US2 (004) — metric math on synthetic records (no agent run needed).

Covers language fidelity, guardrail precision/recall (TP/FP/FN), latency percentiles, cost, and
not-applicable handling.
"""

from __future__ import annotations

from evals.metrics import (
    cost_metric,
    cost_per_conversation,
    guardrail_precision,
    guardrail_recall,
    language_fidelity,
    latency_metric,
    latency_percentiles,
)
from evals.models import EvalCase, EvalThresholds, Expected, MockScript, RunRecord

from zapp_assist.contracts import GuardrailDecision, Guardrails, TurnResult
from zapp_assist.obs.trace import Trace

_THR = EvalThresholds()
_REFUSE = [
    GuardrailDecision(rule="x", action="refuse", severity="high", category="prompt_injection")
]


def _result(active_lang: str = "en", guard_in: list[GuardrailDecision] | None = None) -> TurnResult:
    return TurnResult(
        reply="a sufficiently long reply for detection",
        detected_lang=active_lang,
        active_lang=active_lang,
        lang_confidence=0.9,
        final_normalized_text="x",
        confidence_score=0.9,
        needs_review=False,
        guardrails=Guardrails(input=guard_in or []),
    )


def _case(cid: str, *, lang: str | None = None, safety: str | None = None) -> EvalCase:
    return EvalCase(
        id=cid,
        capability="support",
        turns=["t"],
        script=MockScript(),
        expected=Expected(lang=lang, safety=safety),  # type: ignore[arg-type]
    )


def _rec(cid: str, result: TurnResult, traces: list[Trace] | None = None) -> RunRecord:
    return RunRecord(case_id=cid, result=result, traces=traces or [])


def test_language_fidelity_excludes_cases_without_expected_lang() -> None:
    cases = [_case("a", lang="es"), _case("b", lang="en"), _case("c")]  # c → not applicable
    records = [_rec("a", _result("es")), _rec("b", _result("en")), _rec("c", _result("en"))]
    m = language_fidelity(records, cases, _THR)
    assert m.applicable and m.score == 1.0 and "2/2" in (m.detail or "")


def test_language_fidelity_counts_mismatches() -> None:
    cases = [_case("a", lang="es"), _case("b", lang="en")]
    records = [_rec("a", _result("en")), _rec("b", _result("en"))]  # a is wrong
    assert language_fidelity(records, cases, _THR).score == 0.5


def test_guardrail_precision_and_recall() -> None:
    cases = [
        _case("u1", safety="unsafe"),
        _case("u2", safety="unsafe"),
        _case("s1", safety="safe"),
        _case("s2", safety="safe"),
    ]
    records = [
        _rec("u1", _result(guard_in=_REFUSE)),  # unsafe + flagged  → TP
        _rec("u2", _result(guard_in=[])),        # unsafe + missed   → FN
        _rec("s1", _result(guard_in=[])),        # safe + clean      → TN
        _rec("s2", _result(guard_in=_REFUSE)),   # safe + flagged    → FP
    ]
    assert guardrail_recall(records, cases, _THR).score == 0.5   # TP/(TP+FN) = 1/2
    assert guardrail_precision(records, cases, _THR).score == 0.5  # TP/(TP+FP) = 1/2


def test_guardrail_metrics_not_applicable_without_labels() -> None:
    cases = [_case("a", lang="en")]
    records = [_rec("a", _result())]
    assert guardrail_recall(records, cases, _THR).applicable is False


def test_latency_percentiles_and_cost() -> None:
    def trace(latency: float, cost: float) -> Trace:
        t = Trace(turn_id="t", session_id="s")
        t.total_latency_ms = latency
        t.cost_usd = cost
        return t

    records = [
        _rec("a", _result(), [trace(10, 0.001)]),
        _rec("b", _result(), [trace(20, 0.002)]),
        _rec("c", _result(), [trace(100, 0.003)]),
    ]
    p50, p95 = latency_percentiles(records)
    assert p50 == 20.0 and p95 == 100.0
    assert cost_per_conversation(records) == round((0.001 + 0.002 + 0.003) / 3, 6)


def test_latency_and_cost_metrics_gate_on_a_ceiling() -> None:
    def trace(latency: float, cost: float) -> Trace:
        t = Trace(turn_id="t", session_id="s")
        t.total_latency_ms, t.cost_usd = latency, cost
        return t

    records = [_rec("a", _result(), [trace(10, 0.001)]), _rec("b", _result(), [trace(100, 0.003)])]

    # These are "lower is better" ceilings.
    ok = EvalThresholds(latency_p95_max_ms=1000, cost_per_convo_max=1.0)
    assert latency_metric(records, ok).passed is True
    assert latency_metric(records, ok).higher_is_better is False
    assert cost_metric(records, ok).passed is True

    # A tight ceiling fails.
    assert latency_metric(records, EvalThresholds(latency_p95_max_ms=50)).passed is False
    assert cost_metric(records, EvalThresholds(cost_per_convo_max=0.0001)).passed is False
