# Implementation Plan: Support Agent (Zapp Assist Core)

**Branch**: `001-support-agent` | **Date**: 2026-07-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-support-agent/spec.md`

## Summary

Build the Zapp Assist core: a **deterministic, typed agent graph** that takes one user turn and
produces the canonical JSON contract. The graph runs input guardrails → language detection (fused
deterministic + LLM) → intent routing → one of {grounded support answer (RAG), state-changing action
with human-in-the-loop confirmation, onboarding intake with signal-fusion normalization, safe
out-of-scope decline} → verification/confidence → output guardrails → contract assembly. The system
is built for resilience (timeouts, bounded retries, malformed-response repair, model fallback →
`needs_review`) and observability (per-node trace spans, token/latency/cost per turn). Orchestration
is **LangGraph**, wrapped behind our own graph abstraction; the LLM is **Anthropic Claude** behind a
provider-agnostic client; tools and guardrails are pluggable via registries.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**:
- `anthropic` — Claude SDK (typed exceptions, retries, `usage` for cost). Wrapped by our own
  `LLMClient` so the provider is swappable (Future-Proofing).
- `langgraph` — orchestration graph + typed state; wrapped behind a thin `graph/` abstraction so the
  engine is swappable and nodes stay framework-agnostic (Modularity).
- `pydantic` v2 + `pydantic-settings` — typed contract, entities, and config-as-data.
- `lingua-language-detector` — deterministic language detection, fused with the LLM signal.
- `phonenumbers` — deterministic contact-data normalization (the signal-fusion tool; no network).
- `rank-bm25` — deterministic lexical retrieval over the small curated KB (RAG grounding); no network,
  no embedding provider. Documented as a deliberate simplification, upgradeable to embeddings.
- `structlog` — structured logs; per-turn `Trace` object carries spans + token/latency/cost.
- `typer` + `rich` — CLI entry point and readable output.
- Dev: `pytest`, `ruff`, `mypy`.

**Storage**: In-memory session store behind a `SessionStore` interface (swappable for Redis/DB per
Scalability). Knowledge base = curated Markdown/JSON files in-repo. Mock order/account backend =
in-memory deterministic fixture.

**Testing**: `pytest` (unit + contract + integration). Contract tests assert every turn is
schema-valid; resilience tests inject timeouts/malformed output/tool failures.

**Target Platform**: Local CLI + a callable Python API (`Agent.run_turn(...)`); no web server or auth
in scope for `001`.

**Project Type**: Single Python project (library + CLI).

**LLM configuration (config-as-data)**:
- Primary reasoning (router, responder, normalization-fusion, verifier): `claude-sonnet-5` — the
  production default (near-Opus quality at lower cost/latency; the assessment grades cost/conversation
  and p95 latency). Swappable to `claude-opus-5` via config for hardest cases. See research.md.
- Adaptive thinking on; `effort` per node (low for routing/detection, medium for answering/verifying).
- Structured output via Pydantic + `messages.parse()` / `output_config.format` — this is how the JSON
  contract is enforced at the model boundary.
- **`temperature` note**: current Claude models (`claude-sonnet-5`/`claude-opus-5`) reject a
  `temperature` parameter (400). The brief's "temperature 0" is therefore realized via structured
  schemas + low `effort` + a deterministic rubric, not a temperature knob. The `LLMClient` accepts an
  optional `temperature` and applies it only to models that support it (e.g. `claude-haiku-4-5`).
  Recorded as a documented divergence (see Constitution Check → XI and README).

**Performance Goals**: p95 end-to-end turn latency and estimated cost/conversation reported every eval
run, within configurable thresholds (SC-008). Targets tuned during evaluation (`004`).

**Constraints**: Every turn returns a schema-valid contract, including on failure (FR-001/002,
SC-001/006). No secrets in repo; keys via env (`ANTHROPIC_API_KEY`).

**Scale/Scope**: Single-process demo; stateless nodes + externalized session state so horizontal
scale is not precluded (Scalability, design posture).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design (below).*

| # | Principle | How this design honors it |
|---|-----------|---------------------------|
| I | Scalability | Node/tool handlers are stateless pure functions of `(TurnState) → TurnState`; session state lives behind `SessionStore` (in-memory now, swappable). No shared mutable globals. Scaling path documented; autoscaling not built (design posture). |
| II | Modularity | Explicit typed graph; `ToolRegistry` + `GuardrailRegistry`; provider-abstracted `LLMClient`; pluggable `LanguageDetector` and `SessionStore`. Adding a tool/guardrail/model touches no orchestrator code. LangGraph is wrapped, not leaked into nodes. |
| III | Resilience & Security | `LLMClient` enforces timeout + bounded retries (SDK) + malformed-response repair + model fallback; failures → safe reply + `needs_review`. Untrusted input screened by input guardrails; tool inputs validated (strict schemas); secrets via env; HITL gate on state-changing actions. |
| IV | Continuous Learning | Session memory carries prior turns + collected slots + pending action; `needs_review`/guardrail/low-confidence turns are emitted in a structured form that `004` folds into the eval dataset. Offline/eval-driven (design posture). |
| V | Future-Proofing | Provider-agnostic `LLMClient` (adapter); LangGraph behind our `graph/` seam; config-as-data (models, thresholds, languages, tools, pricing); open standards (Pydantic/JSON Schema, structured logs). |
| VI | Spec-Driven & Traceable | This plan precedes code; tasks.md next; commits trace to spec/tasks; history stays specs-before-code on the feature branch. |
| VII | Structured, Validated Output Contract | Pydantic `TurnResult` validated before return; malformed model output repaired or fails closed to a valid contract with `needs_review=true`. Contract in `contracts/`. |
| VIII | Guardrails by Default, Fail-Safe | `guardrail_in` and `guardrail_out` nodes run on every path (baseline set in `001`, taxonomy in `003`); blocked turns return a safe contract; decisions recorded in `guardrails.input/output`. |
| IX | Multilingual Coherence & Graceful Degradation | Baseline detect + `active_lang` lock + fallback in `001` (FR-021); full policy in `002`. |
| X | Signal Fusion & Deterministic Safety | `phonenumbers` (deterministic) fused with LLM interpretation → `final_normalized_text`/`detected_country`; deterministic signal wins on correctness-critical values; divergence lowers `confidence_score`/sets `needs_review`. |
| XI | Observability & Eval-Driven Verification | Per-node `Span` with token/latency/cost; per-turn `Trace`; consumed by `004`. **Deviation:** literal `temperature=0` is impossible on current Claude models — determinism for the judge/deterministic paths comes from structured schemas + low `effort` + deterministic rubric; `temperature` applied only where the model supports it. Justified in Complexity Tracking. |

**Gate result: PASS** — one justified deviation (temperature), tracked below.

## Project Structure

### Documentation (this feature)

```text
specs/001-support-agent/
├── spec.md              # requirements (done)
├── plan.md              # this design
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — entities
├── quickstart.md        # Phase 1 — run/validate guide
├── contracts/           # Phase 1 — interface contracts
│   ├── agent-turn.md    #   the canonical JSON turn contract
│   ├── nodes.md         #   node input/output contract (graph state)
│   └── tools.md         #   tool + guardrail + LLMClient interfaces
└── tasks.md             # created by /speckit-tasks (next)
```

### Source Code (repository root)

```text
src/zapp_assist/
├── __init__.py
├── config.py                 # pydantic-settings: models, thresholds, languages, pricing (config-as-data)
├── contracts.py              # Pydantic models: TurnResult (the JSON contract), GuardrailDecision, ...
├── llm/
│   ├── client.py             # provider-agnostic LLMClient (timeout/retry/repair/fallback/cost)
│   └── anthropic_adapter.py  # Claude implementation (the only provider-specific file)
├── graph/
│   ├── state.py              # TurnState (typed LangGraph state) + Session
│   ├── build.py              # wire nodes/edges into the LangGraph; the only LangGraph-aware module
│   └── nodes/                # one stateless node per step
│       ├── guardrail_in.py
│       ├── detect_language.py
│       ├── route_intent.py
│       ├── support_rag.py
│       ├── action_plan.py
│       ├── action_execute.py # HITL-gated
│       ├── onboarding.py     # slot-fill + normalize (signal fusion)
│       ├── out_of_scope.py
│       ├── verify_confidence.py
│       ├── guardrail_out.py
│       └── assemble.py       # build + validate TurnResult
├── tools/
│   ├── registry.py           # ToolRegistry
│   ├── normalize.py          # phonenumbers-based normalization (signal-fusion tool)
│   └── mock_backend.py       # deterministic order/account actions
├── guardrails/
│   ├── registry.py           # GuardrailRegistry (baseline rules in 001; taxonomy in 003)
│   └── baseline.py
├── lang/
│   └── detector.py           # lingua-based deterministic detector (baseline; deepened in 002)
├── rag/
│   ├── store.py              # BM25 retriever over curated KB
│   └── kb/                   # curated policy/FAQ docs
├── memory/
│   └── session_store.py      # SessionStore interface + in-memory impl
├── obs/
│   └── trace.py              # Trace/Span, token+latency+cost accounting
├── agent.py                  # Agent.run_turn(session_id, user_text) → TurnResult
└── cli.py                    # typer CLI (interactive + one-shot)

