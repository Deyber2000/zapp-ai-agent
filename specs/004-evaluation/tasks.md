# Tasks: Evaluation Suite

**Input**: Design documents from `/specs/004-evaluation/`

**Prerequisites**: plan.md, spec.md (required); research.md, data-model.md, contracts/eval.md,
quickstart.md (available)

**Tests**: Included — the spec's per-story Independent Tests and measurable SCs, plus Constitution XI
(eval-driven verification).

**Organization**: Grouped by user story. A new top-level `evals/` package that **imports the agent and
reads its `TurnResult` + `Trace`** — **0 changes to `src/zapp_assist/`**; all 101 existing tests must
keep passing. Deterministic by default (per-case scripted model + rule-based judge).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 (user-story phases only)
- Agent code = `src/zapp_assist/` (read-only here); eval code = `evals/`; eval tests = `tests/`.

---

## Phase 1: Foundational (blocking prerequisites for all user stories)

- [ ] T001 [P] Scaffold the `evals/` package (`evals/__init__.py`); add the `zapp-eval = evals.cli:app` console script to `pyproject.toml` and extend the mypy targets to cover `evals`
- [ ] T002 [P] Implement eval models in `evals/models.py` — `MockScript`, `Expected`, `EvalCase`, `RunRecord`, `MetricResult`, `JudgeVerdict`, `EvalThresholds`, `EvalReport` (per data-model.md)
- [ ] T003 [P] Add `evals/eval_config.yaml` (thresholds) + a loader that reads it into `EvalThresholds` with defaults
- [ ] T004 [US1] Implement `evals/scripted_llm.py` — `build_scripted_llm(scripts)` returns a deterministic `LLMClient` dispatching by schema name (Lang/Intent/Grounded/Onboarding/Action/Safety/Rewritten), advancing per turn; eval-owned, no `tests/` import (depends on T002)
- [ ] T005 [US1] Implement `evals/runner.py` — `run_case` (build `Agent.create` + `build_graph(deps).invoke` over one shared `Session`, capture `TurnResult` + `Trace` per turn; exception → `RunRecord(error=...)`, never aborts) and `run_dataset` (depends on T002, T004)

**Checkpoint**: models, config, scripted model, and the runner exist; a case can be executed to a
`RunRecord` with its trace.

---

## Phase 2: User Story 1 — One command → one report + CI gate (Priority: P1) 🎯 MVP

**Goal**: a single command runs the dataset and emits one report with per-metric + overall pass/fail
and a correct process exit code.

**Independent Test**: run the command over the dataset → one report (json + md), pass/fail per metric +
overall; exit 0 on all-pass, non-zero on any fail; an erroring case doesn't abort the run.

### Tests for User Story 1

- [ ] T006 [P] [US1] Unit test the runner over a tiny in-test dataset: produces `RunRecord`s with a `TurnResult` + trace; an intentionally-erroring case is isolated (error recorded, run completes) in `tests/unit/test_eval_runner.py`
- [ ] T007 [P] [US1] Unit test that a threshold change flips the overall pass/fail and the CLI exit code on the same records in `tests/unit/test_eval_runner.py`

### Implementation for User Story 1

- [ ] T008 [US1] Implement `evals/metrics.py::task_success(records, cases) -> MetricResult` (observed outcome vs expected per capability) (depends on T005)
- [ ] T009 [US1] Implement `evals/report.py` — `build_report(...) -> EvalReport` + `write_report` (writes `evals/report.json` + `evals/report.md`); `overall_passed = all metric.passed` (depends on T002, T008)
- [ ] T010 [US1] Implement `evals/cli.py` (`zapp-eval`, typer) — load dataset + thresholds → `run_dataset` → task_success → build/write report → print summary → exit 0/non-zero (depends on T008, T009)
- [ ] T011 [P] [US1] Seed `evals/dataset/` with a few labeled support cases (grounded + no-grounding decline) sufficient to run end-to-end

**Checkpoint**: `uv run zapp-eval` produces one report with task success + a CI exit code — MVP works;
0 changes to `src/zapp_assist`; 101 tests still green.

---

## Phase 3: User Story 2 — Capability metrics from labeled data (Priority: P1/P2)

**Goal**: language fidelity (ES/EN/PT) and guardrail precision/recall added to the report.

**Independent Test**: over labeled cases, language-fidelity and guardrail precision/recall are computed
correctly from the emitted signals vs labels.

### Tests for User Story 2

- [ ] T012 [P] [US2] Unit test the metric math on synthetic records: `language_fidelity`, guardrail `precision`/`recall` (TP/FP/FN), and not-applicable handling in `tests/unit/test_eval_metrics.py`

