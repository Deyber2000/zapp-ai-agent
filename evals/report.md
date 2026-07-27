# Zapp Assist — Evaluation Report

**Overall: ✅ PASS**  ·  cases: 13  ·  _deterministic (scripted model + rule-based judge)_

## Metrics

| Metric | Score | Threshold | Result |
| --- | --- | --- | --- |
| task_success | 1.0 (13/13 cases) | ≥ 0.9 | PASS |
| language_fidelity | 1.0 (13/13 in expected language) | ≥ 0.95 | PASS |
| guardrail_recall | 1.0 (TP=4 FN=0) | ≥ 0.9 | PASS |
| guardrail_precision | 1.0 (TP=4 FP=0) | ≥ 0.9 | PASS |
| judge_quality | 4.827 (avg of 13 (out of 5)) | ≥ 3.5 | PASS |
| latency_p95_ms | 24.096 (per-turn p95) | ≤ 5000.0 | PASS |
| cost_per_convo | 0.002215 (mean per case) | ≤ 0.05 | PASS |

## Operational

- latency p50: 9.105 ms · p95: 24.096 ms
- estimated cost / conversation: $0.002215

## Task success by capability

- action: 1.0
- guardrail: 1.0
- multilingual: 1.0
- onboarding: 1.0
- out_of_scope: 1.0
- support: 1.0

## LLM-as-judge

- average rubric score: 4.827 / 5
