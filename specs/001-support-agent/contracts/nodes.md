# Contract: Graph Nodes & State

Nodes are stateless handlers of the form `node(state: TurnState) -> TurnState` (Scalability,
Modularity). They read/write only `TurnState` and injected dependencies (registries, `LLMClient`,
stores). No node imports LangGraph or the Anthropic SDK; wiring lives only in `graph/build.py`.

## TurnState (threaded through the graph)

```text
TurnState:
  turn_id: str
  session: Session                 # loaded from SessionStore at entry, saved at exit
  user_text: str
  # progressive signals (None until the owning node runs):
  language: LanguageResult | None  # detected_lang, active_lang, lang_confidence
  intent: Intent | None
  normalization: NormalizationSignal | None
  retrieval: list[KnowledgeDocument] | None
  confidence: ConfidenceAssessment | None
  guardrails_in: list[GuardrailDecision]
  guardrails_out: list[GuardrailDecision]
  draft_reply: str | None
  trace: Trace
  result: TurnResult | None        # set by `assemble`
```

## Node responsibilities & edges

| Node | Reads | Writes | Notes |
|------|-------|--------|-------|
| `guardrail_in` | user_text | guardrails_in | On block → jump to `assemble` with a safe reply (FR-019/020). |
| `detect_language` | user_text, session | language, session.active_lang | Fuse deterministic + LLM; lock/fallback baseline (FR-021). |
| `route_intent` | user_text, session | intent | Ambiguous → `clarify`; never route to `action` on ambiguity (FR-003/004). |
| `support_rag` | user_text, retrieval | draft_reply, retrieval, confidence(grounding) | No grounding → decline + `needs_review` (FR-005/006). |
| `action_plan` | user_text, session | session.pending_action, draft_reply | Restate action + params, ask confirmation; no backend change (FR-012). |
| `action_execute` | session.pending_action | draft_reply, session | Execute once only on explicit confirm; else abandon (FR-013). HITL gate. |
| `onboarding` | user_text, session | normalization, session.slots, draft_reply | Slot-fill + normalize (signal fusion); ask only missing field (FR-010/011). |
| `out_of_scope` | user_text | draft_reply | Safe decline in `active_lang` (FR-004/US4). |
| `verify_confidence` | language, retrieval, normalization, intent | confidence, needs_review | Combine signals; divergence/low → `needs_review` (FR-008/016). |
| `guardrail_out` | draft_reply, retrieval | guardrails_out, draft_reply | PII-leak / ungrounded / policy checks; block → safe reply (FR-019/020). |
| `assemble` | all | result | Build + validate `TurnResult`; on any failure substitute safe fallback with `needs_review=true` (FR-002). |

Routing edges after `route_intent`: `support → support_rag`, `onboarding → onboarding`,
`action → action_plan → (confirm?) → action_execute`, `out_of_scope → out_of_scope`,
`clarify → assemble`. All paths converge on `verify_confidence → guardrail_out → assemble`.

## Invariants

- Every path reaches `assemble`; `assemble` always returns a valid `TurnResult` (SC-001/006).
- Each node appends exactly one `Span` to `trace` (ok/error/skipped).
- A node that raises is caught by the graph wrapper, recorded as `error`, and routed to a safe
  degraded outcome — never a crash (FR-018).
