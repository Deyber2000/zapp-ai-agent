"""Action planning node (US3, FR-012). Plan — never execute a state change here.

The LLM extracts the action + parameters (never fabricating an order id). Read-only actions
(`lookup_order`, `track_order`) answer immediately. Order-centric state changes verify the order
exists, then only *propose* — record a `PendingAction(awaiting_confirmation)`, restate, and ask.
Account/membership actions (`update_contact`, `cancel_membership`) skip the order check, propose
the same way. No mutation happens here (FR-012); unknown actions/orders and missing params are
surfaced honestly, not faked.
"""

from __future__ import annotations

from pydantic import BaseModel

from ...memory.session_store import PendingAction
from ...tools.mock_backend import (
    ACCOUNT_ACTIONS,
    CONTACT_FIELDS,
    ORDER_ACTIONS,
    READ_ONLY,
    STATE_CHANGING,
    LookupOrderArgs,
    TrackArgs,
)
from ..deps import Deps
from ..state import TurnState
from ._action import (
    ACTION_ASK_CONTACT,
    ACTION_ASK_ORDER,
    ACTION_ASK_TIME,
    ACTION_CONFIRM,
    ACTION_LOOKUP,
    ACTION_NOT_FOUND,
    ACTION_TRACK,
    ACTION_UNSUPPORTED,
    summarize_action,
)
from ._util import add_span, now, tmpl

_SUPPORTED = READ_ONLY | ORDER_ACTIONS | ACCOUNT_ACTIONS

_ACTION_SYSTEM = (
    "You interpret a Zapp Assist user's action request. Identify the operation and parameters:\n"
    "- action: one of lookup_order, track_order, reschedule_delivery, cancel_order, "
    "process_refund, start_return, update_contact, cancel_membership, or 'unknown'.\n"
    "- order_id: the order identifier if the user gave one, else null. Never invent an order id.\n"
    "- new_time: the requested new delivery time for a reschedule, else null.\n"
    "- field: for update_contact, 'email' or 'phone'; else null.\n"
    "- value: for update_contact, the new email/phone value; else null.\n"
    "Return only what the user actually stated."
)


class ActionRequest(BaseModel):
    """The LLM's reading of the requested action."""

    action: str
    order_id: str | None = None
    new_time: str | None = None
    field: str | None = None
    value: str | None = None


def _finish(state: TurnState, start: float, reply: str, **attrs: object) -> TurnState:
    state.draft_reply = reply
    add_span(state.trace, "action_plan", start, attrs=attrs)
    return state


def _propose(
    state: TurnState, start: float, action: str, params: dict[str, object], active: str
) -> TurnState:
    """Record a pending state-changing action and ask for confirmation (no backend change)."""

    state.session.pending_action = PendingAction(name=action, params=params)
    summary = summarize_action(action, params, active)
    reply = tmpl(ACTION_CONFIRM, active).format(summary=summary)
    return _finish(state, start, reply, action=action, pending=True)


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

    if action in ACCOUNT_ACTIONS:
        return _plan_account(state, start, plan, active)

    # Order-centric (read-only or order state-changing): require + verify an order id first.
    if not plan.order_id:
        reply = tmpl(ACTION_ASK_ORDER, active)
        return _finish(state, start, reply, action=action, asked="order_id")

    lookup = deps.tools.get("lookup_order").run(LookupOrderArgs(order_id=plan.order_id))
    if not lookup.ok:
        state.needs_review_override = True
        reply = tmpl(ACTION_NOT_FOUND, active).format(order=plan.order_id)
        return _finish(state, start, reply, action=action, error=lookup.error)

    if action == "lookup_order":  # read-only → answer immediately, no confirmation needed
        d = lookup.data
        reply = tmpl(ACTION_LOOKUP, active).format(
            order=d["order_id"], status=d["status"], window=d["window"]
        )
        return _finish(state, start, reply, action=action, executed=False)

    if action == "track_order":  # read-only → answer immediately
        d = deps.tools.get("track_order").run(TrackArgs(order_id=plan.order_id)).data
        reply = tmpl(ACTION_TRACK, active).format(
            order=d["order_id"], stage=d["stage"], window=d["window"]
        )
        return _finish(state, start, reply, action=action, executed=False)

    if action == "reschedule_delivery" and not plan.new_time:
        return _finish(state, start, tmpl(ACTION_ASK_TIME, active), action=action, asked="new_time")

    assert action in ORDER_ACTIONS
    params: dict[str, object] = {"order_id": plan.order_id}
    if plan.new_time:
        params["new_time"] = plan.new_time
    return _propose(state, start, action, params, active)


def _plan_account(state: TurnState, start: float, plan: ActionRequest, active: str) -> TurnState:
    """Plan an account/membership action (no order to verify); propose + confirm."""

    action = plan.action
    assert action in STATE_CHANGING
    if action == "update_contact":
        if plan.field not in CONTACT_FIELDS or not plan.value:
            reply = tmpl(ACTION_ASK_CONTACT, active)
            return _finish(state, start, reply, action=action, asked="contact")
        return _propose(state, start, action, {"field": plan.field, "value": plan.value}, active)
    return _propose(state, start, action, {}, active)  # cancel_membership — no params
