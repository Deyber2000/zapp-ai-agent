# Implementation Plan: Agent Core (tool-calling reasoning loop)

**Branch**: `005-agent-core` · **Spec**: [spec.md](spec.md) · **Status**: Implemented

## Technical Context

- **Language/stack**: Python 3.11+, Pydantic v2, LangGraph (isolated to `graph/build.py`), unchanged.
- **Constraint**: no change to the `TurnResult` contract or the `001`–`004` signals — only the middle
  of the graph (understanding + action selection) is replaced.
- **Provider posture**: structured-output tool selection (the shared `LLMClient.complete(schema=...)`),
  because the OpenAI adapter (the live path) does not wire native function-calling; this keeps the mock
  and both adapters on one code path.

## Design

### The node

`src/zapp_assist/graph/nodes/agent.py` — one node replacing `route_intent`, `action_plan`,
`support_rag`. A bounded ReAct loop (`_MAX_STEPS = 4`):

1. Build the working context: recent history (as context) + the current message.
2. Ask the model for an `AgentStep` (`reasoning`, `tool`, and the fields that tool needs).
3. Dispatch on the tool:
   - `search_kb` → retrieve, feed snippets back, loop (the one genuine multi-step chain);
   - `lookup_order` / `track_order` → answer immediately from the backend (read-only);
   - a state-changing tool → **propose**: verify the order exists (read-only), record a
     `PendingAction(awaiting_confirmation)`, restate, and ask — never execute;
   - `answer` → final grounded reply (`grounded=false` or empty → decline + review);
   - `handoff` → defer to `onboarding` / `smalltalk` / `out_of_scope`, or `clarify` inline.
4. The tool name is normalized (`split("(")[0].strip().lower()`) so a provider echoing a signature
   (`search_kb(query)`) is read robustly — parsing the choice, not refereeing it.

### The graph (build.py)

```
guardrail_in → detect_language → [ _route_after_language ]:
    blocked                              → assemble
    pending action awaiting_confirmation → action_execute        (deterministic HITL gate)
    onboarding slot-fill in progress     → onboarding            (deterministic continuation)
    else                                 → agent
agent → [ _after_agent ]: onboarding | smalltalk | out_of_scope | verify (support/action/clarify)
{onboarding, smalltalk, out_of_scope, action_execute} → verify_reply_language
verify_reply_language → verify_confidence → guardrail_out → assemble → END
```

### Determinism where it belongs (Constitution X)

The refactor does NOT add validators over the model's understanding. It keeps deterministic checks only
at boundaries that are safety-critical and where a lexicon already exists:

- **confirm-before-execute** (`action_execute`, `classify_confirmation`) — the only path to a mutation;
- **bare confirmation → clarify** (`_action.is_bare_confirmation`) — a "yes" reaching the agent with
  nothing pending confirms nothing; forced in code because live testing showed the prompt rule was only
  advisory (the model sometimes re-armed from history);
- **onboarding in progress → onboarding** — an in-flight multi-turn slot-fill continues deterministically
  so a mid-fill contact detail is not re-decided into `update_contact` (which dropped the fused E.164 +
  country).

### Where the deleted nodes' logic moved

| Deleted | Logic now lives in |
| --- | --- |
| `route_intent` (intent classifier) | the agent's tool choice + `_after_agent` handoff routing |
| `action_plan` (extract + propose) | the agent's `_propose` (order verification, ask-for-missing, confirm) |
| `support_rag` (retrieve + answer) | the agent's `search_kb` step + `answer`/decline handling |

## Constitution Check

- **II/V Modularity & one seam per dependency** — LangGraph stays in `build.py`; the agent node is a
  pure `(state, deps) -> state` handler; no vendor code leaks in.
- **X Deterministic-by-default at the boundary** — mutation, confirmation, and slot-fill continuation are
  deterministic; understanding is the model's job, cross-checked only where irreversibility demands it.
- **XI Observability** — the agent emits one span per turn; per-loop LLM cost is recorded via
  `trace.record_llm`. (Per-node/tool timing remains a documented gap.)
- **Config-as-data** — no new hardcoded policy; models/effort/thresholds stay in `config.yaml`.

## Phases

- **Phase 0 — Research**: confirmed native function-calling is not wired in the OpenAI adapter →
  structured-output tool selection chosen. See [research.md](research.md).
- **Phase 1 — Build**: agent node, graph rewiring, deterministic gates.
- **Phase 2 — Migrate tests/eval**: mocks synthesize `AgentStep` from existing scripts; add
  `live_task_success`; refresh the stale decline case.
- **Phase 3 — Verify**: live multi-turn conversations + full gate; reconcile docs.
