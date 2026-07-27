# Tasks: Support Agent (Zapp Assist Core)

**Input**: Design documents from `/specs/001-support-agent/`

**Prerequisites**: plan.md, spec.md (required); research.md, data-model.md, contracts/ (available)

**Tests**: Included — the spec's per-story "Independent Test" criteria, the measurable Success
Criteria, and Constitution principles VII/VIII/XI (verification + eval cases) make tests in-scope.

**Organization**: Grouped by user story so each can be implemented and tested independently. Baseline
language + guardrails are in-scope for `001` (FR-019/FR-021) and are deepened later by `002`/`003`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5 (user-story phases only)
- All paths are relative to the repo root; single Python project (`src/zapp_assist/`, `tests/`).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and structure.

- [ ] T001 Create the package/test tree per plan.md (`src/zapp_assist/{llm,graph,graph/nodes,tools,guardrails,lang,rag,rag/kb,memory,obs}/__init__.py` and `tests/{contract,integration,unit,support}/`)
- [ ] T002 Initialize `uv` project: `pyproject.toml` with pinned runtime deps (`anthropic`, `langgraph`, `pydantic>=2`, `pydantic-settings`, `lingua-language-detector`, `phonenumbers`, `rank-bm25`, `structlog`, `typer`, `rich`) and dev deps (`pytest`, `ruff`, `mypy`); generate `uv.lock`; add `zapp-assist` console script
- [ ] T003 [P] Configure `ruff`, `mypy`, and `pytest` in `pyproject.toml`
- [ ] T004 [P] Add `.env.example` (`ANTHROPIC_API_KEY`) and `config.yaml` (models, `effort` per node, confidence thresholds, supported languages ES/EN/PT + fallback, pricing table) at repo root

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared pipeline every user story plugs into. **⚠️ No user-story work begins until this phase is complete.**

- [ ] T005 [P] Implement config loader (`pydantic-settings`) reading `config.yaml` + env in `src/zapp_assist/config.py`
- [ ] T006 [P] Implement the canonical contract models `TurnResult`, `Guardrails`, `GuardrailDecision` (per contracts/agent-turn.md) in `src/zapp_assist/contracts.py`
- [ ] T007 [P] Implement `Trace`/`Span` + token/latency/cost accounting in `src/zapp_assist/obs/trace.py`
- [ ] T008 [P] Define `LLMClient` protocol + `LLMResult`/`Usage` (per contracts/tools.md) in `src/zapp_assist/llm/client.py`
- [ ] T009 Implement the Anthropic adapter (structured output via `messages.parse`, explicit timeout, bounded retries, malformed-response repair, `refusal` handling, model fallback → `degraded`, cost from pricing; `temperature` forwarded only where supported) in `src/zapp_assist/llm/anthropic_adapter.py` (depends on T005, T007, T008)
- [ ] T010 [P] Implement a deterministic `MockLLMClient` (scriptable replies + `ZAPP_FAULT=timeout|malformed|tool_error`) in `tests/support/mock_llm.py`
- [ ] T011 [P] Implement `Session` model + `SessionStore` interface + in-memory impl in `src/zapp_assist/memory/session_store.py`
- [ ] T012 [P] Implement `LanguageDetector` interface + `lingua` impl + LLM-fusion helper (`detected_lang`/`lang_confidence`) in `src/zapp_assist/lang/detector.py`
- [ ] T013 [P] Implement `GuardrailRegistry` + baseline guardrails (input: injection/PII/abuse/off-topic; output: PII-leak/ungrounded/policy) in `src/zapp_assist/guardrails/registry.py` and `src/zapp_assist/guardrails/baseline.py`
- [ ] T014 [P] Implement `ToolRegistry` (register/get/specs) in `src/zapp_assist/tools/registry.py`
- [ ] T015 Define `TurnState` in `src/zapp_assist/graph/state.py` (depends on T006, T011)
- [ ] T016 Implement shared nodes `guardrail_in`, `detect_language`, `route_intent`, `verify_confidence`, `guardrail_out`, `assemble` in `src/zapp_assist/graph/nodes/` (each appends one `Span`; `assemble` validates or fails closed) (depends on T006–T015)
- [ ] T017 Wire the LangGraph in `src/zapp_assist/graph/build.py` with a node runner that catches exceptions → `error` span + degraded route, plus conditional routing edges (depends on T015, T016)
- [ ] T018 Implement `Agent.run_turn(session_id, text) -> TurnResult` (load session → run graph → save session → return validated contract) in `src/zapp_assist/agent.py` (depends on T017)
- [ ] T019 Implement the `typer` CLI (`chat`, `turn --session --text`) in `src/zapp_assist/cli.py` (depends on T018)
- [ ] T020 [P] Contract test: every turn returns a schema-valid `TurnResult` on the mock LLM (SC-001) in `tests/contract/test_turn_contract.py`

