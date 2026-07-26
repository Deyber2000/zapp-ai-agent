"""Guardrail registry (Constitution VIII: guardrails by default, Modularity).

Adding or changing a guardrail is a registration change; the orchestrator and nodes are untouched.
`run()` executes every guardrail for a stage and returns the non-`allow` decisions to record.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import GuardrailDecision, TurnResult


class GuardrailContext(BaseModel):
    """Everything a guardrail may inspect for a given stage."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    stage: str
    user_text: str = ""
    draft_reply: str | None = None
    active_lang: str = "en"
    retrieval: Any = None  # list[KnowledgeDocument] | None on the output stage


@runtime_checkable
class Guardrail(Protocol):
    id: str
    stage: str

    def check(self, ctx: GuardrailContext) -> GuardrailDecision | None: ...


# Action precedence for "most severe governs" (003): higher wins when several rules fire.
_ACTION_ORDER = {"allow": 0, "redact": 1, "escalate": 2, "refuse": 3}


def governing_action(decisions: list[GuardrailDecision]) -> str:
    """The most-severe action across a stage's decisions (allow < redact < escalate < refuse)."""

    return max(
        (d.action for d in decisions), key=lambda a: _ACTION_ORDER[a], default="allow"
    )


class GuardrailSummary(BaseModel):
    """A turn's guardrail decisions flattened for the 004 eval (by category and by layer)."""

    total: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    by_layer: dict[str, int] = Field(default_factory=dict)
    decisions: list[GuardrailDecision] = Field(default_factory=list)


def guardrail_summary(result: TurnResult) -> GuardrailSummary:
    """Flatten a turn's input+output guardrail decisions for precision/recall aggregation (004)."""

    decisions = [*result.guardrails.input, *result.guardrails.output]
    by_category: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    for decision in decisions:
        by_category[decision.category] = by_category.get(decision.category, 0) + 1
        by_layer[decision.layer] = by_layer.get(decision.layer, 0) + 1
    return GuardrailSummary(
        total=len(decisions), by_category=by_category, by_layer=by_layer, decisions=decisions
    )


class GuardrailRegistry:
    """Deterministic rules + an optional semantic classifier (003). `run` fuses the two layers.

    `semantic` is duck-typed (has `.enabled: bool` and `.classify(stage, ctx) -> list[...]`,
    `.degraded: bool`) to avoid a module cycle with `semantic.py`, which imports this registry.
    """

    def __init__(self, semantic: Any = None) -> None:
        self._items: list[Guardrail] = []
        self._semantic = semantic
        self.semantic_degraded = False

    def register(self, guardrail: Guardrail) -> None:
        self._items.append(guardrail)

    def for_stage(self, stage: str) -> list[Guardrail]:
        return [g for g in self._items if g.stage == stage]

    def run(self, stage: str, ctx: GuardrailContext) -> list[GuardrailDecision]:
        # Deterministic layer first (authoritative for known patterns, Principle X)...
        decisions: list[GuardrailDecision] = []
        for guardrail in self.for_stage(stage):
            decision = guardrail.check(ctx)
            if decision is not None:
                decisions.append(decision)
        # ...then the optional semantic layer (additive; each decision tagged layer="semantic").
        self.semantic_degraded = False
        if self._semantic is not None and self._semantic.enabled:
            decisions.extend(self._semantic.classify(stage, ctx))
            self.semantic_degraded = bool(getattr(self._semantic, "degraded", False))
        return decisions
