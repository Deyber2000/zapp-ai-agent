# Tasks: Guardrails Taxonomy & Policy

**Input**: Design documents from `/specs/003-guardrails/`

**Prerequisites**: plan.md, spec.md (required); research.md, data-model.md, contracts/guardrails.md,
quickstart.md (available)

**Tests**: Included — the spec's per-story "Independent Test" criteria and measurable Success Criteria,
plus Constitution VIII/X/XI (guardrails, deterministic safety, eval signals).

**Organization**: Grouped by user story. Builds on the `001` guardrail stack — the deterministic layer
is `001`'s regex rules; the `guardrails.input`/`guardrails.output` contract lists are unchanged (the
decision shape is extended additively). **Every existing `001`/`002` test must keep passing**, and with
the default config the deterministic behavior is byte-for-byte `001`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 (user-story phases only)
- All paths relative to the repo root; single Python project (`src/zapp_assist/`, `tests/`).

---

## Phase 1: Foundational (blocking prerequisites for all user stories)

- [ ] T001 [P] Extend `GuardrailDecision` additively: `category: str = "policy"` and `layer: Literal["deterministic","semantic"] = "deterministic"` (keep `extra="forbid"` and existing fields) in `src/zapp_assist/contracts.py`
- [ ] T002 [P] Add `GuardrailsConfig` (`semantic_enabled: bool = False`, `policy: dict[str, RulePolicy] = {}`, `RulePolicy{enabled=True, severity=None, action=None}`) to `AppConfig` in `src/zapp_assist/config.py` and a `guardrails:` block in `config.yaml` (defaults = 001 baseline)
- [ ] T003 Tag each baseline regex rule with its taxonomy `category` and `layer="deterministic"`, and construct decisions with policy-overridable severity/action in `src/zapp_assist/guardrails/baseline.py` (depends on T001)
- [ ] T004 Registry: apply policy at construction (skip disabled rules; override severity/action) and add `governing_action(decisions)` precedence helper (`allow<redact<escalate<refuse`) in `src/zapp_assist/guardrails/registry.py` (depends on T001, T002)

**Checkpoint**: additive contract, config policy, tagged deterministic rules, and precedence exist;
default config reproduces 001 behavior.

---

## Phase 2: User Story 1 — Layered detection (semantic layer) (Priority: P1) 🎯 MVP

**Goal**: catch obfuscated/paraphrased attacks the regex misses, deterministic-first, without
over-blocking genuine turns.

**Independent Test**: known-pattern attack → refused by deterministic regardless of the toggle;
paraphrased attack (semantic on) → refused by semantic; genuine trigger-like support turn → allowed.

### Tests for User Story 1

- [ ] T005 [P] [US1] Unit test the semantic layer: classify returns `layer="semantic"` decisions in the taxonomy categories; a degraded/erroring classifier returns `[]` and signals degrade (never raises) in `tests/unit/test_semantic_layer.py`
- [ ] T006 [P] [US1] Integration test: known injection → refused, decision `layer=deterministic`; paraphrased injection (semantic on) → refused, `layer=semantic`; genuine trigger-like support turn → allowed (no false block) in `tests/integration/test_us3_guardrails.py`

### Implementation for User Story 1

- [ ] T007 [US1] Implement `SemanticClassifier` protocol + `LLMSemanticClassifier` (`SafetyAssessment` structured schema → category/severity → `GuardrailDecision(layer="semantic")`; never raises; `enabled` from config) in `src/zapp_assist/guardrails/semantic.py` (depends on T001)
- [ ] T008 [US1] Registry: hold an optional `SemanticClassifier`; `run(stage, ctx)` returns deterministic decisions then semantic decisions when enabled (no cross-layer dedupe) in `src/zapp_assist/guardrails/registry.py` (depends on T004, T007)
- [ ] T009 [US1] `guardrail_in`: apply `governing_action` (most severe → blocked/needs_review), record all decisions; if the semantic layer was enabled but degraded, set `needs_review_override` (never fail-open) in `src/zapp_assist/graph/nodes/guardrail_in.py` (depends on T008)
- [ ] T010 [US1] Wire the semantic classifier (built from `llm` + config) into `default_registry` in `src/zapp_assist/guardrails/baseline.py` / `src/zapp_assist/agent.py` (depends on T007, T008)

**Checkpoint**: US1 works — layered detection catches known + paraphrased attacks; MVP demonstrable;
001 tests green with the default config.

---

## Phase 3: User Story 2 — Output protection (Priority: P2)

