# Tasks: Agent Core (tool-calling reasoning loop)

**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)

Tasks are marked `[X]` because this spec was written after the implementation was built and validated
live. They are recorded so the work is traceable to requirements, not to imply spec-first sequencing —
that gap is stated plainly in the spec.

## Phase 1 — Build

- [X] T001 Add `AgentStep` schema + the `agent` node (bounded ReAct loop) in
  `src/zapp_assist/graph/nodes/agent.py` (FR-A01, FR-A02).
- [X] T002 Move `action_plan`'s proposal logic into the agent's `_propose` — order verification,
  ask-for-missing-field, confirm template (FR-A03).
- [X] T003 Move `support_rag`'s retrieve+answer+decline into the agent's `search_kb` step and `answer`
  handler (FR-A08).
- [X] T004 Rewire `graph/build.py`: `_route_after_language` (blocked / pending-confirmation /
  onboarding-in-progress / agent) and `_after_agent` (handoff vs verify); delete `route_intent`,
  `action_plan`, `support_rag` and update `nodes/__init__.py` (FR-A01, FR-A05).
- [X] T005 Deterministic gate: bare confirmation → clarify (`_action.is_bare_confirmation`, called at
  the agent's entry) (FR-A06).
- [X] T006 Deterministic gate: onboarding slot-fill in progress continues onboarding; set
  `intent="onboarding"` in the node regardless of entry path (FR-A07).
- [X] T007 Tool-name normalization so a provider echoing a signature is read robustly (FR-A10).

## Phase 2 — Tests & evaluation

- [X] T008 Update the test mock (`tests/support/mock_llm.py`) and the eval mock
  (`evals/scripted_llm.py`) to synthesize `AgentStep` from the fields tests/cases already script, so
  behavioral coverage carries over (FR-A09).
- [X] T009 Add multi-turn conversation tests: history-poisoning, HITL, onboarding fusion
  (`tests/integration/test_agent_core.py`) (US1–US4).
- [X] T010 Add `live_task_success` to the key-adaptive quality tier; exclude it from the byte-stable
  drift guard; carry it forward on a keyless run (SC-A04).
- [X] T011 Refresh the stale `support-en-decline` case (crypto is now covered by the payments KB) into
  a grounded payments case + a genuinely-ungrounded decline case; regenerate the committed report.

## Phase 3 — Verify & reconcile

- [X] T012 Live verification: multiple multi-turn conversations against the real provider across every
  capability (SC-A01, SC-A02).
- [X] T013 Gate green: ruff, mypy `src evals`, full pytest (SC-A03).
- [X] T014 Reconcile `README.md` + the layer docs + `system-flow.md` to the new node (remove
  `route_intent` / `action_plan` / `support_rag` references).

## Independently testable increments

- The agent node + its tools are unit/integration-testable via the scripted mock without touching the
  language or guardrail layers.
- The deterministic gates (T005–T006) are testable in isolation (`is_bare_confirmation`, the
  onboarding-in-progress route).
