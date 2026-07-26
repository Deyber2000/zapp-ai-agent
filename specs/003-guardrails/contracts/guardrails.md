# Contracts: Guardrails Taxonomy & Policy (003)

Internal interface contracts. The external `001` turn contract is extended only additively (§C1).

## C1 — `GuardrailDecision` (additive contract change)

Adds `category: str = "policy"` and `layer: Literal["deterministic","semantic"] = "deterministic"`.
Existing fields and `extra="forbid"` unchanged; existing `001` decisions validate unchanged. The
`guardrails.input`/`guardrails.output` lists on `TurnResult` are the same lists as `001`.

## C2 — `SemanticClassifier` (NEW interface)

```
class SemanticClassifier(Protocol):
    enabled: bool
    def classify(self, stage: str, ctx: GuardrailContext) -> list[GuardrailDecision]: ...
```

- Returns 0..n decisions with `layer="semantic"`, categories drawn from the taxonomy, each with a
  severity/action (from policy defaults for that category).
- The shipped `LLMSemanticClassifier` calls the existing adapter with a structured `SafetyAssessment`
  schema; **never raises** — on error/degraded it returns `[]` and signals a degrade to the caller.
- A real moderation provider implements the same protocol; the registry/nodes are unchanged.

## C3 — `GuardrailRegistry` (behavior change, compatible surface)

- Built from the guardrails **policy** (enable/disable + severity/action overrides applied to the
  deterministic rules) and an optional `SemanticClassifier`.
- `run(stage, ctx) -> list[GuardrailDecision]`: deterministic decisions first, then semantic decisions
  when `semantic.enabled`. All fired decisions are returned (no cross-layer dedupe).
- `governing_action(decisions) -> str`: the most-severe action by precedence `allow < redact <
  escalate < refuse`.

## C4 — `guardrail_in` / `guardrail_out` (behavior change, same signature)

- **guardrail_in**: run input stage; record all in `guardrails_in`; if `governing_action ∈
  {refuse, escalate}` → `blocked=True`; `escalate` → `needs_review_override`. If the semantic layer was
  enabled but degraded, set `needs_review_override` (conservative).
- **guardrail_out**: run output stage on `draft_reply`; record all in `guardrails_out`; `redact` present
  → mask PII spans; `governing_action ∈ {refuse, escalate}` → replace reply with the safe decline
  template + `needs_review`.
- Both keep the fail-safe boundary: the offending content is never returned; `assemble` always yields a
  valid contract.

## C5 — Configuration contract

- `AppConfig.guardrails: GuardrailsConfig` with `semantic_enabled: bool = False` and
  `policy: dict[str, RulePolicy] = {}` (`RulePolicy{enabled=True, severity=None, action=None}`).
- Empty/absent block → identical to `001` baseline behavior.

## C6 — Compatibility contract

- `TurnResult` field set is unchanged; `guardrails.input`/`output` remain lists of `GuardrailDecision`.
- Existing `001` guardrail tests (rule ids, block/redact behavior) MUST still pass; new decision fields
  are additive with defaults.
- Deterministic layer default policy = `001` values, so with the default config the deterministic
  behavior is byte-for-byte the `001` behavior.