**Checkpoint**: skeleton pipeline runs end-to-end (clarify/decline paths), always contract-valid.

---

## Phase 3: User Story 1 - Grounded support answer (Priority: P1) 🎯 MVP

**Goal**: Answer in-domain questions grounded in the KB, in the user's language, with a valid contract.

**Independent Test**: Ask an in-domain question in ES/EN/PT → grounded reply in that language, valid contract, `needs_review=false`; ask an unknown-to-KB question → decline instead of inventing.

### Tests for User Story 1

- [ ] T021 [P] [US1] Integration test: in-domain ES/EN/PT question → grounded, same-language reply, valid contract, `needs_review=false` (SC-002, SC-007) in `tests/integration/test_us1_support.py`
- [ ] T022 [P] [US1] Test: question with no KB grounding → agent declines + `needs_review=true` (SC-002) in `tests/integration/test_us1_support.py`

### Implementation for User Story 1

- [ ] T023 [P] [US1] Curate the seed knowledge base (delivery/account policy + FAQ docs, ES/EN/PT) as `KnowledgeDocument` files in `src/zapp_assist/rag/kb/`
- [ ] T024 [P] [US1] Implement the BM25 retriever (`KnowledgeDocument` index + score threshold) in `src/zapp_assist/rag/store.py`
- [ ] T025 [US1] Implement `support_rag` node (retrieve → ground+cite or decline; contribute grounding confidence) in `src/zapp_assist/graph/nodes/support_rag.py` (depends on T024)
- [ ] T026 [US1] Route `support → support_rag` in `graph/build.py` and author the grounded-answer system prompt/rules (depends on T025)

**Checkpoint**: US1 fully functional and independently testable (MVP).

---

## Phase 4: User Story 2 - Onboarding intake with signal-fusion normalization (Priority: P2)

**Goal**: Capture and normalize messy contact data by fusing LLM interpretation with a deterministic tool.

**Independent Test**: Submit messy phone+country → correct E.164 `final_normalized_text` + `detected_country`; force LLM/deterministic divergence → confidence drops + `needs_review`.

### Tests for User Story 2

- [ ] T027 [P] [US2] Test: messy phone + country hint → `final_normalized_text` E.164 + correct `detected_country` (SC-003) in `tests/integration/test_us2_onboarding.py`
- [ ] T028 [P] [US2] Test: LLM vs deterministic divergence → `confidence_score` lowered + `needs_review=true` (SC-004); partial data → asks only the missing field in `tests/integration/test_us2_onboarding.py`

### Implementation for User Story 2

- [ ] T029 [P] [US2] Implement `normalize_contact` tool (`phonenumbers` → E.164 + region → `NormalizationSignal`) and register it in `src/zapp_assist/tools/normalize.py`
- [ ] T030 [US2] Implement `onboarding` node (slot-fill; fuse LLM + deterministic per Principle X; ask only missing field; no fabrication) in `src/zapp_assist/graph/nodes/onboarding.py` (depends on T029)
- [ ] T031 [US2] Route `onboarding → onboarding` and feed the fusion signal into `verify_confidence` in `graph/build.py` / `verify_confidence.py` (depends on T030)

**Checkpoint**: US1 and US2 both work independently.

---

## Phase 5: User Story 3 - Action with human-in-the-loop confirmation (Priority: P2)

**Goal**: Perform state-changing actions only after explicit confirmation, exactly once.

**Independent Test**: Request a state-changing action → agent restates + asks confirmation, no backend change; "yes" → executes once; decline/ambiguous → abandoned.

### Tests for User Story 3

- [ ] T032 [P] [US3] Test: action request → confirmation asked + no backend change; "yes" → executed exactly once; decline/ambiguous → no change (SC-005) in `tests/integration/test_us3_action.py`

### Implementation for User Story 3

- [ ] T033 [P] [US3] Implement `mock_backend` tool (`lookup_order`, `reschedule_delivery`, `cancel_order`; deterministic; idempotent execute) and register it in `src/zapp_assist/tools/mock_backend.py`
- [ ] T034 [US3] Implement `action_plan` node (restate action + params; set `pending_action=awaiting_confirmation`; no execution) in `src/zapp_assist/graph/nodes/action_plan.py`
- [ ] T035 [US3] Implement `action_execute` node (execute once from `confirmed` only; abandon on decline/ambiguity) in `src/zapp_assist/graph/nodes/action_execute.py` (depends on T033, T034)
- [ ] T036 [US3] Route `action → action_plan → (confirm?) → action_execute`, detecting confirmation via `session.pending_action` in `graph/build.py` (depends on T034, T035)

