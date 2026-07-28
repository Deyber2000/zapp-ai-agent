# Feature Specification: Agent Core (tool-calling reasoning loop)

**Feature Branch**: `005-agent-core`

**Created**: 2026-07-28

**Status**: Implemented (retroactive spec — documents a refactor validated live before it was specced;
that gap is called out honestly here rather than hidden).

**Input**: Live testing of `001`–`004` surfaced a class of defect the scripted tests could not: the
turn's *understanding* was split across two blind LLM calls — an intent router and an action planner —
each re-reading prose history with a "carry the earlier action forward" instruction. History could
therefore **supply** an action the user never asked for. Replace the router+planner with a single
tool-calling agent, keeping every observable contract and the deterministic confirm-before-execute gate.

## Overview

`001`–`003` built the agent and its signals; `004` evaluates them. This feature changes the *middle* of
the turn — how the agent decides what to do — without changing the turn contract, the language/guardrail
layers, or the evaluation signals.

The old middle was three LLM nodes: `route_intent` (classify into an intent), `action_plan` (extract an
action + params), and `support_rag` (retrieve + answer). Two independent calls each read prose history,
so "action-ness" compounded: a question inherited `action` from prior turns, and a contentless "yes"
inherited a whole `cancel_order` from history.

The new middle is one node, `agent`: a bounded tool-calling loop where the model reasons over the
**current message** (history is context, never an action source) and chooses a tool. The correctness
bet is architectural, not a pile of validators: the **only** path to a backend mutation is
`action_execute`, reached only when a pending action already awaits an explicit confirmation. So a
question — or a bare "yes" with nothing pending — cannot execute anything.

This is the second architectural change to ship without a spec written first (`002` clarify was the
other). The spec is written now so the decision is recorded against the constitution rather than left
implicit in a diff.

## User Scenarios & Testing

### US1 — A question is answered, never actioned
A user who has just performed several actions asks *"can I close my account permanently?"*. The agent
answers from the knowledge base (self-service flow, 14-day grace) and arms nothing. **Test**: after
action-shaped turns, the account-closure question yields `intent=support`, `pending_action=null`, and a
reply that is not a confirmation prompt. (`tests/integration/test_agent_core.py`.)

### US2 — A contentless acknowledgement executes nothing
After a completed cancel, the user types *"yes go ahead"* with nothing pending. The agent asks for
clarification; no action is armed or executed. **Test**: bare "yes" with an empty pending slot →
`state_changes` unchanged, `pending_action=null`.

### US3 — A state change is proposed, confirmed, then executed exactly once
*"cancel order A1001"* → the agent proposes and asks to confirm (no mutation). The next *"yes"* routes
straight to the deterministic executor and cancels exactly once. A decline or an ambiguous answer never
mutates. **Test**: the propose→confirm→execute and propose→decline paths.

### US4 — A multi-turn onboarding fills its slots and stays in onboarding
Providing contact details mid-onboarding continues the onboarding flow (fused E.164 + country),
never a state-changing `update_contact`. **Test**: name then phone across turns yields
`final_normalized_text` in E.164 and `detected_country` populated.

## Requirements (Functional)

- **FR-A01** The turn's understanding MUST be a single reasoning step (one node) that selects a tool,
  not two independent classify+plan calls.
- **FR-A02** The agent MUST expose these tools: `search_kb`, `lookup_order`, `track_order`,
  `cancel_order`, `reschedule_delivery`, `process_refund`, `start_return`, `update_contact`,
  `cancel_membership`, `answer`, `handoff`.
- **FR-A03** Read-only tools (`search_kb`, `lookup_order`, `track_order`) MAY execute during the turn.
  A state-changing tool MUST NOT execute in the agent; it is recorded as a pending action and a
  confirmation is requested (FR-012/013 from `001` are preserved).
- **FR-A04** Conversation history MAY disambiguate a follow-up but MUST NOT by itself supply an action
  the current message does not ask for.
- **FR-A05** The ONLY path to a backend mutation MUST be `action_execute`, reached only when a pending
  action awaits confirmation (deterministic HITL gate, `classify_confirmation`).
- **FR-A06** A bare confirmation ("yes"/"ok"/"no") reaching the agent with nothing pending MUST yield a
  clarify, deterministically (not left to the prompt).
- **FR-A07** An onboarding slot-fill already in progress (some required slots filled, not all) MUST
  continue in the onboarding flow, not be re-decided into a state-changing tool.
- **FR-A08** Grounding is unchanged in spirit: when retrieval yields nothing usable, the agent MUST
  decline and flag for review rather than invent.
- **FR-A09** The change MUST NOT alter the `TurnResult` contract, the `002` language signals, the `003`
  guardrail decisions, or the `004` evaluation signals — only how the middle decides.
- **FR-A10** The refactor MUST be provider-agnostic (structured-output tool selection), so it works on
  the mock, OpenAI, and Anthropic adapters without native function-calling.

## Success Criteria

- **SC-A01** The two history-poisoning defects (question→action, bare-yes→re-arm) do not reproduce,
  verified live against a real provider across a multi-turn conversation.
- **SC-A02** All prior capabilities (multilingual support, all action types, reads, onboarding fusion,
  guardrails, language switch) pass live and in the deterministic suite.
- **SC-A03** The gate stays green (ruff, mypy over `src` + `evals`, full pytest) with no change to the
  turn contract.
- **SC-A04** The evaluation suite gains a `live_task_success` metric so tool-selection regressions are
  observable in a keyed run (the deterministic tier pins the decision and cannot see them).

## Out of Scope

- Native provider function-calling (the OpenAI adapter does not wire it; structured output is used).
- The pre-existing gaps unrelated to the middle: unsupported-language routing, the latency metric
  measuring scripted (no-network) time, per-process backend state, and per-node trace timing. These are
  tracked in `docs/architecture.md` "Known gaps".
