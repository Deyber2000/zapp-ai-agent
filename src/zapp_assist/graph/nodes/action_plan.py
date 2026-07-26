"""Action planning node (US3, FR-012). Plan — never execute a state change here.

The LLM extracts the requested action + parameters (never fabricating an order id). A read-only
lookup is answered immediately. A state-changing action is only *proposed*: we verify the order
exists, record a `PendingAction(status=awaiting_confirmation)`, and restate the action asking for
confirmation. No backend mutation happens on this turn (FR-012). Unknown actions/orders and missing
parameters are surfaced honestly rather than faked (edge cases).
"""

from __future__ import annotations

from pydantic import BaseModel

from ...memory.session_store import PendingAction
from ...tools.mock_backend import STATE_CHANGING, LookupOrderArgs
from ..deps import Deps
from ..state import TurnState
from ._action import (
    ACTION_ASK_ORDER,
    ACTION_ASK_TIME,
    ACTION_CONFIRM,
    ACTION_LOOKUP,
    ACTION_NOT_FOUND,
    ACTION_UNSUPPORTED,
    summarize_action,
)
from ._util import add_span, now, tmpl

_SUPPORTED = {"lookup_order", "reschedule_delivery", "cancel_order"}

_ACTION_SYSTEM = (
    "You interpret a Zapp Assist user's action request. Identify the operation and parameters:\n"
    "- action: one of lookup_order, reschedule_delivery, cancel_order, or 'unknown' if it is none "
    "of these.\n"
    "- order_id: the order identifier if the user gave one, else null. Never invent an order id.\n"
    "- new_time: the requested new delivery time for a reschedule, else null.\n"
    "Return only what the user actually stated."
)


class ActionRequest(BaseModel):
    """The LLM's reading of the requested action."""

    action: str
    order_id: str | None = None
    new_time: str | None = None


def _finish(state: TurnState, start: float, reply: str, **attrs: object) -> TurnState:
    state.draft_reply = reply
    add_span(state.trace, "action_plan", start, attrs=attrs)
    return state


def action_plan(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    cfg = deps.config
    active = state.language.active_lang if state.language else cfg.languages.fallback

    res = deps.llm.complete(
        model=cfg.models.primary,
        system=_ACTION_SYSTEM,
        messages=[{"role": "user", "content": state.user_text}],
        schema=ActionRequest,
        effort=cfg.effort_for("action_plan", "low"),  # type: ignore[arg-type]
    )
    state.trace.record_llm(res.usage, res.cost_usd)

    plan = res.parsed if isinstance(res.parsed, ActionRequest) else None
    if res.degraded or plan is None:
        state.degraded = True
        add_span(state.trace, "action_plan", start, attrs={"degraded": True})
        return state

    action = plan.action
    if action not in _SUPPORTED:
        state.needs_review_override = True
        return _finish(state, start, tmpl(ACTION_UNSUPPORTED, active), action=action)

    if not plan.order_id:
        reply = tmpl(ACTION_ASK_ORDER, active)
        return _finish(state, start, reply, action=action, asked="order_id")

    # Verify the order exists before doing (or proposing) anything — never fake an unknown order.
    lookup = deps.tools.get("lookup_order").run(LookupOrderArgs(order_id=plan.order_id))
    if not lookup.ok:
        state.needs_review_override = True
        reply = tmpl(ACTION_NOT_FOUND, active).format(order=plan.order_id)
        return _finish(state, start, reply, action=action, error=lookup.error)

    if action == "lookup_order":  # read-only → answer immediately, no confirmation needed
        data = lookup.data
        reply = tmpl(ACTION_LOOKUP, active).format(
            order=data["order_id"], status=data["status"], window=data["window"]
        )
        return _finish(state, start, reply, action=action, executed=False)

    if action == "reschedule_delivery" and not plan.new_time:
        return _finish(state, start, tmpl(ACTION_ASK_TIME, active), action=action, asked="new_time")

    # State-changing action with valid params → PROPOSE (pending) + ask confirmation. No change.
    assert action in STATE_CHANGING
    params: dict[str, object] = {"order_id": plan.order_id}
    if plan.new_time:
        params["new_time"] = plan.new_time
    state.session.pending_action = PendingAction(name=action, params=params)

    summary = summarize_action(action, params, active)
    reply = tmpl(ACTION_CONFIRM, active).format(summary=summary)
    return _finish(state, start, reply, action=action, pending=True)
