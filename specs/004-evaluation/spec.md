# Feature Specification: Evaluation Suite

**Feature Branch**: `004-evaluation`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "An automated, CI-ready evaluation system: one command runs the agent over
a labeled dataset and produces one report — task success, language fidelity, guardrail precision/recall,
LLM-as-judge quality, latency and cost — with configurable thresholds and a non-zero exit on failure."

## Overview

Specs `001`–`003` were built to emit observable signals (a validated per-turn contract and a per-turn
trace of spans, tokens, cost, latency, language-fidelity, and guardrail decisions). This feature is the
**capstone that consumes them**: a repeatable evaluation suite that runs the agent over a curated,
labeled dataset and reports how well it does — as a single artifact suitable for a CI gate.

One command → one report. The report scores five dimensions against configurable thresholds and the
command exits non-zero if any threshold is missed, so quality regressions fail the build. The suite runs
deterministically by default (so the committed report is reproducible), and can run live when a real
provider key is present.

It **observes** the agent; it does not change the agent, its contract, or any `001`/`002`/`003`
behavior.

## Scope & Boundaries

**In scope**: a labeled evaluation dataset covering the agent's capabilities; a runner that executes the
agent per case and collects the contract + trace; computation of the five metric families (task success,
language fidelity, guardrail precision/recall, LLM-as-judge quality, operational latency/cost); a single
report artifact (machine-readable + human-readable) with per-metric scores and pass/fail; configurable
thresholds and a CI-friendly non-zero exit on failure; a pre-generated report committed to the repo;
deterministic default runs with an optional live mode.

**Out of scope**: a visual dashboard/UI for the report (→ `005-web-ui`); integrating an external eval
platform/service; any change to the agent, its turn contract, or `001`/`002`/`003` behavior; adding
languages beyond ES/EN/PT.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One command, one report, CI gate (Priority: P1)

An engineer runs a single command and gets one report summarizing how the agent performed across the
dataset, with each metric marked pass or fail against a threshold. In CI, the command exits non-zero
when any threshold is missed, so a quality regression fails the build.

**Why this priority**: This is the core deliverable and the minimum viable eval — a repeatable,
one-command quality gate. Without it, none of the individual metrics are actionable.

**Independent Test**: Run the command against the dataset; verify it produces one report (machine- and
human-readable) with a pass/fail per metric and an overall result, and that the process exit code is
zero when all thresholds pass and non-zero when any fails.

**Acceptance Scenarios**:

1. **Given** the evaluation dataset and default thresholds, **When** the command is run, **Then** it
   produces a single report containing every metric with its score and a pass/fail, plus an overall
   pass/fail.
2. **Given** all metrics meet their thresholds, **When** the command finishes, **Then** it exits with a
   success (zero) code.
3. **Given** at least one metric is below its threshold, **When** the command finishes, **Then** it
   exits with a non-zero code and the report identifies which metric(s) failed.

---

### User Story 2 - Capability metrics from labeled data (Priority: P1)

The report measures the agent's actual behavior against labeled expectations: did it succeed at the
task, reply in the right language, and make the right guardrail decisions.

**Why this priority**: These are the substance of the evaluation — task success, language fidelity, and
guardrail precision/recall — computed objectively from the labeled dataset and the signals the agent
emits. They are what the pass/fail gate is really checking.

**Independent Test**: Run the suite over labeled cases and verify each metric is computed correctly:
task success on known-outcome cases, language fidelity across ES/EN/PT, and guardrail precision/recall
on labeled safe/unsafe cases.

**Acceptance Scenarios**:

1. **Given** cases labeled with an expected outcome (grounded answer, decline, correct normalization,
   confirm-before-execute, safe decline), **When** the suite runs, **Then** it reports a task-success
   rate = the share of cases whose outcome matched the label.
2. **Given** cases labeled with an expected language across ES/EN/PT, **When** the suite runs, **Then**
   it reports a language-fidelity rate = the share of replies in the expected language.