**Checkpoint**: US1–US3 independently functional.

---

## Phase 6: User Story 4 - Safe handling of out-of-scope / unsafe requests (Priority: P3)

**Goal**: Decline off-topic, unsafe, and injection attempts safely and transparently, in the user's language.

**Independent Test**: Send off-topic/unsafe/injection inputs → safe decline, guardrail decision recorded in the contract, no system disclosure.

### Tests for User Story 4

- [ ] T037 [P] [US4] Test: off-topic/unsafe/injection input → safe decline, `guardrails.input` records the decision, no system-prompt disclosure, reply in `active_lang` in `tests/integration/test_us4_guardrails.py`

### Implementation for User Story 4

- [ ] T038 [P] [US4] Strengthen baseline input guardrails (prompt-injection, off-topic, abuse) + per-language decline templates in `src/zapp_assist/guardrails/baseline.py`
- [ ] T039 [US4] Implement `out_of_scope` node + route `out_of_scope → out_of_scope` (safe decline in `active_lang`) in `src/zapp_assist/graph/nodes/out_of_scope.py` (depends on T038)

**Checkpoint**: US1–US4 independently functional.

---

## Phase 7: User Story 5 - Graceful degradation under failure or low confidence (Priority: P2)

**Goal**: Always return a safe, valid, flagged contract under dependency failure or low confidence — no crash.

**Independent Test**: Inject timeout/malformed/tool failures and forced low confidence → valid contract, safe reply, `needs_review=true`, no crash/hang.

### Tests for User Story 5

- [ ] T040 [P] [US5] Resilience tests: `ZAPP_FAULT=timeout|malformed|tool_error` → valid contract, safe reply, `needs_review=true`, 0 crashes (SC-006) in `tests/unit/test_resilience.py`
- [ ] T041 [P] [US5] Test: overall confidence below threshold → `needs_review=true` and reply avoids asserting uncertain facts in `tests/unit/test_resilience.py`

### Implementation for User Story 5

- [ ] T042 [US5] Ensure the node runner (T017) + `assemble` fail closed to a safe `TurnResult` on any node error or `degraded` LLM result, mapping `degraded → needs_review=true` in `graph/build.py` / `graph/nodes/assemble.py`
- [ ] T043 [US5] Add config-driven low-confidence threshold handling to `verify_confidence` in `src/zapp_assist/graph/nodes/verify_confidence.py`

**Checkpoint**: all five stories independently functional; every path degrades safely.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T044 [P] Unit tests for language fusion, BM25 scoring, and cost accounting in `tests/unit/`
- [ ] T045 [P] README: run instructions, the `temperature`-0 divergence note, trade-offs & known limitations, and where AI-copilot suggestions were accepted/rejected (brief expectations)
- [ ] T046 Verify observability: every node emits a `Span`; per-turn and per-conversation latency/token/cost recorded (feeds `004`)
- [ ] T047 Run `ruff check` + `mypy` clean and execute the `quickstart.md` validation end-to-end
- [ ] T048 [P] Audit config-as-data: no hardcoded models/thresholds/languages; secrets only via env (Constitution V, Security)

---

## Phase 9: Grounding Pipeline & Advanced Retrieval (US1 depth) — FR-023–FR-027

**Goal**: Make grounding a first-class layer — a reproducible ingestion pipeline over a structured
multi-domain KB, and hybrid + advanced retrieval on top — all config-gated and degrading to the
deterministic BM25 floor offline (so CI and the committed eval stay keyless).

**Independent Test**: `zapp-ingest` rebuilds the committed index from sources with no key (SC-009);
with a key, a paraphrased/cross-lingual question that BM25 alone misses is recalled via
hybrid+HyPE/HyDE/RAG-Fusion and correctly filtered by Self-Query; with no key, retrieval degrades to
BM25 and grounded-answer/decline behavior is unchanged (FR-025).

### Ingestion

- [ ] T049 [US1] Implement the ingestion **validate** stage (schema / language / duplication / coverage) in `src/zapp_assist/ingestion/validate.py`
- [ ] T050 [US1] Implement chunking + `KnowledgeDocument` assembly + deterministic **index build** in `src/zapp_assist/ingestion/pipeline.py`
- [ ] T051 [US1] Implement **offline LLM enrichment** (HyPE questions + translation gap-fill), cached and committed so rebuilds are keyless/deterministic (FR-024), in `src/zapp_assist/ingestion/enrich.py`
- [ ] T052 [US1] Add the **`zapp-ingest`** console entry point (build/validate the index; offline by default, `--refresh` re-runs enrichment against a live provider) in `src/zapp_assist/ingestion/cli.py` + `pyproject.toml`
- [ ] T053 [P] [US1] Expand the KB to ~6 category/topic domains (delivery, account, payments, orders, returns, membership) × ES/EN/PT under `src/zapp_assist/rag/kb/`

