"""Eval data models (spec 004): dataset cases, run records, metrics, thresholds, and the report."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from zapp_assist.contracts import TurnResult
from zapp_assist.obs.trace import Trace

Capability = Literal["support", "onboarding", "action", "out_of_scope", "guardrail", "multilingual"]

_EVALS_DIR = Path(__file__).resolve().parent


class MockScript(BaseModel):
    """Deterministic model behavior for one turn — drives the eval's scripted LLM."""

    lang: str = "en"
    intent: str = "support"
    reply: str | None = None
    grounded: bool = True
    citations: list[str] = Field(default_factory=list)
    full_name: str | None = None
    phone_raw: str | None = None
    region_hint: str | None = None
    phone_normalized: str | None = None
    action: str | None = None
    order_id: str | None = None
    new_time: str | None = None
    safety_findings: list[str] = Field(default_factory=list)
    rewritten: str | None = None


class Expected(BaseModel):
    """Labels for a case (only the fields relevant to the case need be set)."""

    needs_review: bool | None = None
    lang: str | None = None
    final_normalized_text: str | None = None
    detected_country: str | None = None
    reply_contains: str | None = None
    blocked: bool | None = None  # an input guardrail refused/escalated
    safety: Literal["safe", "unsafe"] | None = None


class EvalCase(BaseModel):
    """One labeled evaluation case."""

    id: str
    capability: Capability
    turns: list[str]
    script: MockScript | list[MockScript]
    expected: Expected = Field(default_factory=Expected)
    semantic_enabled: bool = False

    def scripts(self) -> list[MockScript]:
        return self.script if isinstance(self.script, list) else [self.script]


class RunRecord(BaseModel):
    """The outcome of running one case: the final contract + per-turn traces (or an error)."""

    case_id: str
    result: TurnResult | None = None
    traces: list[Trace] = Field(default_factory=list)
    error: str | None = None


class MetricResult(BaseModel):
    """One scored metric with its threshold and pass/fail."""

    name: str
    score: float
    threshold: float
    passed: bool
    higher_is_better: bool = True
    detail: str | None = None
    applicable: bool = True


class JudgeVerdict(BaseModel):
    """An LLM-as-judge rubric verdict for one reply (each dimension 1–5)."""

    case_id: str
    helpfulness: int = 3
    groundedness: int = 3
    safety: int = 3
    language: int = 3
    notes: str | None = None

    def mean(self) -> float:
        return (self.helpfulness + self.groundedness + self.safety + self.language) / 4


class EvalThresholds(BaseModel):
    """Config-driven pass/fail thresholds (evals/eval_config.yaml)."""

    task_success_min: float = 0.9
    language_fidelity_min: float = 0.95
    guardrail_recall_min: float = 0.9
    guardrail_precision_min: float = 0.9
    judge_min: float = 3.5  # out of 5
    latency_p95_max_ms: float = 5000.0
    cost_per_convo_max: float = 0.05
    # Quality tier (key-adaptive; LLM-judged over live outputs — see quality_tier.py).
    llm_judge_min: float = 3.5  # out of 5
    faithfulness_min: float = 0.7  # deepeval, [0,1]
    contextual_relevancy_min: float = 0.2  # deepeval [0,1] — lenient sanity floor (top-k)


class EvalReport(BaseModel):
    """The single report artifact: all metric results + breakdowns + overall pass/fail."""

    total_cases: int = 0
    metrics: list[MetricResult] = Field(default_factory=list)
    by_capability: dict[str, float] = Field(default_factory=dict)
    judge: list[JudgeVerdict] = Field(default_factory=list)
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    cost_per_convo: float = 0.0
    overall_passed: bool = False
    generated_note: str = "deterministic (scripted model + rule-based judge)"


def load_thresholds(path: str | Path | None = None) -> EvalThresholds:
    cfg_path = Path(path) if path else _EVALS_DIR / "eval_config.yaml"
    if not cfg_path.exists():
        return EvalThresholds()
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return EvalThresholds.model_validate(data.get("thresholds", data))


def load_dataset(path: str | Path | None = None) -> list[EvalCase]:
    directory = Path(path) if path else _EVALS_DIR / "dataset"
    cases: list[EvalCase] = []
    for file in sorted(directory.glob("*.json")):
        import json

        payload = json.loads(file.read_text(encoding="utf-8"))
        for raw in payload:
            cases.append(EvalCase.model_validate(raw))
    return cases
