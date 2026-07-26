# Implementation Plan: Multilingual Coherence & Language Policy

**Branch**: `002-multilingual` | **Date**: 2026-07-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-multilingual/spec.md`

## Summary

Deepen the baseline language handling shipped inline in `001` into a coherent, verified multilingual
policy — **without changing the `001` turn contract**. Three mechanisms:

1. **Reply-language verification** — a new stateless node runs the *deterministic* detector on the
   draft reply; on a mismatch with `active_lang` it makes exactly **one** LLM correction re-ask, then
   re-checks; a persistent mismatch is replaced by a safe in-language message with `needs_review=true`.
2. **Sustained-switch policy** — `detect_language` + a small bounded switch-state on the `Session` so a
   locked `active_lang` changes only after the user sends confident input in a different supported
   language for `language_switch_turns` consecutive turns; short/mixed/low-confidence turns keep the
   lock (no thrash).
3. **Language-fidelity signals** — per-turn language facts (detected, active, confidence, reply-lang,
   reply-match) are emitted as **trace span attributes** for the `004` eval suite. The frozen `001`
   `TurnResult` contract is untouched.

All detection/verification is deterministic (`lingua`, offline); the only LLM use is the single bounded
correction re-ask through the existing adapter. Reuses `lang/detector.py`, the `detect_language` node,
the session `active_lang` lock, config-as-data thresholds, the node-runner degradation model, and the
`Trace`.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: existing only — `pydantic` v2, `langgraph` (isolated in `graph/build.py`),
`lingua-language-detector`, the Anthropic adapter (isolated). **No new dependencies.**

**Storage**: in-memory session store (existing `SessionStore` interface); switch-state fields added to
`Session`.

**Testing**: `pytest` with the existing mock `LLMClient` (no network); deterministic `lingua` drives
detection and reply verification.

**Target Platform**: Linux/macOS server-side library + CLI (existing `zapp-assist`).

**Project Type**: single project (library + CLI), extends the `001` agent core.

**Performance Goals**: reply verification adds no LLM call on the happy path (deterministic check only);
at most **one** extra LLM call per turn when a correction is required.

**Constraints**: must not break the `001` contract or any `001` test; deterministic-wins for the
language choice (Principle X); bounded correction (exactly one re-ask); config-driven thresholds and
supported set; offline detection.

**Scale/Scope**: ES/EN/PT (config-extensible); ~1 new node, ~2 new `Session` fields, ~3 new config
thresholds, per-language verification templates, and unit + integration tests.

## Constitution Check

*GATE: passes before Phase 0 and re-checked after Phase 1.*

- **I Scalability** — switch-state is bounded (a language + a small counter) on the swappable
  `SessionStore`; no unbounded growth. ✅
- **II Modularity** — new behaviour is one stateless node (`verify_reply_language`) + a pure policy
  function; LangGraph stays isolated in `build.py`; no vendor leak into nodes. ✅
- **III Resilience & Security** — the correction is a single bounded re-ask; a degraded correction or a
  persistent mismatch fails safe to an in-language template + `needs_review`; no crash. ✅
- **IV Continuous Learning** — thresholds (lock/switch/verify) are config, tunable from eval feedback;
  fidelity signals feed `004`. ✅
- **V Future-Proofing** — supported languages + thresholds are config; adding a language needs no policy
  code change. ✅
- **VI Spec-Driven & Traceable** — this plan derives from `spec.md`; commits stay spec-before-code. ✅
- **VII Structured Validated Output Contract** — the `001` `TurnResult` is **unchanged**; fidelity
  signals ride in the trace, not the contract (FR-014). ✅
- **VIII Guardrails Fail-Safe** — output guardrails still run after verification; a persistent mismatch
  yields a safe reply, never mismatched content. ✅
- **IX Multilingual Coherence** — this feature *is* Principle IX: verified in-language replies + a
  non-thrashing switch policy. ✅
- **X Signal Fusion & Deterministic Safety** — the deterministic detector decides the language of both
  the message and the reply; the LLM only proposes and (once) rewrites. ✅
- **XI Observability & Eval-Driven Verification** — per-turn language-fidelity signals as span
  attributes; one span per node preserved. ✅

**No violations.** Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/002-multilingual/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — session switch-state, config, trace signals
├── quickstart.md        # Phase 1 — how to validate US1–US4
├── contracts/
│   └── language.md      # node + policy + trace-signal contracts (internal interfaces)
└── tasks.md             # Phase 2 — /speckit-tasks (not created here)
```

### Source Code (repository root) — files this feature touches

```text
src/zapp_assist/
├── lang/
│   └── detector.py            # + language-of-reply helper reuse; fuse() unchanged
├── graph/
│   ├── build.py               # insert verify_reply_language before guardrail_out
│   ├── state.py               # (no contract change) carry reply-check result for the trace
│   ├── nodes/
│   │   ├── detect_language.py # apply the sustained-switch policy (was: lock-forever)
│   │   ├── verify_reply_language.py   # NEW node: deterministic reply check + 1 correction
│   │   └── _util.py           # + per-language "let me answer in your language" templates
├── memory/
│   └── session_store.py       # + pending_switch_lang / pending_switch_count on Session
└── config.py                  # + language_switch_min_confidence / _turns / reply_verify_min_chars

config.yaml                    # add the three thresholds under `thresholds`

tests/
├── unit/
│   ├── test_switch_policy.py          # NEW: lock/persist/switch/anti-thrash
│   └── test_reply_language_verify.py  # NEW: match / correct-once / fail-safe
└── integration/
    └── test_us_multilingual.py        # NEW: US1–US3 across ES/EN/PT
```

**Structure Decision**: extend the existing single-project `001` layout in place — one new node, one
new policy function, additive `Session`/config fields, and new tests. No new top-level modules; the
`001` contract, adapter isolation, and LangGraph isolation are preserved.

## Complexity Tracking

*No constitution violations — no entries.*
