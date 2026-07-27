# Data Model: Evaluation Suite (004)

All models live in `evals/models.py` (Pydantic v2). They describe the dataset, the per-case scripted
model, and the report. Nothing here touches the agent's `TurnResult` (consumed read-only).

## 1. Dataset

### `MockScript` — the deterministic model behavior for a case

| Field | Type | Meaning |
|---|---|---|
| `lang` | str | language the mock LangSignal reports (es/en/pt) |
| `intent` | str | intent the mock router returns (support/onboarding/action/out_of_scope/clarify) |
| `reply` | str \| None | grounded answer text (support) |
| `grounded` | bool | GroundedAnswer.grounded |
| `citations` | list[str] | grounded citations |
| `full_name` / `phone_raw` / `region_hint` / `phone_normalized` | str \| None | onboarding extraction |
| `action` / `order_id` / `new_time` | str \| None | action extraction |
| `safety_findings` | list[str] | categories the semantic classifier returns (for guardrail cases) |
| `rewritten` | str \| None | RewrittenReply text (language correction), if needed |

### `Expected` — the labels for a case

| Field | Type | Meaning |
|---|---|---|
| `intent` | str \| None | expected routed intent |
| `needs_review` | bool \| None | expected review flag |
| `grounded` | bool \| None | expected grounded outcome |
| `lang` | str \| None | expected reply language |
| `final_normalized_text` | str \| None | expected canonical value (onboarding) |
| `detected_country` | str \| None | expected country (onboarding) |
| `safety` | Literal[safe, unsafe] | guardrail label |
| `blocked` | bool \| None | expected block outcome |
| `state_changed` | bool \| None | expected backend mutation (action) |

### `EvalCase`

| Field | Type | Meaning |
|---|---|---|
| `id` | str | unique case id |
| `capability` | Literal[support, onboarding, action, out_of_scope, guardrail, multilingual] | what it exercises |
| `turns` | list[str] | one or more user messages (multi-turn for action/onboarding) |
| `script` | MockScript \| list[MockScript] | per-turn deterministic model behavior |
| `expected` | Expected | labels |
| `semantic_enabled` | bool = False | whether the guardrail semantic layer is on for this case |

The dataset is JSON files under `evals/dataset/`, validated into `EvalCase` on load.

## 2. Per-case run record (transient)

| Field | Type | Meaning |
|---|---|---|
| `case_id` | str | the case |
| `result` | TurnResult | the final turn's contract (from the agent) |
| `traces` | list[Trace] | per-turn traces (latency/cost/spans) |
| `error` | str \| None | set if the case raised (→ task-success failure, run continues) |

## 3. Metrics & report

### `MetricResult`

| Field | Type | Meaning |
|---|---|---|
| `name` | str | metric id (e.g. task_success, language_fidelity, guardrail_recall) |
| `score` | float | value in [0, 1] (rates) or an absolute (latency ms / cost) |
| `threshold` | float | configured minimum (or maximum for latency/cost) |
| `passed` | bool | score meets the threshold (≥ for rates/judge, ≤ for latency/cost) |
| `detail` | str \| None | e.g. "18/20 cases", "TP=9 FP=0 FN=1" |

### `JudgeVerdict`

| Field | Type | Meaning |
|---|---|---|
| `case_id` | str | the reply judged |
| `helpfulness` / `groundedness` / `safety` / `language` | int (1–5) | rubric dimensions |
| `notes` | str \| None | optional |

`quality = mean(mean(dimensions) per verdict)`, reported as a `MetricResult` (scaled to [0,1] or kept 1–5).

### `EvalThresholds` (from `evals/eval_config.yaml`)

| Field | Default | Direction |
|---|---|---|
| `task_success_min` | 0.9 | ≥ |
| `language_fidelity_min` | 0.95 | ≥ |
| `guardrail_recall_min` | 0.9 | ≥ |
| `guardrail_precision_min` | 0.9 | ≥ |
| `judge_min` | 3.5 (of 5) | ≥ |
| `latency_p95_max_ms` | 5000 | ≤ |
| `cost_per_convo_max` | 0.05 | ≤ |

### `EvalReport`

| Field | Type | Meaning |
|---|---|---|
| `total_cases` | int | dataset size |
| `metrics` | list[MetricResult] | every metric with score/threshold/passed |
| `by_capability` | dict[str, float] | task-success per capability |
| `judge` | list[JudgeVerdict] | per-case rubric verdicts |
| `latency_p50_ms` / `latency_p95_ms` | float | operational latency |
| `cost_per_convo` | float | mean cost per case |
| `overall_passed` | bool | AND of all metric `passed` |
| `generated_note` | str | how it was produced (deterministic/live) |

Written to `evals/report.json` (machine) + `evals/report.md` (human), both committed.

## Relationships

```
evals/dataset/*.json → EvalCase[]
   │  (per case)
   ▼
runner: Agent.create(cfg, llm=scripted_from(case.script)) + build_graph(deps).invoke(...)
   │→ RunRecord{result: TurnResult, traces: list[Trace], error}
   ▼
metrics.py  (+ obs.trace.language_fidelity, guardrails.registry.guardrail_summary)
   │→ MetricResult[]  + JudgeVerdict[] (judge.py)
   ▼
report.py → EvalReport → report.json + report.md ; CLI exit = 0 iff overall_passed
```
