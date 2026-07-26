"""Baseline input/output guardrails (Constitution VIII; full taxonomy in spec `003`).

Input:  prompt-injection, PII, abuse, off-topic.
Output: PII-leak, ungrounded-claim, policy.

Each guardrail is deterministic and returns a `GuardrailDecision` or `None` (pass). They are
intentionally conservative to minimise false positives on genuine support questions; spec `003`
replaces these heuristics with the full rule set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..contracts import GuardrailDecision
from .registry import GuardrailContext, GuardrailRegistry

_INJECTION = re.compile(
    r"(ignore\s+(all\s+|your\s+|the\s+|previous\s+|above\s+)*instructions"
    r"|disregard\s+(the\s+|all\s+)*(previous|above|prior)"
    r"|(reveal|print|show|repeat|leak)\s+(me\s+)?(your\s+|the\s+)?(system\s+)?prompt"
    r"|your\s+(system\s+)?instructions"
    r"|you\s+are\s+now\b|jailbreak|developer\s+mode|dan\s+mode)",
    re.IGNORECASE,
)
_ABUSE = re.compile(r"\b(fuck|shit|asshole|bitch|idiot|moron)\b", re.IGNORECASE)
_OFFTOPIC = re.compile(
    r"\b(poem|haiku|joke|riddle|recipe|weather|horoscope|stock\s+price|"
    r"write\s+me\s+a|tell\s+me\s+a\s+story)\b",
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
    id: str
    stage: str
    _check: object  # callable(ctx) -> GuardrailDecision | None

    def check(self, ctx: GuardrailContext) -> GuardrailDecision | None:
        return self._check(ctx)  # type: ignore[operator]


# -- input guardrails ------------------------------------------------------------------------


def _prompt_injection(ctx: GuardrailContext) -> GuardrailDecision | None:
    if _INJECTION.search(ctx.user_text):
        return GuardrailDecision(
            rule="prompt_injection",
            action="refuse",
            severity="high",
            detail="instruction-override attempt",
        )
    return None


def _pii_input(ctx: GuardrailContext) -> GuardrailDecision | None:
    if _EMAIL.search(ctx.user_text) or _LONG_DIGITS.search(ctx.user_text):
        return GuardrailDecision(
            rule="pii",
            action="redact",
            severity="medium",
            detail="personal data detected in input",
        )
    return None


def _abuse(ctx: GuardrailContext) -> GuardrailDecision | None:
    if _ABUSE.search(ctx.user_text):
        return GuardrailDecision(
            rule="abuse",
            action="refuse",
            severity="medium",
            detail="abusive language",
        )
    return None


def _off_topic(ctx: GuardrailContext) -> GuardrailDecision | None:
    if _OFFTOPIC.search(ctx.user_text):
        return GuardrailDecision(
            rule="off_topic",
            action="refuse",
            severity="low",
            detail="request outside the Zapp support domain",
        )
    return None


# -- output guardrails -----------------------------------------------------------------------


def _pii_leak(ctx: GuardrailContext) -> GuardrailDecision | None:
    reply = ctx.draft_reply or ""
    if _EMAIL.search(reply) or _LONG_DIGITS.search(reply):
        return GuardrailDecision(
            rule="pii_leak",
            action="redact",
            severity="medium",
            detail="personal data in reply",
        )
    return None


def _ungrounded(ctx: GuardrailContext) -> GuardrailDecision | None:
    reply = (ctx.draft_reply or "").strip()
    # Only a backstop: retrieval was attempted (list present) but empty, and the reply is NOT a
    # decline — i.e. it asserts something without grounding.
    if isinstance(ctx.retrieval, list) and len(ctx.retrieval) == 0 and reply:
        low = reply.lower()
        if not any(marker in low for marker in _DECLINE_MARKERS):
            return GuardrailDecision(
                rule="ungrounded",
                action="escalate",
                severity="medium",
                detail="answer not grounded in the knowledge source",
            )
    return None


def _policy(ctx: GuardrailContext) -> GuardrailDecision | None:
    if _LEAK.search(ctx.draft_reply or ""):
        return GuardrailDecision(
            rule="policy",
            action="refuse",
            severity="high",
            detail="reply would disclose internal instructions",
        )
    return None


def default_registry() -> GuardrailRegistry:
    """The baseline guardrail set, wired for `001`."""

    registry = GuardrailRegistry()
    registry.register(_Rule("prompt_injection", "input", _prompt_injection))
    registry.register(_Rule("pii", "input", _pii_input))
    registry.register(_Rule("abuse", "input", _abuse))
    registry.register(_Rule("off_topic", "input", _off_topic))
    registry.register(_Rule("pii_leak", "output", _pii_leak))
    registry.register(_Rule("ungrounded", "output", _ungrounded))
    registry.register(_Rule("policy", "output", _policy))
    return registry


def mask_pii(text: str) -> str:
    """Redact PII spans in an outbound reply."""

    text = _EMAIL.sub("[redacted-email]", text)
    text = _LONG_DIGITS.sub("[redacted-number]", text)
    return text
