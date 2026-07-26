# Tasks: Multilingual Coherence & Language Policy

**Input**: Design documents from `/specs/002-multilingual/`

**Prerequisites**: plan.md, spec.md (required); research.md, data-model.md, contracts/language.md,
quickstart.md (available)

**Tests**: Included — the spec's per-story "Independent Test" criteria and measurable Success Criteria,
plus Constitution IX/X/XI (multilingual coherence, deterministic safety, eval signals), make tests
in-scope.

**Organization**: Grouped by user story. Builds on the `001` agent core in place — no new dependencies,
the `001` `TurnResult` contract is unchanged (FR-014), and **every existing `001` test must keep
passing**.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 (user-story phases only)
- All paths are relative to the repo root; single Python project (`src/zapp_assist/`, `tests/`).

---

## Phase 1: Foundational (blocking prerequisites for all user stories)

**Purpose**: additive state, config, and helpers every story builds on. All independent files → `[P]`.

- [ ] T001 [P] Add thresholds `language_switch_min_confidence` (0.75), `language_switch_turns` (2), `reply_verify_min_chars` (15) to `Thresholds` in `src/zapp_assist/config.py` and to `config.yaml` under `thresholds`
- [ ] T002 [P] Add bounded switch-state fields `pending_switch_lang: str | None = None` and `pending_switch_count: int = 0` to `Session` in `src/zapp_assist/memory/session_store.py`
- [ ] T003 [P] Add transient reply-check fields `reply_lang: str | None`, `reply_match: bool | None`, `reply_corrected: bool = False` to `TurnState` in `src/zapp_assist/graph/state.py`
- [ ] T004 [P] Add a reply-language detection helper (detect the language of an arbitrary string over the supported set, reusing `LinguaDetector`) in `src/zapp_assist/lang/detector.py`
- [ ] T005 [P] Add per-language "let me answer in your language" safe templates (`LANG_MISMATCH_TEMPLATES`, ES/EN/PT) in `src/zapp_assist/graph/nodes/_util.py`

**Checkpoint**: config, session, state, detector helper, and templates exist; nothing wired yet.

---

## Phase 2: User Story 1 — Verified in-language replies (Priority: P1) 🎯 MVP

**Goal**: guarantee the reply is actually in `active_lang` — correct once, else safe-flag; never ship a
mismatch.

**Independent Test**: ES/EN/PT in-domain questions → reply in the request language; a forced
wrong-language reply → corrected or safe `needs_review` result, never the mismatched text.

### Tests for User Story 1

- [ ] T006 [P] [US1] Unit test `verify_reply_language`: reply matches (no correction); wrong-language → one correction → matches; still-wrong → safe template + `needs_review=true`; short reply skipped; in `tests/unit/test_reply_language_verify.py`
- [ ] T007 [P] [US1] Integration test (ES/EN/PT): in-domain question → reply in request language + trace `reply_match=true`; forced wrong-language reply → never shipped (SC-002); in `tests/integration/test_us_multilingual.py`

### Implementation for User Story 1

- [ ] T008 [US1] Implement the `verify_reply_language` node (deterministic reply detect; skip on degraded/blocked/no-reply/short; one bounded LLM correction re-ask via the existing adapter; fail-safe to `LANG_MISMATCH_TEMPLATES` + `needs_review_override`; record span attrs) in `src/zapp_assist/graph/nodes/verify_reply_language.py` (depends on T003, T004, T005)
- [ ] T009 [US1] Wire the node into the graph after the answer-producing nodes and before `verify_confidence` (update edges) and export it in `src/zapp_assist/graph/build.py` + `src/zapp_assist/graph/nodes/__init__.py` (depends on T008)

**Checkpoint**: US1 works — replies are verified in-language; MVP is demonstrable and 001 tests green.

---

## Phase 3: User Story 2 — Coherence & sustained-switch policy (Priority: P2)

**Goal**: persist `active_lang` across weak turns; switch only on sustained, confident intent; never
thrash on a one-off phrase.

**Independent Test**: multi-turn session in one language incl. short turns → 0 flips; sustained input in
another supported language → switches; a single foreign phrase → no switch.

### Tests for User Story 2

- [ ] T010 [P] [US2] Unit test the pure switch-policy function across the transition table (first-lock; keep on match/weak/short; accumulate then switch at `language_switch_turns`; reset on interruption; unsupported ignored) in `tests/unit/test_switch_policy.py`
- [ ] T011 [P] [US2] Integration test: multi-turn PT session with short turns keeps `pt` (SC-003); sustained EN switches (SC-004); one-off EN phrase does not switch (SC-004); in `tests/integration/test_us_multilingual.py`

