"""Stateless graph nodes. Each is `node(state, deps) -> state` and appends exactly one Span."""

from __future__ import annotations

from .assemble import assemble
from .detect_language import LangSignal, detect_language
from .guardrail_in import guardrail_in
from .guardrail_out import guardrail_out
from .placeholder import placeholder
from .route_intent import IntentSignal, route_intent
from .support_rag import GroundedAnswer, support_rag
from .verify_confidence import verify_confidence

__all__ = [
    "assemble",
    "detect_language",
    "guardrail_in",
    "guardrail_out",
    "placeholder",
    "route_intent",
    "support_rag",
    "verify_confidence",
    "LangSignal",
    "IntentSignal",
    "GroundedAnswer",
]
