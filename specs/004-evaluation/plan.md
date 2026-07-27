# Implementation Plan: Evaluation Suite

**Branch**: `004-evaluation` | **Date**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-evaluation/spec.md`

## Summary

A one-command, CI-ready evaluation suite that runs the agent over a labeled dataset and emits one
report scoring five metric families against configurable thresholds, exiting non-zero on failure. It is
a pure **observer**: it imports the agent (`Agent.create` / the compiled graph) and reads the
`TurnResult` contract + per-turn `Trace`; it changes nothing in `src/zapp_assist/`.

Lives under `evals/` at the repo root (dataset + runner + metrics + judge + report + a committed
`report.json`/`report.md`), with a `zapp-eval` console entry point. Deterministic by default (a
per-case scripted mock model + a rule-based judge → reproducible committed report, no key/network);
`--live` uses the real provider + an LLM judge when `ANTHROPIC_API_KEY` is set.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: existing only — `pydantic` v2, `pyyaml` (eval config), `typer`/`rich` (CLI,
already deps), the agent package. **No new dependencies.**

**Storage**: labeled JSON dataset under `evals/dataset/`; the report is written to `evals/report.json`
+ `evals/report.md` (committed).

**Testing**: `pytest`; eval unit tests live in `tests/` and import `evals`. Deterministic scripted
model — no network.

**Target Platform**: CLI (`zapp-eval`) on Linux/macOS; runs in CI.

**Project Type**: single project — a new top-level `evals/` package alongside `src/zapp_assist/`.

**Performance Goals**: the full deterministic suite runs in seconds (mock model, no network).

**Constraints**: 0 changes to `src/zapp_assist/` and 0 regressions in the 101 existing tests;
deterministic/reproducible committed report (Principle XI); config-driven thresholds; the eval imports
the agent, never the reverse.

**Scale/Scope**: a curated seed dataset (~15–25 labeled cases across capabilities), 5 metric families,
a judge, a report, a CLI, eval config, and unit tests.

## Constitution Check

*GATE: passes before Phase 0 and re-checked after Phase 1.*

- **I Scalability** — the runner is linear over cases; state is per-case (fresh session). ✅
- **II Modularity** — metrics / judge / report / runner / dataset are separate modules; the judge and
  model are injected seams. ✅
- **III Resilience & Security** — an erroring case is recorded as a failure, never aborts the run
  (FR-004); no secrets in the dataset or report. ✅
- **IV Continuous Learning** — the whole feature exists to measure quality and gate regressions;
  thresholds tune from results. ✅
- **V Future-Proofing** — thresholds + dataset are data; the judge is a swappable interface (rule-based
  now, LLM/real-provider later). ✅
- **VI Spec-Driven & Traceable** — derived from `spec.md`; commits stay spec-before-code. ✅
- **VII Structured Validated Output Contract** — consumes the frozen `TurnResult`; the report is itself
  a validated Pydantic model. The agent contract is untouched. ✅
- **VIII Guardrails Fail-Safe** — N/A to the agent (observer); the eval measures guardrail P/R. ✅
- **IX Multilingual Coherence** — measures language fidelity across ES/EN/PT. ✅
- **X Signal Fusion & Deterministic Safety** — deterministic by default (scripted model + rule-based
  judge) so the committed report is reproducible; live mode opt-in. ✅
- **XI Observability & Eval-Driven Verification** — this feature IS Principle XI: it turns the per-turn
  trace + contract into scored, gated metrics. ✅

**No violations.** Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/004-evaluation/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — case/report/metric/threshold schemas
├── quickstart.md        # Phase 1 — how to run + validate
├── contracts/
│   └── eval.md          # dataset schema, metric/judge/report interfaces, CLI contract
└── tasks.md             # Phase 2 — /speckit-tasks (not created here)
```

### Source Code (repository root) — new `evals/` package (agent untouched)

```text
evals/
├── __init__.py
├── models.py           # Pydantic: EvalCase, MockScript, Expected, MetricResult, JudgeVerdict,
│                       #   EvalReport, EvalThresholds
├── scripted_llm.py     # deterministic LLMClient built from a case's MockScript (eval-owned, no
│                       #   dependency on tests/); handles Lang/Intent/Grounded/Onboarding/Action/
│                       #   Safety(SafetyAssessment)/RewrittenReply/Judge schemas by name
├── runner.py           # per case: build Agent.create(config, llm=scripted) + build_graph(deps),
│                       #   invoke turn(s), collect (TurnResult, Trace); returns per-case records
├── metrics.py          # task_success, language_fidelity, guardrail precision/recall, latency
│                       #   p50/p95, cost/convo (reuse obs.trace.language_fidelity +
│                       #   guardrails.registry.guardrail_summary)
├── judge.py            # Judge protocol; RuleBasedJudge (deterministic, default); LLMJudge (opt-in,
│                       #   adapter-backed, 1-5 rubric via structured output)
├── report.py           # assemble EvalReport; write report.json + report.md; overall pass/fail
├── cli.py              # `zapp-eval` (typer): run all → metrics → report → print summary → exit code
├── eval_config.yaml    # thresholds (task_success_min, language_fidelity_min, guardrail_recall_min,
│                       #   guardrail_precision_min, judge_min, latency_p95_max_ms, cost_per_convo_max)
├── dataset/            # labeled JSON cases (support/onboarding/action/out_of_scope/guardrail/multi)
├── report.json         # committed, reproducible
└── report.md           # committed, human-readable

pyproject.toml          # + console script  zapp-eval = evals.cli:app  ; add evals to mypy targets

tests/
└── unit/
    ├── test_eval_metrics.py     # task_success, precision/recall, percentile, fidelity math
    └── test_eval_runner.py      # tiny dataset → report; threshold flip changes exit/overall
```

**Structure Decision**: a NEW top-level `evals/` package that imports the agent and reads its contract
+ trace. The agent (`src/zapp_assist/`) is not modified. The runner obtains the trace by building the
compiled graph directly (`build_graph(agent.deps)` + `invoke`, exactly as the observability test does),
so **no new public API is added to `Agent`**. Eval unit tests live in `tests/` (collected by the
existing pytest config) and import `evals`. `mypy` targets extend to `evals`; `ruff` already covers it.

## Complexity Tracking

*No constitution violations — no entries.*