tests/
├── contract/                 # every turn schema-valid; contract-shape tests
├── integration/              # US1–US5 acceptance scenarios end-to-end (mock LLM)
└── unit/                     # nodes, tools, fusion, resilience, detector
```

**Structure Decision**: Single Python package `zapp_assist` with a clear seam per concern
(`llm/`, `graph/`, `tools/`, `guardrails/`, `lang/`, `rag/`, `memory/`, `obs/`). The two files that
know a vendor — `llm/anthropic_adapter.py` (Claude) and `graph/build.py` (LangGraph) — are isolated
so both are swappable (Future-Proofing, Modularity). Nodes depend only on `TurnState` + injected
registries/clients, never on LangGraph or the Anthropic SDK directly.

## Complexity Tracking

| Violation / deviation | Why needed | Simpler alternative rejected because |
|-----------------------|------------|--------------------------------------|
| `temperature=0` not applied on the judge / deterministic paths | Current Claude models (`claude-sonnet-5`/`claude-opus-5`) reject `temperature` (HTTP 400). | Pinning the judge to an older temperature-accepting model (e.g. `claude-haiku-4-5`) would trade judgment quality for a knob that no longer exists on frontier models; instead determinism comes from structured JSON schema + low `effort` + a fixed rubric, and `temperature` is applied only where the model supports it. Documented in README. |
| LangGraph dependency (vs hand-rolled graph) | User-selected; provides typed state, conditional edges, and checkpointing that would otherwise be re-implemented. | A hand-rolled graph was the alternative; LangGraph is wrapped behind `graph/` so the dependency does not leak into nodes and can be swapped, satisfying Modularity/Future-Proofing. |
| BM25 retrieval (vs embeddings) | Deterministic, no network, no extra provider; sufficient to demonstrate grounded answering on a small KB. | Embedding-based retrieval needs a second provider (Anthropic has no embeddings API) or a heavy local model; documented as an upgrade path rather than a hidden gap. |
