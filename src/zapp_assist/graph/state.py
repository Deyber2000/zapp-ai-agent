"""TurnState — the object threaded through the graph (contracts/nodes.md).

Nodes are stateless handlers `node(state, deps) -> state`; they read/write only `TurnState` and the
injected `Deps`. No node imports LangGraph or the Anthropic SDK. Internal helper flags (`blocked`,
`degraded`, review override, per-signal confidences) are not part of the external contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from ..contracts import GuardrailDecision, TurnResult
from ..lang.detector import LanguageResult
from ..memory.session_store import Session
from ..obs.trace import Trace

if TYPE_CHECKING:  # avoid importing rank_bm25 at graph-state import time
    from ..rag.store import KnowledgeDocument

Intent = Literal["support", "onboarding", "action", "out_of_scope", "clarify", "smalltalk"]


class NormalizationSignal(BaseModel):
    """Deterministic-vs-LLM fusion signal (populated by US2; defined here for typing)."""

    raw: str
    canonical: str | None = None
    country: str | None = None
    valid: bool = False
    llm_value: str | None = None
    agrees: bool = True


class ConfidenceAssessment(BaseModel):
    """Combined per-turn confidence with its contributing components (FR-016)."""

    score: float
    components: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


@dataclass
class TurnState:
    turn_id: str
    session: Session
    user_text: str
    trace: Trace

    # progressive signals (None until the owning node runs)
    language: LanguageResult | None = None
    intent: Intent | None = None
    normalization: NormalizationSignal | None = None
    retrieval: list[KnowledgeDocument] | None = None
    confidence: ConfidenceAssessment | None = None
    guardrails_in: list[GuardrailDecision] = field(default_factory=list)
    guardrails_out: list[GuardrailDecision] = field(default_factory=list)
    draft_reply: str | None = None
    result: TurnResult | None = None

    # internal control/help flags (not part of the external contract)
    blocked: bool = False
    degraded: bool = False
    needs_review: bool = False
    needs_review_override: bool = False
    grounding_confidence: float | None = None
    intent_confidence: float | None = None

    # reply-language verification (002); transient, surfaced only in the trace (not the contract)
    reply_lang: str | None = None
    reply_match: bool | None = None
    reply_corrected: bool = False
    # True only when `draft_reply` is free text the model generated (support_rag's grounded answer).
    # Template-composed replies are correct-by-construction in `active_lang`, so they skip the
    # (offline, lingua-based) reply-language check — which confuses es/pt on short strings and could
    # otherwise overwrite a valid reply (e.g. a completed action's confirmation) with a review note.
    reply_from_model: bool = False
