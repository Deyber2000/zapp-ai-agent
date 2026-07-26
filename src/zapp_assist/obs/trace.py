"""Observability: per-turn Trace with one Span per node plus token/latency/cost accounting.

(Constitution XI, FR-022.) The Trace is sufficient to debug and cost-account a turn from logs
alone, and is the signal source the `004` evaluation suite consumes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import ModelPricing
from ..llm.client import Usage

SpanStatus = Literal["ok", "error", "skipped"]


class Span(BaseModel):
    """One node execution: name, latency, status, and free-form attributes."""

    node: str
    latency_ms: float = 0.0
    status: SpanStatus = "ok"
    attrs: dict[str, Any] = Field(default_factory=dict)


class TokenTotals(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0


class Trace(BaseModel):
    """The per-turn trace: spans + aggregated tokens/cost/latency."""

    turn_id: str
    session_id: str
    spans: list[Span] = Field(default_factory=list)
    tokens: TokenTotals = Field(default_factory=TokenTotals)
    cost_usd: float = 0.0
    total_latency_ms: float = 0.0

    def add_span(self, span: Span) -> None:
        self.spans.append(span)

    def record_llm(self, usage: Usage, cost_usd: float) -> None:
        self.tokens.input += usage.input_tokens
        self.tokens.output += usage.output_tokens
        self.tokens.cache_read += usage.cache_read_input_tokens
        self.cost_usd += cost_usd


def compute_cost(input_tokens: int, output_tokens: int, pricing: ModelPricing) -> float:
    """Cost in USD from the config pricing table (per 1M tokens)."""

    return (
        input_tokens / 1_000_000 * pricing.input_per_1m
        + output_tokens / 1_000_000 * pricing.output_per_1m
    )
