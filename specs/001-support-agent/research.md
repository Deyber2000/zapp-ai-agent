# Phase 0 Research: Support Agent (Zapp Assist Core)

Decisions resolving the technical unknowns from `plan.md`. Format: Decision / Rationale /
Alternatives considered.

## 1. LLM provider & model tier

- **Decision**: Anthropic Claude behind a provider-agnostic `LLMClient`. Default primary model
  `claude-sonnet-5`; configurable to `claude-opus-5`. Cheap-path tasks (routing, detection assist)
  may use `claude-sonnet-5` at `effort: low`.
- **Rationale**: Sonnet 5 is near-Opus quality at ~⅗ the input / ⅗ the output price ($3/$15 vs
  $5/$25 per 1M) with lower latency — the right production default for a support agent that is graded
  on cost/conversation and p95 latency. The model is a config value, so switching to Opus 5 for the
  hardest cases is a one-line change.
- **Alternatives**: (a) Opus 5 everywhere — best quality, higher cost/latency; kept as a config
  option. (b) OpenAI — rejected per the provider decision; the adapter seam keeps it possible.

## 2. Structured output / enforcing the JSON contract

- **Decision**: Define the contract as a Pydantic v2 model and obtain it via Anthropic structured
  outputs (`messages.parse()` with the Pydantic model, i.e. `output_config.format`). Validate the
  final `TurnResult` again in `assemble` before returning.
- **Rationale**: Server-side schema enforcement drastically lowers malformed-output rate; a second
  local validation guarantees FR-002 (never emit an invalid contract). Supported on Sonnet 5 / Opus 5.
- **Alternatives**: Prompt-and-parse JSON (higher malformed rate); tool-forcing (`tool_choice`) — used
  selectively for tool calls, but the turn contract uses `output_config.format`.

## 3. Determinism & the "temperature 0" requirement

- **Decision**: Do not send `temperature`. Achieve reproducibility for the judge and deterministic
  paths via (a) structured JSON schema, (b) low `effort`, (c) a fixed, versioned rubric/prompt. The
  `LLMClient` accepts an optional `temperature` and forwards it **only** to models that accept it.
- **Rationale**: `temperature`/`top_p`/`top_k` are removed on `claude-sonnet-5`/`claude-opus-5` (HTTP
  400). Even historically, `temperature=0` never guaranteed identical outputs. This is an honest
  divergence from the brief, documented in README and the Constitution Check.
- **Alternatives**: Pin the judge to `claude-haiku-4-5` (accepts `temperature`) — rejected: trades
  judgment quality for a knob; kept available via config for experiments.

## 4. Orchestration

- **Decision**: LangGraph for the graph + typed state + conditional edges, wrapped behind a small
  `graph/` module. Nodes are pure `(TurnState) → TurnState`-style handlers that never import LangGraph
  or the Anthropic SDK.
- **Rationale**: Provides state management, conditional routing, and checkpointing out of the box;
  wrapping keeps Modularity/Future-Proofing intact and makes the engine swappable.
- **Alternatives**: Hand-rolled state machine (more control, more code) — rejected per the user's
  orchestration decision, but the wrapper preserves the option.

## 5. Signal fusion (deterministic + LLM)

- **Decision**: `phonenumbers` parses/validates/normalizes contact data to E.164 and derives the
  region → `detected_country`; the LLM extracts the candidate value + interpretation. Fusion rule:
  deterministic result wins for the normalized value and country; agreement raises confidence,
  divergence lowers `confidence_score` and sets `needs_review`.
- **Rationale**: Directly implements Principle X and the brief's `final_normalized_text` (LLM+API
  fused) and `detected_country`; deterministic library is offline and reliable.
- **Alternatives**: A network geo/validation API — rejected for reliability, latency, and a key
  dependency; the tool interface allows adding one later.

## 6. Language detection (baseline for 001)

- **Decision**: `lingua-language-detector` as the deterministic detector, fused with the LLM's
  assessment; disagreement lowers `lang_confidence`. Baseline lock/fallback here; full policy in `002`.
- **Rationale**: High accuracy on short text for ES/EN/PT with confidence values; deterministic and
  offline.
- **Alternatives**: `langdetect`/`fasttext` (less accurate on short strings / heavier); LLM-only
  detection (non-deterministic, no independent cross-check for fusion).

## 7. Retrieval / grounding (hybrid RAG + advanced techniques)

