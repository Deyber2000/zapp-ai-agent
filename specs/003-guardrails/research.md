# Research: Guardrails Taxonomy & Policy (003)

Phase 0 decisions. Each: **Decision → Rationale → Alternatives considered**. Reuses the `001` guardrail
stack; no new dependencies.

## R1 — Additive `GuardrailDecision` extension (category + layer)

**Decision**: Add two fields to `GuardrailDecision`: `category: str` (the taxonomy category) and
`layer: Literal["deterministic","semantic"] = "deterministic"`. Both defaulted; the existing
`rule`/`action`/`severity`/`detail` fields and `extra="forbid"` are unchanged.

**Rationale**: `001` explicitly delegates "the guardrail taxonomy and how decisions appear in the
contract" to `003`, so enriching the decision shape is this feature's mandate, not a contract violation.
Defaults make it backward-compatible: every existing `001` decision still validates and no test breaks.
Category + layer are exactly what the `004` precision/recall metric needs (FR-013/014).

**Alternatives considered**: (a) *Put category/layer only in the trace* (like `002`'s language signals)
— rejected: guardrail category/layer are part of the decision a caller legitimately consumes, and `001`
delegated the decision shape here. (b) *Encode them in the free-text `detail`* — rejected: unparseable,
defeats automated precision/recall.

## R2 — Semantic layer: optional LLM classifier, off by default, fail-safe

**Decision**: A `SemanticClassifier` interface with an LLM-backed implementation
(`classify(stage, ctx) -> list[GuardrailDecision]` with `layer="semantic"`), toggled by
`guardrails.semantic_enabled` (**default false**). When enabled it runs after the deterministic rules;
on an LLM error/timeout it returns no decisions (degrade to deterministic) and the node flags the turn
`needs_review` — never fail-open.

**Rationale**: The deterministic layer only catches known patterns; a semantic classifier is the
backstop for paraphrased/obfuscated attacks and unusual-phrasing toxicity (US1, SC-001). Off by default
keeps the baseline deterministic, cheap, and reproducible, and means **every existing `001`/`002` test
runs unchanged** (no new LLM calls). Fail-safe degradation satisfies FR-010/SC-005 (Constitution
III/VIII).

**Alternatives considered**: (a) *Always-on semantic* — rejected: adds an LLM call to every turn
(cost/latency) and would perturb existing tests. (b) *A second regex pack instead of a classifier* —
rejected: regex cannot generalize to paraphrase, which is the whole point of the layer. (c) *External
moderation service* — out of scope; the interface is designed so one could replace the mock later.

## R3 — Config-driven policy applied at registry construction

**Decision**: A `guardrails` config block with `semantic_enabled` and a per-rule `policy` map keyed by
rule id: `{enabled, severity, action}`. The registry applies the policy when built — a disabled rule is
not registered; an overridden severity/action replaces the rule's default. Defaults equal today's `001`
values, so with no config the behavior is identical.

**Rationale**: Production guardrails must be tunable without a code redeploy (US3, FR-011/012,
SC-006). Keeping *detection logic* in code and *policy* (enabled/severity/action) in config is the
clean split — the rule still knows *how* to detect; config decides *whether* and *how severely*.

**Alternatives considered**: (a) *Rules fully defined in config (patterns too)* — rejected: regex-in-
YAML is fragile and hard to test. (b) *Hardcoded policy (as `001`)* — rejected: fails the config-driven
requirement.

## R4 — Action precedence: "most severe governs"

**Decision**: Order actions `allow < redact < escalate < refuse`. When multiple rules fire on a turn,
all decisions are recorded, and the **governing action** is the maximum by this order. `guardrail_in`
blocks on `refuse`/`escalate` (escalate also flags review); `guardrail_out` redacts on `redact` and
replaces with a safe decline on `refuse`/`escalate`.

**Rationale**: Deterministic, total ordering makes multi-trigger outcomes unambiguous (FR-009,
edge cases). `refuse` (hard stop) must dominate a mere `redact`.

**Alternatives considered**: severity-based ordering — rejected: action is what governs the *outcome*;
severity is a label. A high-severity `redact` should still only redact, not refuse.

## R5 — Deterministic-first fusion + layer tagging

**Decision**: `registry.run(stage, ctx)` returns deterministic decisions first (tagged
`layer="deterministic"`), then appends semantic decisions (tagged `layer="semantic"`) when enabled.
Decisions are not deduped across layers — both are recorded (the `004` metric wants to see which layer
caught what); the governing action (R4) still decides the outcome. Deterministic is authoritative for
known patterns simply because it always runs and its decision is recorded regardless of the semantic
layer.

**Rationale**: Preserves every signal for evaluation while keeping enforcement unambiguous. Matches
"either layer flagging is enough to act; the record shows which layer fired" (FR-005).

**Alternatives considered**: dedupe by category keeping deterministic — rejected: loses the semantic
recall signal the eval needs.

## R6 — Semantic classifier interface (future-proofing)

**Decision**: `SemanticClassifier` is a small protocol (`enabled: bool`, `classify(stage, ctx) ->
list[GuardrailDecision]`). The shipped implementation calls the existing LLM adapter with a structured
`SafetyAssessment` schema (categories + severity). A real moderation provider can implement the same
protocol with no change to the registry, nodes, or policy.

**Rationale**: Principle V (Future-Proofing) — the moderation backend is a swappable seam, mirroring the
`LLMClient` / `SessionStore` pattern already used elsewhere.

**Alternatives considered**: hardwiring the LLM call into `guardrail_in` — rejected: couples the node to
a specific backend and can't be swapped or unit-tested in isolation.

## Taxonomy (categories → default severity → default action)

| Stage | Category | Rule(s) | Default severity | Default action |
|---|---|---|---|---|
| input | prompt_injection | prompt_injection (regex), semantic | high | refuse |
| input | pii | pii (regex), semantic | medium | redact |
| input | toxicity | abuse (regex), semantic | medium | refuse |
| input | off_topic | off_topic (regex), semantic | low | refuse |
| input | unsafe | semantic | high | refuse |
| output | pii_leak | pii_leak (regex) | medium | redact |
| output | ungrounded | ungrounded (regex) | medium | escalate |
| output | disclosure | policy (regex), semantic | high | refuse |
| output | unsafe | semantic | high | refuse |

Defaults equal the `001` baseline values; all are overridable via `guardrails.policy` in `config.yaml`.
