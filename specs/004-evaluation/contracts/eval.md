# Contracts: Evaluation Suite (004)

Internal interfaces for `evals/`. The agent's `TurnResult` / `Trace` are consumed read-only; nothing
here changes the agent.

## C1 — Dataset schema (JSON → `EvalCase`)

Each dataset file is a list of case objects validated into `EvalCase` (see data-model §1). Required:
`id`, `capability`, `turns` (≥1), `script` (one `MockScript` or one per turn), `expected`. Invalid
cases fail loading with a clear error (the dataset is data, validated on read).

## C2 — Scripted model (`evals/scripted_llm.py`)

`build_scripted_llm(scripts: list[MockScript]) -> LLMClient` returns a deterministic client
implementing the agent's `LLMClient` protocol. It dispatches by the requested schema's name
(LangSignal, IntentSignal, GroundedAnswer, OnboardingExtraction, ActionRequest, SafetyAssessment,
RewrittenReply) and advances per turn. Unknown schema → a safe degraded result. Eval-owned; no import
of `tests/`.

## C3 — Runner (`evals/runner.py`)

`run_case(case: EvalCase, config) -> RunRecord`: builds `Agent.create(config=config,
llm=build_scripted_llm(case.script...))`, compiles the graph via `build_graph(agent.deps)`, and invokes
each turn over one shared `Session`, capturing `final["ts"].result` and `final["ts"].trace` per turn.
Any exception → `RunRecord(error=...)` (never raises; FR-004). `run_dataset(cases, config) ->
list[RunRecord]`.

## C4 — Metrics (`evals/metrics.py`)

Pure functions over `list[RunRecord]` + `list[EvalCase]` → `MetricResult`:
`task_success`, `language_fidelity`, `guardrail_precision`, `guardrail_recall`, `latency_percentiles`
(p50/p95), `cost_per_conversation`. Reuse `zapp_assist.obs.trace.language_fidelity` and
`zapp_assist.guardrails.registry.guardrail_summary`. Guardrail labeling: a case is *flagged* if
`result` is blocked or any recorded decision action ∈ {refuse, escalate}; TP/FP/FN per data-model §R5.
A metric with no applicable cases → `MetricResult` marked not-applicable (not a misleading 0/1).

## C5 — Judge (`evals/judge.py`)

```
class Judge(Protocol):
    def score(self, case: EvalCase, record: RunRecord) -> JudgeVerdict: ...
```
`RuleBasedJudge` (default, deterministic) derives the 1–5 rubric from observable facts. `LLMJudge`
(opt-in) asks the adapter for a structured `RubricVerdict`. The committed report uses `RuleBasedJudge`.

## C6 — Report (`evals/report.py`)

`build_report(records, cases, verdicts, thresholds) -> EvalReport`; `write_report(report, dir)` emits
`report.json` + `report.md`. `overall_passed = all(m.passed for m in metrics)`.

## C7 — CLI (`zapp-eval`, `evals/cli.py`)

`zapp-eval [--dataset PATH] [--config PATH] [--out DIR] [--live]`:
1. load dataset + thresholds; 2. `run_dataset`; 3. compute metrics + judge; 4. `build_report` +
`write_report`; 5. print the human summary; 6. **exit 0 iff `overall_passed`, else non-zero**.
Default = deterministic (scripted model + RuleBasedJudge); `--live` uses the real provider + `LLMJudge`
when `ANTHROPIC_API_KEY` is set.

## C8 — Compatibility contract

- `evals/` imports `zapp_assist`; `zapp_assist` never imports `evals`.
- The agent, its `TurnResult` contract, and all `001`/`002`/`003` behavior are unchanged; all 101
  existing tests still pass.
- `pyproject.toml` adds the `zapp-eval` console script and extends `mypy` targets to `evals`.
