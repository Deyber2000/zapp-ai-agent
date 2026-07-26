"""Guardrail registry (Constitution VIII: guardrails by default, Modularity).

Adding or changing a guardrail is a registration change; the orchestrator and nodes are untouched.
`run()` executes every guardrail for a stage and returns the non-`allow` decisions to record.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from ..contracts import GuardrailDecision


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


class GuardrailRegistry:
    def __init__(self) -> None:
        self._items: list[Guardrail] = []

    def register(self, guardrail: Guardrail) -> None:
        self._items.append(guardrail)

    def for_stage(self, stage: str) -> list[Guardrail]:
        return [g for g in self._items if g.stage == stage]

    def run(self, stage: str, ctx: GuardrailContext) -> list[GuardrailDecision]:
        decisions: list[GuardrailDecision] = []
        for guardrail in self.for_stage(stage):
            decision = guardrail.check(ctx)
            if decision is not None:
                decisions.append(decision)
        return decisions
