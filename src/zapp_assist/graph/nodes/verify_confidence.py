"""Confidence verification node (FR-008/016).

Combines the available signals (language, intent, grounding, fusion) into one score and decides
`needs_review`: below the configured threshold, on degradation, on signal divergence, or when an
upstream node explicitly flagged the turn.
"""

from __future__ import annotations

from ..deps import Deps
from ..state import ConfidenceAssessment, TurnState
from ._util import add_span, now


def verify_confidence(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    threshold = deps.config.thresholds.review_confidence

    components: dict[str, float] = {}
    if state.language is not None:
        components["language"] = state.language.lang_confidence
    if state.intent_confidence is not None:
        components["intent"] = state.intent_confidence
    if state.grounding_confidence is not None:
        components["grounding"] = state.grounding_confidence
    if state.normalization is not None:
        components["fusion"] = 1.0 if state.normalization.agrees else 0.3

    score = sum(components.values()) / len(components) if components else 0.0

    reasons: list[str] = []
    review = False
    if score < threshold:
        review = True
        reasons.append("below_confidence_threshold")
    if state.degraded:
        review = True
        reasons.append("degraded_dependency")
    if state.needs_review_override:
        review = True
        reasons.append("flagged_for_review")
    if state.normalization is not None and not state.normalization.agrees:
        review = True
        reasons.append("signal_divergence")

    state.confidence = ConfidenceAssessment(
        score=round(score, 4), components=components, reasons=reasons
    )
    state.needs_review = review

    add_span(
        state.trace,
        "verify_confidence",
        start,
        attrs={"score": state.confidence.score, "needs_review": review},
    )
    return state