**Goal**: never return PII, unsafe, or disclosure content — redact or replace before returning.

**Independent Test**: reply with PII → redacted + recorded; reply that discloses internal instructions
→ replaced with a safe decline + `needs_review`; blocked/redacted output → valid contract, safe content.

### Tests for User Story 2

- [ ] T011 [P] [US2] Integration test: PII-in-output redacted before return (`guardrails.output` records `pii_leak`); disclosure reply → safe decline + `needs_review`; offending content never returned in `tests/integration/test_us3_guardrails.py`

### Implementation for User Story 2

- [ ] T012 [US2] `guardrail_out`: apply `governing_action` across output decisions (redact → mask PII; refuse/escalate → safe decline template + `needs_review`), record all, never emit offending content in `src/zapp_assist/graph/nodes/guardrail_out.py` (depends on T004)

**Checkpoint**: US1 + US2 — both sides of the envelope enforce with most-severe-governs.

---

## Phase 4: User Story 3 — Configurable policy (Priority: P2)

**Goal**: tune the safety posture from config — disable a rule, change action/severity, toggle semantic —
with no code change.

**Independent Test**: disable a rule → it no longer fires; change an action (redact→refuse) → new action
governs; toggle semantic off → only deterministic runs.

### Tests for User Story 3

- [ ] T013 [P] [US3] Unit test: a disabled rule does not fire; an overridden action/severity is applied; `governing_action` precedence; `semantic_enabled=false` runs no semantic layer in `tests/unit/test_guardrail_policy.py`

### Implementation for User Story 3

- [ ] T014 [US3] Confirm the policy path is fully wired end-to-end (registry applies enable/disable + overrides from T004; the semantic toggle from T008) and add any missing config plumbing; validate via an `AppConfig` with a `guardrails` block in `src/zapp_assist/guardrails/registry.py` (depends on T004, T008)

**Checkpoint**: US1–US3 — policy is entirely config-driven, no code change needed to re-tune.

---

## Phase 5: User Story 4 — Guardrail eval signals (Priority: P3)

**Goal**: every decision exposes rule/category/severity/action/layer so `004` can compute precision/recall.

**Independent Test**: any turn's decisions expose all five fields; a labeled set yields computable
precision/recall inputs.

### Tests for User Story 4

- [ ] T015 [P] [US4] Unit test: recorded decisions expose rule, category, severity, action, and layer; a helper flattens a turn's guardrail decisions for aggregation in `tests/unit/test_guardrail_signals.py`

### Implementation for User Story 4

- [ ] T016 [US4] Add a small reader helper to flatten/summarize guardrail decisions (per stage/category/layer) from a `TurnResult` for the `004` suite in `src/zapp_assist/guardrails/registry.py` (depends on T001)

**Checkpoint**: all four stories functional; guardrail signals available to evaluation.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T017 [P] Update the README to describe the layered guardrail system (deterministic + semantic, config policy) in `README.md`
- [ ] T018 Run the full gate — `ruff check .`, `mypy src`, `pytest` (001 + 002 + 003) — confirm **0 regressions** and execute the `quickstart.md` validations
- [ ] T019 [P] Config-as-data audit: severity/action/enabled and the semantic toggle are config-driven; no hardcoded policy in nodes; taxonomy categories centralized

---

## Dependencies & execution order

- **Foundational (Phase 1)** blocks every user story. T001, T002 are `[P]`; T003 depends on T001;
  T004 depends on T001+T002.
- **US1 (P1)** depends on Foundational → the MVP. Ship/verify before US2.
- **US2 (P2)** depends on Foundational (governing_action); independent of US1 (different node file).
- **US3 (P2)** depends on Foundational + US1 (semantic toggle).
- **US4 (P3)** depends on US1 (the `layer` field being populated).
- **Polish (Phase 6)** depends on all stories.

## Parallel execution examples

- Foundational: T001, T002 in parallel (contract vs config).
- US1: T005 (semantic unit test) and T006 (integration test) alongside each other before implementation.
- US2's node change (T012) can proceed in parallel with US1's semantic module (T007) — different files.

## Implementation strategy

- **MVP = Foundational + User Story 1** (layered detection): the additive contract + config policy +
  the semantic layer, the P1 security improvement over `001`. Deliver and verify it (gate green, 001
  behavior preserved by default) before US2.
- Then increment US2 → US3 → US4, committing each as its own increment on `003-guardrails`, keeping the
  gate green and the `001` contract lists + tests intact at every step.