### Implementation for User Story 2

- [ ] T013 [US2] Implement `evals/metrics.py::language_fidelity` (reuse `obs.trace.language_fidelity` + expected lang) and `guardrail_precision`/`guardrail_recall` (reuse `guardrails.registry.guardrail_summary` + safe/unsafe labels) (depends on T008)
- [ ] T014 [US2] Expand `evals/dataset/` with multilingual (ES/EN/PT), guardrail (labeled safe/unsafe, incl. a semantic-on paraphrase), onboarding, action (multi-turn HITL), and out-of-scope cases (depends on T011)
- [ ] T015 [US2] Wire the new metrics into `build_report` + the CLI summary (depends on T013, T009)

**Checkpoint**: report includes task success, language fidelity, and guardrail precision/recall.

---

## Phase 4: User Story 3 — LLM-as-judge answer quality (Priority: P2)

**Goal**: a 1–5 rubric quality score per reply, aggregated into the report; deterministic for the
committed run.

**Independent Test**: the rule-based judge scores each dimension 1–5 deterministically; the aggregate
quality appears in the report.

### Tests for User Story 3

- [ ] T016 [P] [US3] Unit test `RuleBasedJudge`: 1–5 per rubric dimension from observable facts; deterministic (same input → same scores) in `tests/unit/test_eval_judge.py`

### Implementation for User Story 3

- [ ] T017 [US3] Implement `evals/judge.py` — `Judge` protocol, `RuleBasedJudge` (deterministic default), `LLMJudge` (opt-in, adapter-backed, structured rubric) (depends on T002)
- [ ] T018 [US3] Wire judge verdicts + an aggregate quality `MetricResult` (judge_min) into `build_report` + CLI (depends on T017, T009)

**Checkpoint**: report includes an answer-quality score; committed run uses the deterministic judge.

---

## Phase 5: User Story 4 — Ops metrics + config + committed report (Priority: P2/P3)

**Goal**: latency p50/p95 + cost/conversation in the report, config-driven thresholds, and a committed
reproducible report.

**Independent Test**: report includes latency p50/p95 + cost/convo; a threshold change flips pass/fail;
a committed report exists matching a fresh deterministic run.

### Tests for User Story 4

- [ ] T019 [P] [US4] Unit test `latency_percentiles` (p50/p95) and `cost_per_conversation` math on synthetic traces in `tests/unit/test_eval_metrics.py`

### Implementation for User Story 4

- [ ] T020 [US4] Implement `evals/metrics.py::latency_percentiles` + `cost_per_conversation`; wire into `build_report` + CLI (depends on T008)
- [ ] T021 [US4] Generate and COMMIT `evals/report.json` + `evals/report.md` from a deterministic `uv run zapp-eval` (depends on T015, T018, T020)

**Checkpoint**: all five metric families in the report; thresholds config-driven; committed report present.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T022 [P] Add an "Evaluation" section to `README.md` (one command, the five metrics, CI gate, committed report, live mode)
- [ ] T023 Run the full gate — `ruff check .`, `mypy src evals`, `pytest` — confirm **0 changes to `src/zapp_assist`** and 0 regressions in the 101 existing tests; execute the `quickstart.md` validations
- [ ] T024 [P] Config-as-data + boundary audit: thresholds are config-driven; `evals` imports `zapp_assist` only (one-way, no reverse import); no secrets in dataset/report

---

## Dependencies & execution order

- **Foundational (Phase 1)** blocks all. T001/T002/T003 are `[P]`; T004 depends on T002; T005 on T002+T004.
- **US1 (P1)** depends on Foundational → the MVP (task success + report + CLI + exit).
- **US2** depends on US1's metrics/report scaffold (adds fidelity + guardrail P/R + dataset breadth).
- **US3** depends on the runner + report (adds the judge).
- **US4** depends on the metrics + judge (ops metrics + committed report).
- **Polish** depends on all.

## Parallel execution examples

- Foundational: T001, T002, T003 in parallel (packaging vs models vs config).
- US1: T006/T007 (tests) and T011 (dataset seed) alongside the metric/report/CLI implementation.
- US2's metric math test (T012) can be written in parallel with US1's report wiring.

## Implementation strategy

- **MVP = Foundational + User Story 1**: the end-to-end pipeline (dataset → runner → task success →
  one report → CI exit). Deliver and verify (0 agent changes, 101 tests green) before US2.
- Then increment US2 → US3 → US4, committing each on `004-evaluation`, keeping the gate green and
  `src/zapp_assist` untouched. US4 ends by committing the reproducible `report.json`/`report.md`.