### Implementation for User Story 2

- [ ] T012 [P] [US2] Implement the pure `apply_switch_policy(active, detected, confidence, pending_lang, pending_count, config) -> (active, pending_lang, pending_count, switched)` function (sole owner of the data-model §1 transition table) in `src/zapp_assist/lang/detector.py` (depends on T001)
- [ ] T013 [US2] Update `detect_language` to apply the switch policy (replace lock-forever), persist the switch-state on the session, and record `{detected, active, confidence, switched, pending}` span attrs in `src/zapp_assist/graph/nodes/detect_language.py` (depends on T012, T002)

**Checkpoint**: US1 + US2 work independently; language is coherent and switches only on intent.

---

## Phase 4: User Story 3 — Graceful degradation on unsupported / low-confidence (Priority: P2)

**Goal**: never reply in an unsupported language; fall back safely and flag review.

**Independent Test**: French input and separately low-confidence input → valid contract, fallback-language
reply, `needs_review=true`, never an unsupported-language reply.

### Tests for User Story 3

- [ ] T014 [P] [US3] Integration test: unsupported language (French) → fallback (`en`) reply + `needs_review=true`, no French reply (SC-005); low-confidence/short input → keep active/fallback, safe reply; in `tests/integration/test_us_multilingual.py`

### Implementation for User Story 3

- [ ] T015 [US3] Ensure the degradation path is closed: `detect_language` fallback for unsupported/low-confidence sets `needs_review_override`; `verify_reply_language` never emits a reply whose language is unsupported (fail-safe template wins); confirm `assemble` yields a valid contract in `src/zapp_assist/graph/nodes/detect_language.py` + `verify_reply_language.py` (depends on T013, T008)

**Checkpoint**: US1–US3 independently functional; the language safety envelope is closed.

---

## Phase 5: User Story 4 — Language-fidelity signals for evaluation (Priority: P3)

**Goal**: per-turn language facts are readable from the trace so `004` can score fidelity without reading
reply text.

**Independent Test**: any turn exposes detected/active/confidence/reply_lang/reply_match; a batch yields a
computable language-fidelity rate.

### Tests for User Story 4

- [ ] T016 [P] [US4] Unit test: both spans (`detect_language`, `verify_reply_language`) carry the fidelity attributes; a fidelity-rate helper computes the share of `reply_match=true` over a run in `tests/unit/test_language_fidelity.py`

### Implementation for User Story 4

- [ ] T017 [US4] Confirm both spans emit the fidelity attributes (from T013/T008) and add a small reader helper to compute a language-fidelity rate from a `Trace`/run (consumed later by `004`) in `src/zapp_assist/obs/trace.py` (depends on T013, T008)

**Checkpoint**: all four stories functional; fidelity signals available to evaluation.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T018 [P] Update the README roadmap to reflect the 002 mechanisms (verified replies, switch policy, fidelity signals) in `README.md`
- [ ] T019 Run the full gate — `ruff check .`, `mypy src`, `pytest` (001 + 002) — confirm **0 regressions in 001** and execute the `quickstart.md` validations end-to-end
- [ ] T020 [P] Config-as-data audit: the three new thresholds are config-driven and the supported set stays config-extensible; no hardcoded languages/thresholds in `src`

---

## Dependencies & execution order

- **Foundational (Phase 1)** blocks every user story. T001–T005 are all `[P]` (different files).
- **US1 (P1)** depends only on Foundational → the MVP. Ship/verify before US2.
- **US2 (P2)** depends on Foundational; independent of US1 (different files: `detector.py` policy fn +
  `detect_language.py`).
- **US3 (P2)** depends on US1 (verify node) + US2 (detect_language policy).
- **US4 (P3)** depends on US1 + US2 (the spans that carry the attributes).
- **Polish (Phase 6)** depends on all stories.

## Parallel execution examples

- Foundational: T001, T002, T003, T004, T005 in parallel (config, session, state, detector, templates).
- Within a story, the test tasks marked `[P]` can be written alongside each other before implementation.
- US2's pure policy function (T012) can be built in parallel with US1's node (T008) — different files.

## Implementation strategy

- **MVP = User Story 1** (verified in-language replies): the P1 guarantee and the clearest improvement
  over `001`. Deliver and verify it (gate green, 001 untouched) before US2.
- Then increment US2 → US3 → US4, committing each as its own increment on `002-multilingual`, keeping
  the gate green and the `001` contract + tests intact at every step.