### Retrieval

- [ ] T054 [US1] `Embedder` seam (OpenAI `text-embedding-3-small`) in `src/zapp_assist/rag/embedder.py`; `Retriever` protocol + config-driven factory in `src/zapp_assist/rag/retriever.py`
- [ ] T055 [US1] Dense (semantic) retriever with **HyPE** representations (index each doc's hypothetical questions) in `src/zapp_assist/rag/dense.py`
- [ ] T056 [US1] **Hybrid** retriever — BM25 + dense fused via Reciprocal Rank Fusion, degrading to BM25 offline — in `src/zapp_assist/rag/hybrid.py`
- [ ] T057 [US1] **Advanced** query expansion — HyDE (hypothetical-answer query) + RAG-Fusion (multi-phrasing + fuse), reporting LLM cost to the trace via `on_llm` (FR-027) — in `src/zapp_assist/rag/advanced.py`
- [ ] T058 [US1] **Self-Query** metadata filtering — LLM extracts category/topic filters, applied before retrieval; degrades to no-filter when no LLM (FR-026) — in `src/zapp_assist/rag/advanced.py`
- [ ] T059 [US1] **LLM reranker** over the fused candidate set, config-gated, degrading to fusion order — in `src/zapp_assist/rag/advanced.py`
- [ ] T060 [US1] Extend the `config.yaml` `retrieval:` block (mode, embedder, rrf_k, hype, hyde, rag_fusion, self_query, rerank) — every enhancement toggled as config-as-data (FR-026)

### Tests & eval

- [ ] T061 [P] [US1] Offline retrieval tests: HyPE recall, hybrid RRF, HyDE/RAG-Fusion expansion, Self-Query filter, rerank ordering, degrade-to-BM25, `on_llm` cost reporting in `tests/unit/test_retrieval_*.py`
- [ ] T062 [P] [US1] Ingestion tests: validate rejects malformed docs; enrichment cache is deterministic; the committed index rebuilds keyless (SC-009) in `tests/unit/test_ingestion.py`
- [ ] T063 [US1] Broaden the `004` eval dataset to exercise the new domains; keep the committed report deterministic (bm25-pinned) in `evals/dataset/`

**Checkpoint**: grounding is a reproducible, observable, config-tunable layer; offline behavior is byte-for-byte unchanged.

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2)** blocks everything. **User stories (P3–P7)** all depend only on Foundational; they can then proceed in parallel or in priority order. **Polish (P8)** last.
- **US1 (P1)** MVP — no dependency on other stories.
- **US2/US3/US4** — independent branches off the shared pipeline; each independently testable.
- **US5** — resilience mechanisms live in Foundational (T009/T017); its phase is fault-injection tests + fail-closed wiring + low-confidence handling.
- **Phase 9 (Grounding pipeline)** — depends on Foundational + US1 (T023–T026); within it, ingestion (T049–T053) precedes the retrievers that consume the built index (T054–T060), then tests/eval (T061–T063). Every enhancement is independently config-gated, so partial adoption is safe.
- Within a story: tests written first (should fail) → tool/store → node → routing.

## Parallel Opportunities

- Setup: T003, T004 in parallel.
- Foundational: T005–T014 are mostly `[P]` (distinct files); T015→T016→T017→T018→T019 are sequential.
- Per story, the `[P]` tests and the `[P]` tool/store tasks run in parallel before the node wiring.

## Parallel Example: Foundational

```bash
# After T001–T004, launch the independent foundational modules together:
Task: "T006 contracts.py"   Task: "T007 obs/trace.py"   Task: "T008 llm/client.py"
Task: "T011 memory/session_store.py"   Task: "T012 lang/detector.py"
Task: "T013 guardrails/*"   Task: "T014 tools/registry.py"
```

## Implementation Strategy

- **MVP**: Phase 1 → Phase 2 → Phase 3 (US1), then STOP and validate the grounded-answer loop end to end.
- **Incremental**: add US2 → US3 → US4 → US5, validating each independently; none breaks a prior story.
- Commit after each task or logical group; keep specs-before-code ordering on the branch.

## Notes

- `[P]` = different files, no incomplete dependency. `[US#]` maps tasks to stories for traceability.
- Baseline language/guardrails here are deepened by specs `002`/`003`; the eval suite is `004`.
- US1 grounding is deepened by Phase 9 (hybrid + advanced retrieval over a reproducible ingestion pipeline).
- Verify tests fail before implementing; a task is "done" only when its acceptance criteria pass
  (Constitution: "It runs" is not "it is verified").
