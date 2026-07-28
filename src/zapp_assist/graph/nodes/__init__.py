"""Stateless graph nodes. Each is `node(state, deps) -> state` and appends exactly one Span."""

from __future__ import annotations

from .action_execute import action_execute
from .agent import AgentStep, agent
from .assemble import assemble
from .detect_language import LangSignal, detect_language
from .guardrail_in import guardrail_in
from .guardrail_out import guardrail_out
from .onboarding import OnboardingExtraction, onboarding
from .out_of_scope import out_of_scope
from .smalltalk import smalltalk
from .verify_confidence import verify_confidence
from .verify_reply_language import RewrittenReply, verify_reply_language

__all__ = [
    "action_execute",
    "agent",
    "assemble",
    "detect_language",
    "guardrail_in",
    "guardrail_out",
    "onboarding",
    "out_of_scope",
    "smalltalk",
    "verify_confidence",
    "verify_reply_language",
    "AgentStep",
    "LangSignal",
    "OnboardingExtraction",
    "RewrittenReply",
]
