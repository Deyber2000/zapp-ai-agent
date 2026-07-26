# Contracts: Multilingual Coherence & Language Policy (002)

Internal interface contracts for this feature. These are library-internal (node + policy + trace)
contracts, not external APIs. **The external `001` `TurnResult` contract is unchanged** (FR-014).

## C1 — `detect_language` node (behavior change, same signature)

`detect_language(state, deps) -> state` — unchanged signature; the **switch policy** replaces the
lock-forever behaviour.

**Preconditions**: runs after `guardrail_in`; may run on a blocked turn (language still needed for the
decline language).

**Postconditions**:
- `state.language` set via the existing deterministic `lingua` + LLM `fuse()` (deterministic wins).
- `state.session.active_lang` set per the transition table in [data-model.md §1]:
  - first confident supported detection **locks** it;
  - a **sustained** switch (`language_switch_turns` consecutive confident supported turns in a new
    language) updates it;
  - weak/short/mixed/matching turns **keep** it and reset the pending accumulator.
- `state.session.pending_switch_lang` / `pending_switch_count` updated (bounded).
- Span `detect_language` records `{detected, active, confidence, switched, pending}`.

**Invariants**: `active_lang` only changes to a supported language; a single foreign phrase never
switches; deterministic detection is authoritative for the language choice (Principle X).

## C2 — `verify_reply_language` node (NEW)

`verify_reply_language(state, deps) -> state` — stateless node, inserted after answer-producing nodes,
before `verify_confidence`.

**Skip conditions** (record a `skipped` span, no change): `state.degraded`, `state.blocked`, no
`draft_reply`, or `len(draft_reply) < reply_verify_min_chars` (record `skipped_short=true`,
`reply_match=true`).

**Behavior**:
1. `reply_lang = deterministic_detect(draft_reply)` (offline; no LLM).
2. If `reply_lang == active_lang` → `reply_match=true`; done.
3. Else → **one** LLM correction re-ask (existing adapter) to rewrite `draft_reply` in `active_lang`;
   set `reply_corrected=true`; re-detect.
   - If it now matches → keep the corrected reply, `reply_match=true`.
   - Else (still mismatched or correction degraded) → replace `draft_reply` with the per-language safe
     template, set `reply_match=false` and `needs_review_override=true`.
4. Record span `verify_reply_language` with `{active, reply_lang, reply_match, corrected, skipped_short}`.

**Postconditions**: `draft_reply` is in `active_lang` **or** the turn is flagged `needs_review` with a
safe in-language message. Never emits reply text whose detected language ≠ `active_lang` for a verified
(non-short) reply.

**Bounds**: at most one LLM call; never loops; never raises (node-runner degrades on exception).

## C3 — Switch-policy function (pure, unit-testable)

A pure helper (no I/O) that, given `(active_lang, detected_lang, confidence, pending_lang,
pending_count, config)`, returns `(new_active_lang, new_pending_lang, new_pending_count, switched)`.
Deterministic; the sole owner of the transition table in data-model §1. `detect_language` calls it.

## C4 — Trace signal schema (for `004`)

Language-fidelity signals are span attributes (no new types), sufficient to compute a language-fidelity
rate over any run without inspecting reply text:

```jsonc
// span "detect_language"
{ "detected": "es", "active": "es", "confidence": 0.94, "switched": false, "pending": null }
// span "verify_reply_language"
{ "active": "es", "reply_lang": "es", "reply_match": true, "corrected": false, "skipped_short": false }
```

## C5 — Compatibility contract

- `TurnResult` fields, types, and validation are **unchanged**; `final_normalized_text`,
  `detected_country`, `guardrails`, etc. behave exactly as in `001`.
- `detected_lang` / `active_lang` / `lang_confidence` are still populated the same way (now via the
  switch policy, but same fields and ranges).
- All existing `001` tests MUST continue to pass unchanged.
