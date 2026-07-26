"""Observability: per-turn Trace with one Span per node plus token/latency/cost accounting.

(Constitution XI, FR-022.) The Trace is sufficient to debug and cost-account a turn from logs
alone, and is the signal source the `004` evaluation suite consumes.
"""

from __future__ import annotations

from collections.abc import Iterable
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


class LanguageFidelity(BaseModel):
    """Aggregated language-fidelity over a set of turn traces (002 → consumed by the 004 eval)."""

    turns: int = 0
    verified: int = 0  # turns whose reply language was actually checked (not skipped-short)
    matched: int = 0  # verified turns whose reply was in the active language
    rate: float = 1.0  # matched / verified (1.0 when nothing needed verifying)


def language_fidelity(traces: Iterable[Trace]) -> LanguageFidelity:
    """Compute the language-fidelity rate from turn traces (FR-011/012).

    Reads the `verify_reply_language` span's `reply_match` attribute — present only on turns whose
    reply was actually verified (short replies are skipped). Needs no reply-text inspection.
    """

    turns = verified = matched = 0
    for trace in traces:
        turns += 1
        for span in trace.spans:
            if span.node == "verify_reply_language" and "reply_match" in span.attrs:
                verified += 1
                if span.attrs["reply_match"]:
                    matched += 1
    rate = matched / verified if verified else 1.0
    return LanguageFidelity(turns=turns, verified=verified, matched=matched, rate=round(rate, 4))
