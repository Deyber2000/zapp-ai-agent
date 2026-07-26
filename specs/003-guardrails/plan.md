# Implementation Plan: Guardrails Taxonomy & Policy

**Branch**: `003-guardrails` | **Date**: 2026-07-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-guardrails/spec.md`

## Summary

Turn the baseline guardrails from `001` into a full, **layered, configurable** system without breaking
the turn contract. Three mechanisms:

1. **Layered detection** — the existing regex rules become the **deterministic layer**; a new,
   optional **semantic classifier** (LLM-backed, behind an interface, mock in tests) is the second
   layer. They fuse deterministic-first (Principle X): deterministic is authoritative for known
   patterns, either layer flagging acts, and each decision is tagged with the layer that fired. The
   semantic layer is **off by default** (config toggle), so the baseline stays deterministic/cheap and
   every existing `001`/`002` test is unaffected.
2. **Configurable policy** — a `guardrails` config block: the semantic toggle plus per-rule policy
   (`enabled`, `severity`, `action`) applied at registry construction, so rules can be disabled or
   re-tuned without code changes.
3. **Enforcement + eval signals** — `guardrail_in`/`guardrail_out` apply "**most severe action
   governs**" across all decisions; every decision carries `rule`, `category`, `severity`, `action`,
   and `layer` for the `004` precision/recall metric.

**Contract change (deliberate, additive):** `GuardrailDecision` gains `category: str` and
`layer: Literal["deterministic","semantic"] = "deterministic"`, both defaulted so existing decisions
still validate. `001` explicitly delegates the guardrail decision shape to `003`; the
`guardrails.input`/`guardrails.output` lists and existing fields are unchanged, and no `001` test
breaks.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: existing only — `pydantic` v2, the Anthropic adapter (isolated) for the
semantic classifier, LangGraph (isolated). **No new dependencies.**

**Storage**: N/A (stateless guardrails; policy is config).

**Testing**: `pytest` with the mock `LLMClient`; the deterministic layer runs as today; the semantic
layer is scripted per test and off by default.

**Target Platform**: server-side library + CLI (extends the `001` agent core).

**Project Type**: single project.

**Performance Goals**: zero added LLM calls by default (semantic off); at most one classify call per
stage per turn when the semantic layer is enabled.

**Constraints**: deterministic-first (Principle X); fail-safe — a semantic error degrades to the
deterministic layer, never fail-open; a blocked turn returns a safe, schema-valid contract; config-
driven policy; must not break the `001` contract lists or any existing test.

**Scale/Scope**: ~4 input + ~4 output categories; ~10 rules; 1 new module (`semantic.py`), additive
contract fields, a config block, registry/policy wiring, and unit + integration tests.

## Constitution Check

*GATE: passes before Phase 0 and re-checked after Phase 1.*

- **I Scalability** — guardrails are stateless; the semantic call is bounded (one per stage) and
  toggleable. ✅
- **II Modularity** — rules and the semantic classifier plug into the registry; adding/removing a rule
  or swapping the classifier touches one place; nodes/orchestrator unchanged. ✅
- **III Resilience & Security** — this feature *is* the safety envelope; a semantic error degrades to
  deterministic + `needs_review` (never fail-open); blocked turns fail safe. ✅
- **IV Continuous Learning** — rule severity/action and the semantic toggle are config, tunable from
  eval feedback; decisions feed `004` precision/recall. ✅
- **V Future-Proofing** — policy is config; the `SemanticClassifier` interface lets a real moderation
  provider replace the mock without policy changes. ✅
- **VI Spec-Driven & Traceable** — derived from `spec.md`; commits stay spec-before-code. ✅
- **VII Structured Validated Output Contract** — the contract change is additive/backward-compatible;
  the `guardrails.input`/`output` lists and all existing fields are preserved. ✅
- **VIII Guardrails by Default, Fail-Safe** — this feature is Principle VIII: input before processing,
  output before returning, on every turn; most-severe-governs; blocked → safe reply. ✅
- **IX Multilingual Coherence** — safe declines already reply in `active_lang` (via `002` verification);
  guardrail categories are language-agnostic. ✅
- **X Signal Fusion & Deterministic Safety** — deterministic layer is authoritative for known patterns;
  the semantic layer is additive; either flags → act. ✅
- **XI Observability & Eval-Driven Verification** — every decision records rule/category/severity/
  action/layer; one span per guardrail node preserved. ✅

**No violations.** Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-guardrails/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — taxonomy, decision shape, policy config, precedence
├── quickstart.md        # Phase 1 — how to validate US1–US4
├── contracts/
│   └── guardrails.md    # taxonomy + decision shape + registry/classifier/enforcement contracts
└── tasks.md             # Phase 2 — /speckit-tasks (not created here)
```

### Source Code (repository root) — files this feature touches

```text
src/zapp_assist/
├── contracts.py               # + GuardrailDecision.category / .layer (additive, defaulted)
├── config.py                  # + GuardrailsConfig (semantic_enabled + per-rule policy) on AppConfig
├── guardrails/
│   ├── registry.py            # apply policy at load; hold optional SemanticClassifier; tag layer;
│   │                          #   action-precedence helper ("most severe governs")
│   ├── baseline.py            # tag each regex rule with a category; policy-driven enabled/severity/action
│   └── semantic.py            # NEW: SemanticClassifier protocol + LLM-backed impl (mock in tests)
├── graph/nodes/
│   ├── guardrail_in.py        # most-severe-governs; record all; semantic error → degrade + needs_review
│   └── guardrail_out.py       # most-severe-governs (redact/refuse); record all
└── agent.py                   # wire the semantic classifier (from llm + config) into default_registry

config.yaml                    # add the `guardrails` block (semantic_enabled + per-rule policy)

tests/
├── unit/
│   ├── test_guardrail_policy.py     # NEW: config policy (disable/override) + action precedence
│   └── test_semantic_layer.py       # NEW: semantic fusion, layer tagging, degrade-on-error
└── integration/
    └── test_us3_guardrails.py       # NEW: US1 (paraphrase/known/genuine), US2 (output), US3 (config)
```

**Structure Decision**: extend the existing single-project `001` layout in place — one new module
(`semantic.py`), additive contract fields, a config block, registry/policy/enforcement wiring, and new
tests. The `001` contract lists, adapter isolation, and LangGraph isolation are preserved.

## Complexity Tracking

*No constitution violations — no entries.*
