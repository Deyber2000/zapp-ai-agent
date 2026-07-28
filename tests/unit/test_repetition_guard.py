"""Repetition guard (assemble node): don't re-emit a reply we just sent (001; defect #4).

The first version compared only against the immediately previous reply, by exact match — so a
completed onboarding that re-emitted its confirm would ping-pong confirm/nudge/confirm (the nudge
became the previous reply, letting the next confirm through), and a one-character casing variant
slipped past untouched. The guard now compares against the last few replies, normalized for
case/whitespace, and stands down while an action legitimately awaits a repeated confirmation.
"""

from __future__ import annotations

from zapp_assist.config import load_config
from zapp_assist.graph.deps import Deps
from zapp_assist.graph.nodes._util import REPETITION_TEMPLATES
from zapp_assist.graph.nodes.assemble import assemble
from zapp_assist.graph.state import TurnState
from zapp_assist.guardrails.baseline import default_registry
from zapp_assist.lang.detector import LanguageResult, LinguaDetector
from zapp_assist.memory.session_store import PendingAction, Session, TurnRef
from zapp_assist.obs.trace import Trace
from zapp_assist.tools.registry import ToolRegistry

CONFIRM = "All set, Carlos Mendoza! I saved your number as +573001234567. Is that correct?"


def _deps() -> Deps:
    cfg = load_config()
    return Deps(
        config=cfg,
        llm=None,  # type: ignore[arg-type]  # assemble does not call the LLM
        detector=LinguaDetector(cfg.languages.supported, cfg.languages.fallback),
        guardrails=default_registry(),
        tools=ToolRegistry(),
    )


def _state(
    draft: str, history: list[TurnRef], *, pending: bool = False, intent: str = "onboarding"
) -> TurnState:
    session = Session(session_id="s", history=list(history))
    if pending:
        session.pending_action = PendingAction(name="cancel_order", params={"order_id": "A1001"})
    state = TurnState(turn_id="t", session=session, user_text="x", trace=Trace(turn_id="t",
                                                                               session_id="s"))
    state.language = LanguageResult(detected_lang="en", active_lang="en", lang_confidence=0.9)
    state.intent = intent  # type: ignore[assignment]  # the guard is scoped to onboarding replies
    state.draft_reply = draft
    return state


def _reply(
    draft: str, history: list[TurnRef], *, pending: bool = False, intent: str = "onboarding"
) -> str:
    out = assemble(_state(draft, history, pending=pending, intent=intent), _deps())
    assert out.result is not None
    return out.result.reply


def test_repeat_two_turns_back_is_caught_not_just_the_previous_reply() -> None:
    # confirm, then nudge, then confirm again: comparing against a WINDOW (not only history[-1])
    # catches the second confirm even though the nudge sits between them (closes the ping-pong).
    history = [
        TurnRef(user_text="a", reply=CONFIRM, intent="onboarding"),
        TurnRef(user_text="b", reply=REPETITION_TEMPLATES["en"], intent="onboarding"),
    ]
    assert _reply(CONFIRM, history) == REPETITION_TEMPLATES["en"]


def test_near_duplicate_casing_variant_is_caught() -> None:
    # A one-character casing difference ("carlos mendoza") is the same reply for the user.
    near_dup = CONFIRM.replace("Carlos Mendoza", "carlos mendoza")
    history = [TurnRef(user_text="a", reply=CONFIRM, intent="onboarding")]
    assert _reply(near_dup, history) == REPETITION_TEMPLATES["en"]


def test_guard_stands_down_while_an_action_awaits_confirmation() -> None:
    # Re-asking the SAME confirmation question is intentional when an action is pending — the guard
    # must not replace it with "already shared that" (which would falsely imply closure).
    reask = "Just to confirm: do you want me to cancel order A1001? Please reply yes or no."
    history = [TurnRef(user_text="a", reply=reask, intent="action")]
    assert _reply(reask, history, pending=True) == reask


def test_a_fresh_distinct_reply_is_not_touched() -> None:
    history = [TurnRef(user_text="a", reply=CONFIRM, intent="onboarding")]
    fresh = "Order A1001 is “out for delivery” with delivery today 5–7pm."
    assert _reply(fresh, history) == fresh