3. **Given** cases labeled safe/unsafe, **When** the suite runs, **Then** it reports guardrail
   precision and recall computed from the agent's recorded guardrail decisions versus the labels.

---

### User Story 3 - LLM-as-judge answer quality (Priority: P2)

The report includes an answer-quality score from an LLM judge applying a fixed rubric (helpfulness,
groundedness, safety, language) so that quality — not just pass/fail correctness — is measured.

**Why this priority**: Automated quality judgment on a consistent rubric adds a dimension the objective
metrics can't capture. It depends on the runner (US1) and is a distinct, valuable signal, but secondary
to the objective correctness metrics.

**Independent Test**: Run the judge over a set of replies and verify each receives a 1–5 score per
rubric dimension, aggregated into an average quality score in the report; verify the judge runs
deterministically for the committed report.

**Acceptance Scenarios**:

1. **Given** the agent's replies for the dataset, **When** the judge runs, **Then** each reply gets a
   1–5 score on each rubric dimension and the report includes an aggregate quality score.
2. **Given** the judge runs for the committed report, **When** it is executed again with the same
   inputs, **Then** it yields the same scores (deterministic/reproducible).

---

### User Story 4 - Operational metrics + configurable thresholds + committed report (Priority: P2)

The report includes latency (p50/p95) and estimated cost per conversation, all thresholds are
configuration, and a pre-generated report is committed to the repo so results are visible without
running anything.

**Why this priority**: Operational metrics and tunable thresholds make the eval production-relevant, and
a committed report makes the results reviewable at a glance. Important, but built on the runner and
metrics above.

**Independent Test**: Run the suite and verify the report includes latency p50/p95 and estimated
cost/conversation; change a threshold in configuration and verify the pass/fail outcome changes
accordingly; confirm a pre-generated report exists in the repo.

**Acceptance Scenarios**:

1. **Given** the per-turn traces, **When** the suite runs, **Then** the report includes latency p50 and
   p95 and an estimated cost per conversation.
2. **Given** a threshold changed in configuration, **When** the suite runs, **Then** the pass/fail
   outcome reflects the new threshold with no code change.
3. **Given** the repository, **When** it is inspected, **Then** a pre-generated report artifact is
   present and consistent with a fresh deterministic run.

---

### Edge Cases

- **No provider key present**: the suite still runs fully in deterministic mode (the committed report is
  produced this way); live judging is skipped or uses the deterministic judge.
- **A case errors**: it is recorded as a failure for task success (never crashes the whole run) and the
  report still completes.
- **Empty or partial dataset**: the suite reports honestly (e.g., 0 cases) rather than fabricating
  scores.
- **Divergent labels**: a case labeled unsafe that the agent allows counts against recall; a safe case
  that is blocked counts against precision — both are surfaced.
- **Threshold exactly met**: meeting a threshold counts as a pass (defined boundary).
- **Metric with no applicable cases**: reported as not-applicable rather than a misleading 100%/0%.

## Requirements *(mandatory)*

### Functional Requirements

**Runner & report**
- **FR-001**: The suite MUST run via a single command over the labeled dataset and produce one report.
- **FR-002**: The report MUST be available in a machine-readable form and a human-readable summary, with
  each metric's score and a pass/fail plus an overall pass/fail.
- **FR-003**: The command MUST exit non-zero when any metric is below its configured threshold, and zero
  when all pass (CI gate).
- **FR-004**: A single erroring case MUST NOT abort the run; it MUST be counted as a task-success
  failure and the report MUST still complete.

**Metrics**
- **FR-005**: The suite MUST compute a task-success rate as the share of cases whose observed outcome
  matches the case's labeled expected outcome.
- **FR-006**: The suite MUST compute a language-fidelity rate as the share of replies in each case's
  expected language, across ES/EN/PT.
