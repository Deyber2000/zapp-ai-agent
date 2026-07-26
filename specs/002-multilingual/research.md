# Research: Multilingual Coherence & Language Policy (002)

Phase 0 decisions. Each: **Decision → Rationale → Alternatives considered**. Everything reuses the
`001` stack; no new dependencies.

## R1 — Reply-language verification: deterministic check + one bounded correction

**Decision**: After a reply is drafted, run the deterministic `lingua` detector on the *reply text*.
If its language ≠ `active_lang`, make exactly **one** LLM re-ask to rewrite the reply in `active_lang`,
then re-check deterministically. If it still mismatches (or the correction is degraded), replace the
reply with a per-language safe template and set `needs_review=true`. Record the outcome in the trace.

**Rationale**: Turns "reply in the user's language" from a *request* (what `001` does via the system
prompt) into a *verified guarantee* (FR-004/005). The check itself uses no LLM (offline, free,
deterministic — Principle X); only a genuine mismatch spends one bounded correction (Principle III,
mirrors the adapter's single repair re-ask). Fail-safe on persistent mismatch avoids ever shipping
mismatched text (SC-002).

**Alternatives considered**: (a) *LLM-judge the language* — rejected: slower, costlier, non-deterministic
for a decision a detector makes reliably. (b) *Trust the prompt, no verification* — rejected: that is
exactly the `001` gap this feature closes. (c) *Loop corrections until match* — rejected: unbounded;
one re-ask then fail-safe is the resilient bound.

## R2 — Fidelity signals ride in the trace, not the contract

**Decision**: Emit `detected_lang`, `active_lang`, `lang_confidence`, `reply_lang`, and `reply_match`
as **span attributes** on the trace (detect_language + verify_reply_language spans). Do **not** add a
field to `TurnResult`.

**Rationale**: The `001` contract is frozen (`extra="forbid"`) and already merged; FR-014 requires not
breaking it. The `004` eval suite consumes the trace anyway (that is its purpose, per `001` FR-022).
Keeping the signal in the trace is the least-coupling, contract-safe choice.

**Alternatives considered**: (a) *Add `reply_match` to `TurnResult`* — rejected: changes a frozen
contract for a signal only evaluation needs, not callers. (b) *Separate side-channel log* — rejected:
the trace already exists and is the designated eval signal source.

## R3 — Sustained-switch policy: consecutive-confident-turns counter

**Decision**: Keep the `001` lock (first confident supported detection locks `active_lang`). Add two
bounded fields to `Session`: `pending_switch_lang` and `pending_switch_count`. On each turn, if the
deterministic detection is a **supported** language, **different** from `active_lang`, with confidence
≥ `language_switch_min_confidence`: if it equals `pending_switch_lang`, increment the count, else start
a new pending at count 1. When the count reaches `language_switch_turns` (default 2), switch
`active_lang` and clear the pending state. Any turn that matches `active_lang`, or is weak/short/mixed,
**resets** the pending state.

**Rationale**: Directly encodes "switch only on sustained, confident intent; never thrash on a one-off"
(FR-007/008, SC-003/004). A counter is O(1) state, deterministic, and trivially testable. Resetting on
a matching/weak turn is what makes a single foreign phrase a no-op.

**Alternatives considered**: (a) *Rolling window of last N langs* — equivalent but heavier state;
the counter is the minimal form of the same idea. (b) *Switch immediately on any confident different
lang* — rejected: thrashes on borrowed words/quotes (fails SC-004). (c) *Never switch (pure `001`
lock)* — rejected: fails the deliberate-switch user story (US2).

## R4 — Short-reply handling in verification (avoid false mismatches)

**Decision**: Skip reply verification when the draft reply is shorter than `reply_verify_min_chars`
(default ~15 chars). Very short replies (e.g. "OK", "Listo") are unreliable for any detector; treat
them as matching and record `reply_match=true` (unverified-short) in the trace.

**Rationale**: `lingua` (like any detector) is unreliable on 1–2 word text; verifying it would produce
false mismatches and needless corrections. The templates the agent emits are per-language by
construction, so short canned replies are already in-language. Config-driven so it is tunable.

**Alternatives considered**: (a) *Always verify* — rejected: false positives on short replies trigger
pointless corrections. (b) *Word-count gate* — equivalent; a char threshold is simpler and language-
neutral.

## R5 — Node placement in the graph

**Decision**: Insert `verify_reply_language` **after** the answer-producing nodes and **before**
`verify_confidence` → `guardrail_out` → `assemble`. It reads/writes `draft_reply` and may set
`needs_review_override`, which `verify_confidence` then folds into the final decision.

**Rationale**: Verification must see the produced `draft_reply` and its `needs_review` contribution must
be visible to `verify_confidence`. Running before `guardrail_out` means output guardrails still apply to
the final (possibly corrected) reply. It is skipped cleanly when the turn is degraded/blocked or has no
draft reply (same skip-on-degraded discipline as every node).

**Alternatives considered**: (a) *Inside each answer node* — rejected: duplicates logic across
support/onboarding/action/out_of_scope; a single node is DRY and centralizes the guarantee. (b) *After
`guardrail_out`* — rejected: a correction after guardrails would bypass output guardrail checks on the
rewritten text.

## R6 — Detection reuse (no new dependency)

**Decision**: Reuse `LinguaDetector`/`lang.detector` for both message and reply detection; the existing
`fuse()` stays unchanged for message-language fusion. Add a thin helper to detect the language of an
arbitrary string (the reply) with the same supported set.

**Rationale**: One detector, one supported set, one code path — consistent and offline. No new library.

**Alternatives considered**: adding a second detection library — rejected as needless coupling and
inconsistency.

## Summary of config additions (config-as-data, Principle V)

| Key (under `thresholds`) | Default | Meaning |
|---|---|---|
| `language_switch_min_confidence` | 0.75 | deterministic confidence floor for a turn to count toward a switch |
| `language_switch_turns` | 2 | consecutive confident turns in a new supported language required to switch |
| `reply_verify_min_chars` | 15 | replies shorter than this skip verification (treated as in-language) |

`language_lock` (0.75, existing) remains the floor to first-lock `active_lang`. Supported languages and
fallback stay in the existing `languages` config block.
