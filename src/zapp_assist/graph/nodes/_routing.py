"""Deterministic routing guardrail (Constitution X).

Every other correctness-critical signal in the system already gets a deterministic cross-check —
phone via `phonenumbers`, language via `lingua`, action confirmation via a regex lexicon. Routing
was the exception: the LLM classifier's verdict selected the entire downstream path with nothing
checking it, and history-aware routing let prior turns *supply* an action (a question inheriting
`action`, a bare "yes" re-arming a cancel with an id recovered from history).

These pure checks are that missing cross-check. They only ever pull an `action` classification
*back* toward something safer — they never turn a benign message into a state change. History may
disambiguate a follow-up; it must never be what supplies the action.
"""

from __future__ import annotations

import re

from ...memory.session_store import Session
from ..state import Intent
from ._action import classify_confirmation

# An order identifier as used across the mock backend / KB (e.g. A1001): a letter + 3+ digits.
_ORDER_ID_RE = re.compile(r"\b[A-Za-z]\d{3,}\b")

# Interrogative / informational openers across ES/EN/PT — "am I able to…", "how do I…", "is it
# possible…". A question about whether or how something works is support, not a command to do it.
_INTERROGATIVE = re.compile(
    r"^\s*(?:can|could|may|do|does|is|are|how|what|where|when|why|should|would)\b"
    r"|^\s*¿?\s*(?:puedo|puede|podr[ií]a|c[oó]mo|se\s+puede|qu[eé]|es\s+posible|d[oó]nde)\b"
    r"|^\s*(?:posso|pode|poderia|como|é\s+possível|o\s+que|onde|quando)\b",
    re.IGNORECASE,
)

# Action verbs actually stated in THIS message. Distinguishes "cancel order A1001" (a real request)
# from "can I close my account?" (a question) — "close" is deliberately excluded because the KB
# documents account closure as a self-service flow, not an agent action.
_ACTION_VERB = re.compile(
    r"\b(?:cancel|resched\w*|refund|return|updat\w*|chang\w*"
    r"|cancela\w*|reprogram\w*|reembols\w*|devol\w*|actualiz\w*|cambi\w*"
    r"|cancele\w*|reagend\w*|atualiz\w*|mud[ae]\w*)\b",
    re.IGNORECASE,
)


def order_ids_in(text: str) -> set[str]:
    """The set of order ids named in `text` (upper-cased), e.g. {'A1001'}."""

    return {m.group(0).upper() for m in _ORDER_ID_RE.finditer(text or "")}


def has_order_id(text: str) -> bool:
    return bool(_ORDER_ID_RE.search(text or ""))


def is_interrogative(text: str) -> bool:
    body = (text or "").strip()
    return bool(_INTERROGATIVE.search(body)) or body.endswith("?")


def has_action_verb(text: str) -> bool:
    return bool(_ACTION_VERB.search(text or ""))


def is_bare_confirmation(text: str) -> bool:
    """A yes/no that carries no request of its own — e.g. 'yes go ahead', 'sí, adelante'.

    A leading affirmation on a real question ('ok, how do I track my order?') is not bare: it has an
    order/action reference, a question mark, or simply too many words.
    """

    body = (text or "").strip()
    if classify_confirmation(body) == "ambiguous":  # not a clear yes/no at all
        return False
    if has_order_id(body) or has_action_verb(body) or "?" in body:
        return False
    return len(body.split()) <= 4


def guard_intent(intent: Intent, text: str, session: Session) -> tuple[Intent, str | None]:
    """Cross-check the router's verdict. Returns (intent, reason); reason is set only on override.

    Safe-direction only, and only ever on `action`:
      * a genuine confirmation turn (something already pending) is left alone — it is routed to
        execution upstream;
      * a bare confirmation with nothing pending carries no request → `clarify`;
      * an interrogative with no order id and no stated action verb is a question → `support`.
    """

    if intent != "action":
        return intent, None  # the guard never manufactures an action, only defuses one
    if session.pending_action is not None:
        return "action", None  # answering a pending confirmation — hands off to action_execute
    if is_bare_confirmation(text):
        return "clarify", "bare_confirmation_no_pending"
    if is_interrogative(text) and not has_order_id(text) and not has_action_verb(text):
        return "support", "interrogative_no_action_content"
    return "action", None
