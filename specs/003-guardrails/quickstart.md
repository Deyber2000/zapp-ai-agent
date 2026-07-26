# Quickstart & Validation: Guardrails Taxonomy & Policy (003)

How to run and prove `003` end-to-end. Interfaces are in [contracts/guardrails.md](./contracts/guardrails.md);
taxonomy/policy in [data-model.md](./data-model.md).

## Prerequisites

- Same as `001`: Python 3.11+, `uv`. **No key needed** for tests (mock `LLMClient`; the semantic layer
  is scripted and off by default). A live run needs `ANTHROPIC_API_KEY`.

## Automated checks

```bash
uv run pytest -q                                    # full suite (001 + 002 + 003), must stay green
uv run pytest tests/unit/test_guardrail_policy.py -q       # US3 config policy + action precedence
uv run pytest tests/unit/test_semantic_layer.py -q         # US1 semantic fusion + degrade-on-error
uv run pytest tests/integration/test_us3_guardrails.py -q  # US1/US2/US3 end-to-end
uv run ruff check . && uv run mypy src
```

## Validate each user story

| Story | Input / scenario | Expected outcome |
|-------|------------------|------------------|
| **US1** Known pattern | a keyword injection ("ignore your instructions...") | refused by the **deterministic** layer regardless of the semantic toggle; decision `layer=deterministic` |
| **US1** Paraphrase | an obfuscated injection the regex misses, semantic **on** | refused by the **semantic** layer; decision `layer=semantic`, category `prompt_injection` |
| **US1** Genuine | a support question with a trigger-like phrase, semantic off | allowed and processed (no false block) |
| **US2** PII output | a draft reply containing an email / long number | redacted before return; `guardrails.output` records `pii_leak` |
| **US2** Disclosure | a draft reply that would reveal internal instructions | replaced with a safe decline + `needs_review` |
| **US3** Disable rule | disable a rule in config | that rule no longer fires on the same input |
| **US3** Override action | change a rule's action (redact → refuse) in config | the new action governs |
| **US3** Toggle semantic | set `semantic_enabled: false` | only the deterministic layer runs (no semantic calls) |

## How the tests drive it (deterministic, no network)

- The **deterministic** layer runs exactly as in `001` (regex). Existing `001` guardrail behavior is the
  default, so all `001` tests pass unchanged.
- The **semantic** layer is enabled per-test via a config override and its classification is scripted on
  the mock `LLMClient` (a `SafetyAssessment` result), including a degraded result to exercise the
  fail-safe (degrade-to-deterministic + `needs_review`).
- **Policy** changes are exercised by constructing an `AppConfig` with a `guardrails` block (disable a
  rule / override an action / toggle the semantic layer) — no code change.

## What "done" means for 003

- All acceptance scenarios in `spec.md` pass; **every `001`/`002` test still passes**; the
  `guardrails.input`/`output` contract lists are unchanged (additive decision fields only).
- Layered detection catches obfuscated attacks (semantic) and known patterns (deterministic), with low
  false positives on genuine turns (SC-001/002); blocked turns never leak content (SC-003); output PII
  redacted (SC-004); semantic failure degrades safely (SC-005).
- Policy is fully config-driven (SC-006); every decision exposes rule/category/severity/action/layer
  for `004` (SC-007). Gate green (ruff/mypy/pytest).
