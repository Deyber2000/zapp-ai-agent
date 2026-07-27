"""Stateless graph nodes. Each is `node(state, deps) -> state` and appends exactly one Span."""

from __future__ import annotations

from .action_execute import action_execute
from .action_plan import ActionRequest, action_plan
from .assemble import assemble
from .detect_language import LangSignal, detect_language
from .guardrail_in import guardrail_in
from .guardrail_out import guardrail_out
from .onboarding import OnboardingExtraction, onboarding
from .out_of_scope import out_of_scope
from .route_intent import IntentSignal, route_intent
from .smalltalk import smalltalk
from .support_rag import GroundedAnswer, support_rag
from .verify_confidence import verify_confidence
from .verify_reply_language import RewrittenReply, verify_reply_language

__all__ = [
    "action_execute",
    "action_plan",
    "assemble",
    "detect_language",
    "guardrail_in",
    "guardrail_out",
    "onboarding",
    "out_of_scope",
    "route_intent",
    "smalltalk",
    "support_rag",
    "verify_confidence",
    "verify_reply_language",
    "LangSignal",
    "IntentSignal",
    "GroundedAnswer",
    "OnboardingExtraction",
    "ActionRequest",
    "RewrittenReply",
]
