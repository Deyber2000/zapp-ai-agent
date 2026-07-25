# Phase 1 Data Model: Support Agent (Zapp Assist Core)

Entities are Pydantic v2 models unless noted. Field names in the turn contract match the assessment
brief exactly. Validation rules trace to the FRs in `spec.md`.

## TurnResult — the canonical output contract (FR-001, FR-002)

The single object every turn returns. See `contracts/agent-turn.md` for the JSON shape and examples.

| Field | Type | Rules |
|-------|------|-------|
| `reply` | `str` | Non-empty; in `active_lang`. |
| `detected_lang` | `str` | ISO 639-1 (2 letters). |
| `active_lang` | `str` | ISO 639-1; equals the language of `reply`. |
| `lang_confidence` | `float` | 0.0–1.0. |
| `final_normalized_text` | `str` | LLM + deterministic-tool fused value (may equal the raw text when no normalization applies). |
| `detected_country` | `str \| null` | ISO 3166-1 alpha-2 or null. |
| `confidence_score` | `float` | 0.0–1.0; combined language + grounding + fusion + intent signal. |
| `needs_review` | `bool` | True on low confidence, signal divergence, guardrail block, or degraded/fallback turn. |
| `guardrails` | `Guardrails` | `{ input: list[GuardrailDecision], output: list[GuardrailDecision] }`. |

Invariant: constructing `TurnResult` performs schema validation; `assemble` never returns on failure —
it substitutes a safe fallback `TurnResult` with `needs_review=true`.

## Guardrails / GuardrailDecision (FR-019, FR-020; taxonomy in 003)

| Entity | Fields |
|--------|--------|
| `Guardrails` | `input: list[GuardrailDecision]`, `output: list[GuardrailDecision]` |
| `GuardrailDecision` | `rule: str` (id), `action: Literal["allow","refuse","redact","escalate"]`, `severity: Literal["low","medium","high"]`, `detail: str \| null` |

## Session (FR-014, FR-015)

Conversation-scoped state, held behind `SessionStore`.

| Field | Type | Rules |
|-------|------|-------|
| `session_id` | `str` | Stable per conversation. |
| `active_lang` | `str \| null` | Locked after first confident detection; switch policy in `002`. |
| `slots` | `dict[str, SlotValue]` | Collected onboarding fields. |
| `pending_action` | `PendingAction \| null` | Set when an action awaits confirmation. |
| `history` | `list[TurnRef]` | Bounded recent turns for coherence. |

## Intent (FR-003, FR-004)

`Literal["support", "onboarding", "action", "out_of_scope", "clarify"]`. `clarify` is emitted when
intent is ambiguous (no state-changing action on ambiguity).

## NormalizationSignal — signal fusion (FR-007, FR-008, FR-009)

| Field | Type | Notes |
|-------|------|-------|
| `raw` | `str` | User-provided value. |
| `canonical` | `str \| null` | Deterministic normalized form (e.g. E.164). |
| `country` | `str \| null` | ISO 3166-1 alpha-2 derived deterministically. |
| `valid` | `bool` | From the deterministic tool. |
| `llm_value` | `str \| null` | The LLM's interpretation. |
| `agrees` | `bool` | canonical vs llm_value agreement → confidence contribution. |

Fusion: `final_normalized_text`/`detected_country` take the deterministic `canonical`/`country` when
present; `agrees=false` lowers `confidence_score` and sets `needs_review`.

## ConfidenceAssessment (FR-016)

| Field | Type | Notes |
|-------|------|-------|
| `score` | `float` | Combined 0.0–1.0. |
| `components` | `dict[str, float]` | `{language, grounding, fusion, intent}` contributors. |
| `reasons` | `list[str]` | Human-readable drivers (feeds review + `004`). |

## PendingAction — HITL (FR-012, FR-013)

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | e.g. `reschedule_delivery`, `cancel_order`. |
| `params` | `dict` | Validated against the tool's strict schema. |
| `status` | `Literal["awaiting_confirmation","confirmed","executed","abandoned"]` | Execute only from `confirmed`; execute at most once. |

## KnowledgeDocument (FR-005, FR-006)

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Stable id (cited in grounded answers). |
| `title` | `str` | |
| `text` | `str` | Body indexed by BM25. |
| `lang` | `str` | Source language of the doc. |

## Trace / Span — observability (FR-022)

| Entity | Fields |
|--------|--------|
| `Trace` | `turn_id`, `session_id`, `spans: list[Span]`, `total_latency_ms`, `tokens: {input,output,cache_read}`, `cost_usd` |
| `Span` | `node: str`, `latency_ms: float`, `status: Literal["ok","error","skipped"]`, `attrs: dict` |

## TurnState — graph state (internal)

The mutable object threaded through the LangGraph nodes; see `contracts/nodes.md`. Holds the input
text, the `Session`, intermediate signals (language, intent, normalization, retrieval, confidence,
guardrail decisions), the `Trace`, and the building `TurnResult`. Not part of the external contract.
