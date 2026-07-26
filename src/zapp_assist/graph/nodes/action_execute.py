"""Action execution node (US3, FR-013). Reached only when a pending action awaits confirmation.

Deterministically reads the user's confirmation reply:
  * confirm   → execute the pending action EXACTLY ONCE, then clear it (so it can never re-execute);
  * decline   → abandon it, no backend change;
  * ambiguous → keep it pending and re-ask (never execute on an unclear answer).

The confirmation decision is deterministic (see `_action.classify_confirmation`) — an irreversible
action must not hinge on a model guess.
"""

from __future__ import annotations

from ...memory.session_store import PendingAction
from ...tools.mock_backend import CancelArgs, RescheduleArgs
from ...tools.registry import ToolResult
from ..deps import Deps
from ..state import TurnState
from ._action import (
    ACTION_ABANDONED,
    ACTION_DONE,
    ACTION_FAILED,
    ACTION_REASK,
    classify_confirmation,
    summarize_action,
)
from ._util import add_span, now, tmpl


def _execute(pending: PendingAction, deps: Deps) -> ToolResult:
    tool = deps.tools.get(pending.name)
    if pending.name == "reschedule_delivery":
        return tool.run(
            RescheduleArgs(order_id=pending.params["order_id"], new_time=pending.params["new_time"])
        )
    return tool.run(CancelArgs(order_id=pending.params["order_id"]))


def action_execute(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    active = state.language.active_lang if state.language else deps.config.languages.fallback
    pending = state.session.pending_action

    if pending is None or pending.status != "awaiting_confirmation":
        # Defensive: routing only sends confirmation turns here. Nothing to do → assemble decides.
        add_span(state.trace, "action_execute", start, attrs={"pending": False})
        return state

    summary = summarize_action(pending.name, pending.params, active)
    decision = classify_confirmation(state.user_text)

    if decision == "confirm":
        result = _execute(pending, deps)
        state.session.pending_action = None  # cleared → executes at most once (FR-013)
        if result.ok:
            reply = tmpl(ACTION_DONE, active).format(summary=summary)
        else:
            reply, state.needs_review_override = (
                tmpl(ACTION_FAILED, active).format(summary=summary),
                True,
            )
        return _span(state, start, reply, decision="confirm", ok=result.ok)

    if decision == "decline":
        state.session.pending_action = None  # abandoned → no backend change
        return _span(state, start, tmpl(ACTION_ABANDONED, active), decision="decline")

    # Ambiguous → keep pending, re-ask. Never executes on an unclear answer.
    reply = tmpl(ACTION_REASK, active).format(summary=summary)
    return _span(state, start, reply, decision="ambiguous")


def _span(state: TurnState, start: float, reply: str, **attrs: object) -> TurnState:
    state.draft_reply = reply
    add_span(state.trace, "action_execute", start, attrs=attrs)
    return state
