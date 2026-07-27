# Zapp Assist — Evaluation Report

**Overall: ✅ PASS**  ·  cases: 20  ·  _deterministic core + live LLM-judged quality tier (deepeval)_

## Metrics

| Metric | Score | Threshold | Result |
| --- | --- | --- | --- |
| task_success | 1.0 (20/20 cases) | ≥ 0.9 | PASS |
| language_fidelity | 1.0 (20/20 in expected language) | ≥ 0.95 | PASS |
| guardrail_recall | 1.0 (TP=4 FN=0) | ≥ 0.9 | PASS |
| guardrail_precision | 1.0 (TP=4 FP=0) | ≥ 0.9 | PASS |
| judge_quality | 4.888 (avg of 20 (out of 5)) | ≥ 3.5 | PASS |
| latency_p95_ms | 20.309 (per-turn p95) | ≤ 5000.0 | PASS |
| cost_per_convo | 0.002565 (mean per case) | ≤ 0.05 | PASS |
| llm_judge_quality | 4.588 (LLM-as-judge over 20 live replies (out of 5)) | ≥ 3.5 | PASS |
| rag_faithfulness | 0.938 (deepeval, 4 grounded cases [0-1]) | ≥ 0.7 | PASS |
| rag_contextual_relevancy | 0.356 (deepeval, 5 grounded cases [0-1]) | ≥ 0.2 | PASS |

## Operational

- latency p50: 5.822 ms · p95: 20.309 ms
- estimated cost / conversation: $0.002565

## Task success by capability

- action: 1.0
- guardrail: 1.0
- multilingual: 1.0
- onboarding: 1.0
- out_of_scope: 1.0
- support: 1.0

## Judge rubric (deterministic proxy)

- rule-based average: 4.888 / 5 (helpfulness, groundedness, safety, language)
- the real LLM-as-judge (temperature 0) is `llm_judge_quality` in the metrics table,
  populated when a key is present (the key-adaptive quality tier).
