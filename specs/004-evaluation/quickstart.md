# Quickstart & Validation: Evaluation Suite (004)

How to run the eval and prove `004` end-to-end. Interfaces are in [contracts/eval.md](./contracts/eval.md);
schemas in [data-model.md](./data-model.md).

## Prerequisites

- Same as the agent: Python 3.11+, `uv`. **No key or network needed** for the default run (scripted
  per-case model + rule-based judge). A `--live` run needs `ANTHROPIC_API_KEY`.

## Run the eval (one command)

```bash
uv run zapp-eval                    # deterministic: runs the dataset, writes evals/report.{json,md}
echo $?                             # 0 if all thresholds pass, non-zero if any fail (CI gate)

uv run zapp-eval --live            # optional: real provider + LLM judge (needs ANTHROPIC_API_KEY)
```

Expected: a printed summary table (each metric: score / threshold / PASS|FAIL + overall), and
`evals/report.json` + `evals/report.md` written (matching the committed ones on a clean tree).

## Automated checks

```bash
uv run pytest -q                                  # full suite (001-003 + eval unit tests) stays green
uv run pytest tests/unit/test_eval_metrics.py -q         # metric math (task/precision-recall/percentile/fidelity)
uv run pytest tests/unit/test_eval_runner.py -q          # tiny dataset → report; threshold flips exit/overall
uv run ruff check . && uv run mypy src evals
```

## Validate each user story

| Story | Scenario | Expected outcome |
|-------|----------|------------------|
| **US1** one command / CI gate | `uv run zapp-eval` | one report (json + md), per-metric + overall pass/fail; exit 0 all-pass, non-zero on any fail |
| **US1** error isolation | a case that raises | recorded as a task-success failure; the run still completes |
| **US2** task success | labeled outcome cases | rate = matches / cases, reported with pass/fail |
| **US2** language fidelity | ES/EN/PT expected-language cases | share of replies in the expected language |
| **US2** guardrail P/R | labeled safe/unsafe cases | precision + recall from recorded guardrail decisions vs labels |
| **US3** judge | agent replies | 1–5 per rubric dimension; aggregate quality; reproducible (committed = rule-based) |
| **US4** ops + config | traces + thresholds | latency p50/p95 + cost/convo; changing a threshold flips pass/fail, no code change |
| **US4** committed report | inspect repo | `evals/report.json` + `report.md` present, match a fresh deterministic run |

## How it stays deterministic (no network)

- Each case carries a `MockScript`; the runner builds a per-case scripted `LLMClient` (eval-owned) so
  the agent runs identically every time.
- The default judge is rule-based (deterministic). `--live` swaps in the real provider + LLM judge.
- Correctness metrics (task success, fidelity, guardrail P/R, judge) are byte-stable across runs; only
  latency values are environment-dependent (informational, for regression comparison).

## What "done" means for 004

- `uv run zapp-eval` produces one report over the labeled dataset with all five metric families and a
  correct exit code (SC-001/002/003/005).
- Thresholds are config-driven (SC-006); the committed report is reproducible with no key/network
  (SC-004/007).
- **0 changes to `src/zapp_assist/`**; all 101 existing tests still pass; gate green (ruff/mypy/pytest).