- **FR-007**: The suite MUST compute guardrail precision and recall from the agent's recorded guardrail
  decisions versus each case's safe/unsafe label.
- **FR-008**: The suite MUST compute an LLM-as-judge quality score on a fixed 1–5 rubric covering
  helpfulness, groundedness, safety, and language.
- **FR-009**: The suite MUST compute latency p50 and p95 and an estimated cost per conversation from the
  per-turn traces.

**Configuration & reproducibility**
- **FR-010**: All pass/fail thresholds MUST be configuration, not hardcoded, and changeable without code
  changes.
- **FR-011**: The suite MUST run deterministically by default (no external provider/network required) so
  the committed report is reproducible; it MUST support an optional live mode when a provider key is
  present.
- **FR-012**: A pre-generated report MUST be committed to the repository and consistent with a fresh
  deterministic run.

**Data & integration**
- **FR-013**: The dataset MUST be labeled, cover the agent's capabilities (support, onboarding, action,
  out-of-scope/guardrails, multilingual), and be stored as data (not code).
- **FR-014**: The suite MUST consume only the signals the agent already emits (the turn contract and the
  per-turn trace) and MUST NOT change the agent, its contract, or `001`/`002`/`003` behavior.

### Key Entities *(include if feature involves data)*

- **Eval Case**: one labeled unit — the input(s), the capability it exercises, and the expected outcome
  (expected task result, expected language, safe/unsafe label).
- **Eval Dataset**: the curated collection of cases covering the agent's capabilities.
- **Metric Result**: a computed metric — its name, score, threshold, and pass/fail.
- **Judge Verdict**: an LLM-as-judge rubric result for a reply (per-dimension 1–5 + notes).
- **Eval Report**: the single artifact aggregating all metric results, the judge scores, operational
  metrics, and the overall pass/fail.
- **Thresholds**: the configured minimum acceptable value per metric.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A single command produces one report covering all five metric families and an overall
  pass/fail, and returns a correct process exit code (zero on all-pass, non-zero on any-fail).
- **SC-002**: On the labeled dataset, task success, language fidelity, and guardrail precision/recall
  are each computed and reported with a value in [0, 1] (or a count) and a pass/fail.
- **SC-003**: Guardrail recall on labeled unsafe cases and precision on labeled safe cases are both
  reported; the gate can enforce a minimum recall (e.g., ≥ 0.9) via configuration.
- **SC-004**: The LLM-as-judge produces a 1–5 score per rubric dimension for every evaluated reply, and
  the committed run is reproducible (identical scores on re-run).
- **SC-005**: The report includes latency p50/p95 and estimated cost per conversation for the run.
- **SC-006**: Changing any threshold in configuration changes the pass/fail outcome on the same data
  with 0 code changes.
- **SC-007**: The suite runs end-to-end with no provider key and no network access, producing the
  committed report deterministically; 0 agent/contract changes are required.

## Assumptions

- The dataset is a curated, representative seed set (tens of cases across capabilities), sufficient to
  demonstrate each metric — not an exhaustive benchmark.
- Deterministic runs use the same mock model seam the test suite uses; the committed report is generated
  in this mode so it is stable and reviewable in CI. Live mode (real provider) is opt-in via a key.
- The LLM-as-judge uses a fixed rubric and deterministic settings; for the committed/CI run it is
  provider-injected deterministically (a scripted/stub judge), mirroring how the agent's model is
  injected in tests. The "temperature 0" intent is realized structurally (fixed rubric + low-variance
  settings), consistent with the project-wide note that current models reject a temperature parameter.
- "Estimated cost per conversation" uses the per-turn token counts and the configured pricing table.
- Default thresholds are sensible starting values (tunable): e.g., task success and language fidelity
  high, guardrail recall high, a minimum average judge score, and latency/cost ceilings.
- Percentile latency (p50/p95) is measured on the deterministic run's timings; absolute values are
  environment-dependent and used for regression comparison, not as universal SLAs.
