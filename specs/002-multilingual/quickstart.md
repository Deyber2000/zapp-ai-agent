# Quickstart & Validation: Multilingual Coherence & Language Policy (002)

How to run and prove `002` end-to-end. Interfaces are in [contracts/language.md](./contracts/language.md);
state/config in [data-model.md](./data-model.md).

## Prerequisites

- Same as `001`: Python 3.11+, `uv`. **No key needed** for the test suite (mock `LLMClient`; `lingua`
  detection is offline and deterministic). A live run (`zapp-assist chat`) needs `ANTHROPIC_API_KEY`.

## Automated checks

```bash
uv run pytest -q                                   # full suite (001 + 002), must stay green
uv run pytest tests/unit/test_switch_policy.py -q          # US2 sustained-switch / anti-thrash
uv run pytest tests/unit/test_reply_language_verify.py -q  # US1 verify: match / correct-once / fail-safe
uv run pytest tests/integration/test_us_multilingual.py -q # US1–US3 across ES/EN/PT
uv run ruff check . && uv run mypy src
```

## Validate each user story

| Story | Input / scenario | Expected outcome |
|-------|------------------|------------------|
| **US1** Verified reply | in-domain question in ES / EN / PT | reply is in the request language; trace `reply_match=true` |
| **US1** Wrong-language reply | force the model to answer in the wrong language | one correction re-ask; if still wrong → safe in-language message + `needs_review=true`; **never** the mismatched text (SC-002) |
| **US2** Coherence | multi-turn session in PT incl. short turns ("ok", "obrigado") | `active_lang` stays `pt`; 0 flips on weak turns (SC-003) |
| **US2** Sustained switch | ≥ `language_switch_turns` confident EN turns after a PT lock | `active_lang` switches to `en` (SC-004) |
| **US2** One-off phrase | a single EN phrase inside a PT session | `active_lang` stays `pt` (SC-004) |
| **US3** Unsupported | a message in French | reply in fallback (`en`) + `needs_review=true`; never a French reply (SC-005) |
| **US3** Low-confidence | very short/ambiguous input | keep active (or fallback); safe reply; no asserted uncertain language |
| **US4** Fidelity signals | any turn | trace exposes `detected`, `active`, `confidence`, `reply_lang`, `reply_match` (SC-006) |

## How the tests drive it (deterministic, no network)

- **Detection & verification** run on real `lingua` — ES/EN/PT sentences are chosen to clear the
  confidence thresholds (as in `001`'s language tests); short strings exercise the `reply_verify_min_chars`
  skip and the switch-policy reset.
- **Wrong-language reply** is simulated by scripting the mock `LLMClient` to return a reply in the wrong
  language, then (for the correction re-ask) either a corrected reply or a still-wrong reply, to exercise
  both the corrected and fail-safe paths.
- **Switch policy** is unit-tested through the pure policy function (C3) with explicit
  `(active, detected, confidence, pending…)` inputs — no graph needed — plus an integration test that
  drives real turns.

## What "done" means for 002

- All acceptance scenarios in `spec.md` pass; **every `001` test still passes** and the `001` contract
  is unchanged (FR-014).
- Reply-language verification guarantees in-language replies or a safe flagged result (SC-001/002).
- The switch policy persists language across weak turns and switches only on sustained intent
  (SC-003/004); unsupported/low-confidence degrades safely (SC-005).
- Per-turn language-fidelity signals are present in the trace for `004` (SC-006).
- Thresholds and supported languages are config-driven (no hardcoding); gate green (ruff/mypy/pytest).
