"""Deterministic routing guardrail (Constitution X).

The router's verdict now gets the same deterministic cross-check every other correctness-critical
signal has. The guard only ever pulls an `action` classification back toward something safe — a bare
confirmation with nothing pending, or an interrogative with no order id and no action verb, must
never arm a state change from conversation history.
"""

from __future__ import annotations

from zapp_assist.graph.nodes._routing import (
    guard_intent,
    has_action_verb,
    has_order_id,
    is_bare_confirmation,
    is_interrogative,
    order_ids_in,
)
from zapp_assist.memory.session_store import PendingAction, Session


def _session(*, pending: bool = False) -> Session:
    s = Session(session_id="t")
    if pending:
        s.pending_action = PendingAction(name="cancel_order", params={"order_id": "A1001"})
    return s


# --- pure signals ------------------------------------------------------------------------------


def test_order_id_detection() -> None:
    assert has_order_id("cancel order A1001")
    assert order_ids_in("A1001 and a1002") == {"A1001", "A1002"}
    assert not has_order_id("close my account permanently")
    assert order_ids_in("no order here") == set()


def test_interrogative_forms_across_languages() -> None:
    assert is_interrogative("can I also close my account permanently?")
    assert is_interrogative("¿puedo cerrar mi cuenta?")
    assert is_interrogative("como faço para cancelar?")
    assert is_interrogative("what is the status of my order")  # opener, no '?'
    assert not is_interrogative("cancel order A1001")


def test_action_verb_detection() -> None:
    assert has_action_verb("please cancel it")
    assert has_action_verb("quiero cancelar el pedido")
    assert has_action_verb("reagendar a entrega")
    assert not has_action_verb("close my account")


def test_bare_confirmation() -> None:
    assert is_bare_confirmation("yes go ahead")
    assert is_bare_confirmation("sí, adelante")
    assert is_bare_confirmation("sim, pode")
    assert not is_bare_confirmation("cancel order A1001")  # a real request
    assert not is_bare_confirmation("ok, how do I track my order?")  # a leading 'ok' on a question
    assert not is_bare_confirmation("maybe")  # ambiguous, not a clear yes/no
    assert not is_bare_confirmation("yes, cancel A1001")  # names an order + verb


# --- guard_intent: only ever pulls `action` toward safety --------------------------------------


def test_bare_affirmation_with_nothing_pending_becomes_clarify() -> None:
    intent, reason = guard_intent("action", "yes go ahead", _session(pending=False))
    assert intent == "clarify" and reason == "bare_confirmation_no_pending"


def test_interrogative_question_becomes_support_not_action() -> None:
    intent, reason = guard_intent(
        "action", "can I also close my account permanently?", _session(pending=False)
    )
    assert intent == "support" and reason == "interrogative_no_action_content"


def test_genuine_action_with_order_id_is_untouched() -> None:
    intent, reason = guard_intent("action", "please cancel order A1001", _session())
    assert intent == "action" and reason is None


def test_explicit_membership_cancel_is_untouched() -> None:
    # An interrogative that DOES state an action verb is a real request, not a question.
    intent, reason = guard_intent("action", "can you cancel my membership?", _session())
    assert intent == "action" and reason is None


def test_confirmation_turn_with_pending_is_untouched() -> None:
    # A real "yes" answering a pending confirmation must reach execution, not be re-routed.
    intent, reason = guard_intent("action", "yes go ahead", _session(pending=True))
    assert intent == "action" and reason is None


def test_guard_never_manufactures_or_touches_non_action_intents() -> None:
    for intent in ("support", "smalltalk", "onboarding", "out_of_scope", "clarify"):
        assert guard_intent(intent, "yes go ahead", _session()) == (intent, None)
