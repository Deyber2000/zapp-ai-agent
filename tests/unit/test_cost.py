"""Unit tests for cost accounting (Constitution XI, FR-022).

`compute_cost` reflects the config pricing table; `Trace.record_llm` aggregates tokens and cost
across the multiple LLM calls a single turn makes.
"""

from __future__ import annotations

import pytest

from zapp_assist.config import ModelPricing
from zapp_assist.llm.client import Usage
from zapp_assist.obs.trace import Trace, compute_cost

_PRICING = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)


def test_compute_cost_matches_pricing_table() -> None:
    # 1M input @ $3 + 1M output @ $15 = $18.
    assert compute_cost(1_000_000, 1_000_000, _PRICING) == pytest.approx(18.0)


def test_compute_cost_scales_with_partial_tokens() -> None:
    expected = 1000 / 1_000_000 * 3.0 + 500 / 1_000_000 * 15.0
    assert compute_cost(1000, 500, _PRICING) == pytest.approx(expected)


def test_trace_record_llm_aggregates_tokens_and_cost() -> None:
    trace = Trace(turn_id="t", session_id="s")
    trace.record_llm(Usage(input_tokens=90, output_tokens=45), 0.0009)
    trace.record_llm(Usage(input_tokens=10, output_tokens=5), 0.0001)

    assert trace.tokens.input == 100
    assert trace.tokens.output == 50
    assert trace.cost_usd == pytest.approx(0.001)
