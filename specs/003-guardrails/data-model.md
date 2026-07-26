# Data Model: Guardrails Taxonomy & Policy (003)

Additive to the `001` contract. The `guardrails.input`/`guardrails.output` lists and existing
`GuardrailDecision` fields are unchanged; two defaulted fields are added; policy lives in config.

## 1. `GuardrailDecision` (extends `contracts.py`, additive)

| Field | Type | Default | Meaning |
|---|---|---|---|
| `rule` | str | — | the rule id that fired (existing) |
| `action` | Literal[allow, refuse, redact, escalate] | — | action taken (existing) |
| `severity` | Literal[low, medium, high] | — | severity (existing) |
| `detail` | str \| None | None | human note (existing) |
| **`category`** | str | `"policy"` | **NEW** taxonomy category (see taxonomy below) |
| **`layer`** | Literal[deterministic, semantic] | `"deterministic"` | **NEW** which layer detected it |

`model_config = ConfigDict(extra="forbid")` is kept. Defaults make every existing `001` decision (which
sets only rule/action/severity/detail) valid unchanged.

## 2. Taxonomy (categories per stage)

- **Input**: `prompt_injection`, `pii`, `toxicity`, `off_topic`, `unsafe`.
- **Output**: `pii_leak`, `ungrounded`, `disclosure`, `unsafe`.

Each `001` regex rule is tagged with its category (see research.md taxonomy table); the semantic layer
emits decisions in the same categories with `layer="semantic"`.

## 3. Guardrails policy config (`config.py::GuardrailsConfig` + `config.yaml`)

```text
guardrails:
  semantic_enabled: false          # toggle the semantic layer (default off)
  policy:                          # per-rule overrides, keyed by rule id
    <rule_id>:
      enabled: true                # false → the rule is not registered
      severity: low|medium|high    # overrides the rule default
      action: allow|redact|refuse|escalate   # overrides the rule default
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `semantic_enabled` | bool | `false` | run the semantic layer in addition to deterministic |
| `policy` | dict[str, RulePolicy] | `{}` | per-rule overrides; absent rule → its code defaults |
| `RulePolicy.enabled` | bool | `true` | register the rule or not |
| `RulePolicy.severity` | str \| None | None | override severity |
| `RulePolicy.action` | str \| None | None | override action |

With an empty `guardrails` block, behavior equals the `001` baseline.

## 4. Action precedence ("most severe governs")

Total order: `allow (0) < redact (1) < escalate (2) < refuse (3)`. The **governing action** of a turn is
the maximum over all recorded decisions for the stage.

- input: governing ∈ {refuse, escalate} → `blocked`; escalate → also `needs_review_override`.
- output: `redact` present → mask PII spans; governing ∈ {refuse, escalate} → replace with safe decline
  + `needs_review`.

## 5. Semantic layer (transient; not stored)

- `SemanticClassifier`: `enabled: bool`; `classify(stage, ctx) -> list[GuardrailDecision]` (layer
  `"semantic"`). LLM-backed via a `SafetyAssessment` schema (categories + severity).
- On LLM error/degraded → returns `[]`; the node records this as a degrade and sets
  `needs_review_override` (never fail-open).

## Relationships

```
GuardrailRegistry (built with policy + optional SemanticClassifier)
  ├─ deterministic rules (baseline.py, tagged category, layer=deterministic)
  └─ semantic classifier (semantic.py, layer=semantic) — only if semantic_enabled
        │
        ▼  run(stage, ctx)
  list[GuardrailDecision]  (all layers, all fired rules)
        │
        ▼  guardrail_in / guardrail_out
  governing action (most severe) → enforce (block / redact / safe-decline)
  all decisions → contract guardrails.input / guardrails.output  →  004 precision/recall
```
