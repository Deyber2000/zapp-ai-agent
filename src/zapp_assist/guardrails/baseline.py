"""Baseline (deterministic) guardrail layer + registry wiring (Constitution VIII).

The regex rules below are the DETERMINISTIC layer (fast, offline, authoritative for known patterns).
Each rule is tagged with a taxonomy `category` and carries a default severity/action that the config
`guardrails.policy` can override per rule (or disable). `003` adds the semantic layer, wired in here
via `default_registry(..., semantic=...)`; with the default config (semantic off, no overrides)
behavior is byte-for-byte the `001` baseline.

Input:  prompt-injection, PII, abuse/toxicity, off-topic.
Output: PII-leak, ungrounded-claim, policy/disclosure.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..contracts import GuardrailAction, GuardrailDecision, Severity
from .registry import GuardrailContext, GuardrailRegistry

if TYPE_CHECKING:
    from ..config import AppConfig

_INJECTION = re.compile(
    r"(ignore\s+(all\s+|your\s+|the\s+|previous\s+|above\s+|prior\s+)*(instructions|rules|prompt)"
    r"|disregard\s+(the\s+|all\s+|your\s+)*(previous|above|prior|instructions|rules)"
    r"|forget\s+(all\s+|your\s+|the\s+|everything|previous)"
    r"|override\s+(your\s+|the\s+)?(instructions|rules|prompt|settings)"
    r"|(reveal|print|show|repeat|leak|expose|tell\s+me)\s+(me\s+)?(your\s+|the\s+)?"
    r"(system\s+|initial\s+|original\s+)?(prompt|instructions|rules|guidelines)"
    r"|your\s+(system\s+)?(prompt|instructions)"
    r"|(what\s+(is|are)|repeat)\s+your\s+(system\s+)?(prompt|instructions|rules)"
    r"|pretend\s+(to\s+be|you|that)|act\s+as\s+(a|an|if)|role[\s-]?play"
    r"|you\s+are\s+now\b|new\s+instructions|bypass|jailbreak|developer\s+mode|dan\s+mode)",
    re.IGNORECASE,
)
_ABUSE = re.compile(
    r"\b(fuck\w*|shit|asshole|bitch|idiot|moron|bastard|jackass|screw\s+you|shut\s+up|piss\s+off)\b",
    re.IGNORECASE,
)
_OFFTOPIC = re.compile(
    r"\b(poem|haiku|sonnet|joke|riddle|recipe|weather|horoscope|stock\s+price|lyrics|"
    r"write\s+(me\s+)?(a|an|some)|tell\s+me\s+a\s+(story|joke)|translate\s+this|"
    r"capital\s+of|who\s+(is|was)\s+the\s+president|math\s+(homework|problem)|sing\s+(me\s+)?a)\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.\-]+@[\w\-]+\.\w+")
_LONG_DIGITS = re.compile(r"\b\d[\d \-]{11,}\d\b")  # 13+ digit runs → card/account-like
_LEAK = re.compile(
    r"(system\s+prompt|my\s+instructions\s+are|i\s+was\s+instructed\s+to)", re.IGNORECASE
)

# Decline replies that legitimately contain no grounding — the ungrounded guard must not flag these.
_DECLINE_MARKERS = (
    "can't confirm",
    "cannot confirm",
    "no puedo confirmar",
    "não posso confirmar",
    "nao posso confirmar",
    "flagged it",
    "marcado",
    "sinalizei",
)


@dataclass
class _Rule:
    """A deterministic rule: a predicate + its category and (policy-overridable) severity/action."""

    id: str
    stage: str
    category: str
    severity: Severity
    action: GuardrailAction
    detail: str
    match: Callable[[GuardrailContext], bool]

    def check(self, ctx: GuardrailContext) -> GuardrailDecision | None:
        if self.match(ctx):
            return GuardrailDecision(
                rule=self.id,
                action=self.action,
                severity=self.severity,
                detail=self.detail,
                category=self.category,
                layer="deterministic",
            )
        return None


# -- matchers (predicates over the guardrail context) ----------------------------------------


def _m_injection(ctx: GuardrailContext) -> bool:
    return bool(_INJECTION.search(ctx.user_text))


def _m_pii_input(ctx: GuardrailContext) -> bool:
    return bool(_EMAIL.search(ctx.user_text) or _LONG_DIGITS.search(ctx.user_text))


def _m_abuse(ctx: GuardrailContext) -> bool:
    return bool(_ABUSE.search(ctx.user_text))


def _m_off_topic(ctx: GuardrailContext) -> bool:
    return bool(_OFFTOPIC.search(ctx.user_text))


def _m_pii_leak(ctx: GuardrailContext) -> bool:
    reply = ctx.draft_reply or ""
    return bool(_EMAIL.search(reply) or _LONG_DIGITS.search(reply))


def _m_ungrounded(ctx: GuardrailContext) -> bool:
    # Backstop: retrieval was attempted (list present) but empty, and the reply is NOT a decline —
    # i.e. it asserts something without grounding.
    reply = (ctx.draft_reply or "").strip()
    if isinstance(ctx.retrieval, list) and len(ctx.retrieval) == 0 and reply:
        low = reply.lower()
        return not any(marker in low for marker in _DECLINE_MARKERS)
    return False


def _m_policy(ctx: GuardrailContext) -> bool:
    return bool(_LEAK.search(ctx.draft_reply or ""))


def _base_rules() -> list[_Rule]:
    """Fresh rule instances so policy overrides never mutate shared state; defaults = 001."""

    return [
        _Rule("prompt_injection", "input", "prompt_injection", "high", "refuse",
              "instruction-override attempt", _m_injection),
        _Rule("pii", "input", "pii", "medium", "redact",
              "personal data detected in input", _m_pii_input),
        _Rule("abuse", "input", "toxicity", "medium", "refuse", "abusive language", _m_abuse),
        _Rule("off_topic", "input", "off_topic", "low", "refuse",
              "request outside the Zapp support domain", _m_off_topic),
        _Rule("pii_leak", "output", "pii_leak", "medium", "redact",
              "personal data in reply", _m_pii_leak),
        _Rule("ungrounded", "output", "ungrounded", "medium", "escalate",
              "answer not grounded in the knowledge source", _m_ungrounded),
        _Rule("policy", "output", "disclosure", "high", "refuse",
              "reply would disclose internal instructions", _m_policy),
    ]


def default_registry(config: AppConfig | None = None, semantic: Any = None) -> GuardrailRegistry:
    """The baseline (deterministic) rules, with config policy applied + an optional semantic layer.

    Policy (`config.guardrails.policy`, keyed by rule id) can disable a rule or override its
    severity/action without code changes; absent → the rule's defaults (= `001`).
    """

    policy = config.guardrails.policy if config is not None else {}
    registry = GuardrailRegistry(semantic=semantic)
    for rule in _base_rules():
        override = policy.get(rule.id)
        if override is not None:
            if not override.enabled:
                continue
            if override.severity is not None:
                rule.severity = override.severity
            if override.action is not None:
                rule.action = override.action
        registry.register(rule)
    return registry


def mask_pii(text: str) -> str:
    """Redact PII spans in an outbound reply."""

    text = _EMAIL.sub("[redacted-email]", text)
    text = _LONG_DIGITS.sub("[redacted-number]", text)
    return text
