# Research: Evaluation Suite (004)

Phase 0 decisions. Each: **Decision → Rationale → Alternatives considered**. Reuses the agent + its
signals; no new dependencies.

## R1 — `evals/` is a separate top-level package that only imports the agent

**Decision**: Put the suite in a new `evals/` package at the repo root. It imports `zapp_assist`
(agent, contract, trace, and the reusable `obs.trace.language_fidelity` / `guardrails.registry.
guardrail_summary` helpers) but nothing in `src/zapp_assist/` imports `evals`.

**Rationale**: Keeps the eval a pure observer (Principle XI) and the agent free of test/eval coupling.
The one-way dependency is enforceable by inspection.

**Alternatives considered**: (a) *Put eval code under `src/zapp_assist/evals`* — rejected: ships eval
tooling inside the agent package. (b) *Only in `tests/`* — rejected: the eval is a deliverable
(dataset + runner + committed report), not just a test.

## R2 — The runner gets the `Trace` by building the compiled graph directly

**Decision**: `Agent.run_turn` returns only `TurnResult`. The metrics need the `Trace` (latency,
cost, language-fidelity + guardrail span attrs). The runner builds the compiled graph itself —
`build_graph(agent.deps)` then `invoke({"ts": TurnState(...)})` — reading `final["ts"].trace` and
`final["ts"].result`, exactly as the `001` observability test does. Multi-turn cases reuse one
`Session` across turns (the runner threads it), mirroring `run_turn`'s load/save.

**Rationale**: Gets the trace with **zero changes to `Agent`** (no new public API), honoring
"observer, changes nothing" (FR-014). The graph builder is already a public seam.

**Alternatives considered**: (a) *Add `Agent.run_turn_with_trace`* — rejected: modifies the agent for
the eval's convenience. (b) *Parse the trace from logs* — rejected: brittle; the in-memory trace is
available.

## R3 — Per-case deterministic scripted model, owned by `evals/`

**Decision**: Each case carries a `MockScript` (lang, intent, reply, grounded, citations, normalization
fields, safety findings, judge scores). `evals/scripted_llm.py` builds a deterministic `LLMClient` from
it (dispatching by schema name: LangSignal / IntentSignal / GroundedAnswer / OnboardingExtraction /
ActionRequest / SafetyAssessment / RewrittenReply / the judge schema). It is eval-owned and does **not**
import `tests/`.

**Rationale**: The agent requires an injected model; a per-case script makes the whole run deterministic
and reproducible (so the committed report is stable and CI needs no key/network). Owning it in `evals/`
keeps the deliverable self-contained (a test dependency would be wrong for a shipped tool).

**Alternatives considered**: (a) *Reuse `tests/support/mock_llm`* — rejected: a shipped deliverable
must not depend on the test package. (b) *Record/replay real responses* — rejected: needs a key to
record and is heavier than scripting for a curated seed set.

## R4 — Deterministic-by-default with a rule-based judge; LLM judge opt-in

**Decision**: A `Judge` protocol with two implementations. `RuleBasedJudge` (default, deterministic)
scores the 1–5 rubric (helpfulness, groundedness, safety, language) from observable facts (reply
non-empty & on-topic, grounded flag / citations, no guardrail block, reply language == expected).
`LLMJudge` (opt-in via `--live` + key) asks the adapter for a structured rubric verdict. The committed
report uses `RuleBasedJudge`.

**Rationale**: Satisfies "LLM-as-judge quality with deterministic settings" while keeping the committed
run reproducible and CI keyless (FR-008/011, SC-004). The rubric and the seam are real; the backend is
swappable — mirroring how the agent's model is injected. Consistent with the project-wide "temperature
rejected by current models" note: determinism is structural.

**Alternatives considered**: (a) *LLM judge only* — rejected: non-deterministic + needs a key, so the
committed report wouldn't be reproducible. (b) *No judge* — rejected: the rubric quality dimension is a
required metric.

## R5 — Metric definitions

**Decision**:
- **task_success**: per capability, the observed outcome vs the label — support: grounded reply when
  `grounded` expected / decline (`needs_review` + no invented answer) when not; onboarding: correct
  `final_normalized_text` + `detected_country`; action: confirmation asked before any state change, and
  executed only after confirmation; out_of_scope/guardrail: safe decline / blocked. Rate = matches / cases.
- **language_fidelity**: reply language (via the deterministic detector) == the case's expected
  language, across ES/EN/PT; reuse the trace `reply_match` where present.
- **guardrail precision/recall**: over cases labeled `safe`/`unsafe`. A case is "flagged" if it was
  blocked or recorded a refusing/escalating guardrail decision. TP = unsafe & flagged; FP = safe &
  flagged; FN = unsafe & not flagged. `recall = TP/(TP+FN)`, `precision = TP/(TP+FP)` (reuse
  `guardrail_summary`).
- **latency p50/p95**: percentiles of per-turn `trace.total_latency_ms` across all turns.
- **cost/convo**: mean `trace.cost_usd` summed per conversation (case).

**Rationale**: Each metric is computed from the labels + the signals the agent already emits — objective
and reproducible. Standard precision/recall definitions make the guardrail gate meaningful (SC-003).

**Alternatives considered**: F1 only — kept precision and recall separately so the gate can enforce a
high recall (safety) independently.

## R6 — One report: `report.json` + `report.md`, committed; CLI exit code

**Decision**: `EvalReport` (Pydantic) holds every `MetricResult` (name, score, threshold, passed),
per-capability breakdowns, judge aggregate, latency/cost, and an overall `passed`. `report.py` writes
`evals/report.json` (machine) and `evals/report.md` (human). `zapp-eval` prints the summary and exits
`0` iff `overall.passed`, else non-zero (FR-002/003). Both artifacts are committed and reproduced by a
fresh deterministic run.

**Rationale**: One artifact, two renderings — CI reads the code/JSON, humans read the markdown. A
Pydantic report is itself validated (Principle VII).

**Alternatives considered**: HTML/dashboard — deferred to `005-web-ui` (out of scope here).

## R7 — Config-as-data thresholds

**Decision**: `evals/eval_config.yaml` holds all thresholds (`task_success_min`,
`language_fidelity_min`, `guardrail_recall_min`, `guardrail_precision_min`, `judge_min`,
`latency_p95_max_ms`, `cost_per_convo_max`) loaded into an `EvalThresholds` model with sensible
defaults. Changing a threshold changes pass/fail with no code change (FR-010, SC-006).

**Rationale**: Production evals must be tunable from results without a redeploy (Principle IV/V).

**Alternatives considered**: reuse the agent's `config.yaml` — kept eval thresholds in their own file so
the eval config is self-contained and doesn't couple to the agent's runtime config.

## Determinism & reproducibility note

The committed `report.json`/`report.md` are produced by the default deterministic run (scripted model +
rule-based judge). `Trace.total_latency_ms` is wall-clock and environment-dependent, so the committed
report's **latency values are informational** (used for regression comparison), while all correctness
metrics (task success, fidelity, guardrail P/R, judge) are byte-stable across runs.