- **Decision**: Hybrid retrieval — BM25 (`rank-bm25`, sparse) fused with dense embeddings (`openai`
  `text-embedding-3-small`, behind an `Embedder` seam) via Reciprocal Rank Fusion. Layered on the base
  retriever, individually config-gated: HyPE (index the hypothetical questions each doc answers), HyDE
  (draft a hypothetical answer as an extra query), RAG-Fusion (multi-phrasing + fuse), Self-Query (LLM
  extracts category/topic filters from the doc metadata), and an LLM reranker. Retrieved snippets are
  cited; nothing clearing the threshold → decline + `needs_review` (FR-006). Every enhancement degrades
  to the BM25 floor when no key/LLM is present.
- **Rationale**: A single lexical index misses paraphrases and cross-lingual synonyms; hybrid fusion +
  query expansion + metadata filtering + reranking materially lift grounding recall/precision (US1),
  while the offline BM25 floor keeps CI and the committed eval deterministic and keyless.
- **Alternatives**: Pure BM25 — kept as the deterministic floor, not the ceiling. Local
  `sentence-transformers` embeddings — rejected to keep the footprint light; the `Embedder` seam leaves
  it a drop-in. Parent-document retrieval and query decomposition — considered but not adopted at this
  KB scale; the retriever seam leaves them open.

## 8. Resilience

- **Decision**: `LLMClient` sets an explicit timeout, relies on the SDK's bounded retries with
  backoff (429/5xx/connection), repairs malformed/parse-failed output (one bounded re-ask, then fail
  closed), handles `stop_reason == "refusal"`, and falls back to a safe canned reply with
  `needs_review=true`. Typed exceptions (`RateLimitError`, `APITimeoutError`, `APIStatusError`,
  `APIConnectionError`, `BadRequestError`) are mapped to safe outcomes.
- **Rationale**: Implements Principle III and FR-017/018, SC-006 (no crash/hang; always a valid
  contract).
- **Alternatives**: Unbounded retries (latency risk) / crash-on-error (violates the contract) —
  rejected.

## 9. Observability & cost accounting

- **Decision**: A per-turn `Trace` with one `Span` per node (name, latency, status). Each LLM call
  records `usage` (input/output/cache tokens) and computes cost from a config pricing table;
  per-turn and per-conversation cost/latency are aggregated for `004`. Logs via `structlog`.
- **Rationale**: Implements Principle XI and FR-022; feeds the eval's latency/cost metrics; the +10
  observability bonus.
- **Alternatives**: OpenTelemetry — heavier than needed for the assessment; the `Trace` abstraction
  could export to OTel later.

## 10. Session state & memory

- **Decision**: `SessionStore` interface with an in-memory implementation holding `active_lang`
  (locked), collected onboarding slots, pending action, and a bounded recent-turn history.
- **Rationale**: Multi-turn coherence (FR-014/015) with a swap point for Redis/DB (Scalability).
- **Alternatives**: Global dict (not swappable, not thread-safe) — rejected.

## 11. Packaging, config, tooling

- **Decision**: `uv` + `pyproject.toml` with pinned deps; `pydantic-settings` loads a `config.yaml` +
  `.env`; `.env.example` documents `ANTHROPIC_API_KEY`. `ruff` + `mypy` + `pytest`.
- **Rationale**: Reproducible, typed, config-as-data (Future-Proofing); secrets via env (Security).
- **Alternatives**: `pip`/`requirements.txt` — fine, but `uv` is already available and faster/locked.

## 12. Knowledge ingestion pipeline

- **Decision**: A reproducible ingestion pipeline (`zapp-ingest`) builds the KB: validate
  (schema / language / duplication / coverage) → chunk → enrich → build index. Provider-dependent
  enrichment (HyPE questions, translation gap-fill) runs offline against the real provider, is cached
  and committed, and never runs on the serving path; the committed index rebuilds with no network/key.
- **Rationale**: Makes ingestion a first-class, traceable layer (Constitution VI/XI): the metadata and
  hypothetical questions that strengthen retrieval get in-repo provenance and deterministic
  reproducibility, rather than being hand-authored or produced ad hoc.
- **Alternatives**: Hand-authoring enriched JSON — rejected: not reproducible, error-prone, unvalidated.
  Generating enrichment at serving time — rejected: non-deterministic and adds latency, cost, and a key
  dependency to every turn.
