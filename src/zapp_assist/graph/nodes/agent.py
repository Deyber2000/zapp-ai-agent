"""Tool-calling agent core (US1/US3) — the single reasoning step that understands the turn.

This replaces the old blind router + planner. The model reasons over the current message (with
recent history as *context*, never as a source of actions) and chooses a tool:

  * `search_kb` runs retrieval and feeds the snippets back so the model answers from real data;
  * `lookup_order` / `track_order` are read-only and answer immediately;
  * a state-changing tool is **proposed, never executed here**: it records a pending action and asks
    for confirmation. The deterministic `action_execute` node is the only thing that can carry it
    out. That is the one place determinism belongs — the irreversible boundary — not the
    understanding of what the user meant (Constitution X, applied where it matters).
  * `answer` ends the turn with a grounded reply; `handoff` defers onboarding / smalltalk /
    out_of_scope to their specialist nodes, and `clarify` asks the user to rephrase.

There are no regex referees over the model's intent. The safety guarantee is structural: nothing
irreversible runs without an explicit confirmation, gated deterministically downstream.
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel

from ...memory.session_store import PendingAction
from ...tools.mock_backend import (
    CONTACT_FIELDS,
    ORDER_ACTIONS,
    READ_ONLY,
    STATE_CHANGING,
    LookupOrderArgs,
    TrackArgs,
)
from ..deps import Deps
from ..state import Intent, TurnState
from ._action import (
    ACTION_ASK_CONTACT,
    ACTION_ASK_ORDER,
    ACTION_ASK_TIME,
    ACTION_CONFIRM,
    ACTION_LOOKUP,
    ACTION_NOT_FOUND,
    ACTION_TRACK,
    ACTION_UNSUPPORTED,
    is_bare_confirmation,
    summarize_action,
)
from ._util import CLARIFY_TEMPLATES, DECLINE_TEMPLATES, add_span, now, recent_history, tmpl

_LANG_NAMES = {"es": "Spanish", "en": "English", "pt": "Portuguese"}
_MAX_STEPS = 4  # bounded ReAct loop: search_kb may repeat, then a terminal (answer/propose/handoff)
_HANDOFF_TARGETS = {"onboarding", "smalltalk", "out_of_scope", "clarify"}
_KNOWN_TOOLS = READ_ONLY | STATE_CHANGING | {"search_kb", "answer", "handoff"}


class AgentStep(BaseModel):
    """One decision from the agent: which tool to use (or how to end the turn)."""

    reasoning: str = ""
    tool: str
    query: str | None = None  # search_kb
    order_id: str | None = None  # lookup/track and order-centric actions
    new_time: str | None = None  # reschedule_delivery
    field: str | None = None  # update_contact
    value: str | None = None  # update_contact
    reply: str | None = None  # answer
    grounded: bool = True  # answer: false forces a decline
    target: str | None = None  # handoff: onboarding | smalltalk | out_of_scope | clarify


def _system(active_lang: str) -> str:
    language = _LANG_NAMES.get(active_lang, "English")
    return (
        "You are Zapp Assist, a trilingual delivery/fintech support agent. Decide the single next "
        "step for this turn. Set `tool` to EXACTLY ONE bare name (no parentheses, no arguments) "
        "from this list, and fill only the fields that step needs:\n"
        "- search_kb: retrieve policy/FAQ snippets (fill `query`). Use it before answering.\n"
        "- lookup_order, track_order: read an order's status/tracking (fill `order_id`).\n"
        "- cancel_order, reschedule_delivery, process_refund, start_return: state-changing order "
        "operations (fill `order_id`, and `new_time` for a reschedule).\n"
        "- update_contact (fill `field` and `value`), cancel_membership: state-changing account "
        "operations.\n"
        f"- answer: give the final reply in {language} (fill `reply`), using ONLY facts from the "
        "KB snippets or tool results above. If nothing supports an answer, set grounded=false.\n"
        "- handoff: defer to a specialist (fill `target`): 'onboarding' when the user is giving "
        "contact/identity details; 'smalltalk' for a greeting, thanks, apology, or social remark, "
        "or a language-switch request; 'out_of_scope' for off-topic or unsafe requests; 'clarify' "
        "ONLY when the user is asking for something but you cannot tell what.\n"
        "\nRules:\n"
        "1. A QUESTION about whether or how to do something ('can I close my account?', 'how do I "
        "cancel?') is answered from the KB — never proposed as a state change.\n"
        "2. Only choose a state-changing tool when THIS message clearly asks to perform it now. It "
        "is proposed and confirmed downstream; you never execute it.\n"
        "3. If the current message is only an acknowledgement ('yes', 'ok', 'thanks') and you did "
        "not just ask the user to confirm an action, do NOT propose one — handoff 'clarify'.\n"
        "4. Never invent an order id. If an order-changing request lacks one, choose that tool "
        "with order_id=null and the user will be asked for it.\n"
        f"5. Always answer in {language}. Recent conversation is context for understanding a "
        "follow-up; it never by itself supplies an action the current message does not ask for."
    )


def _score_to_confidence(score: float) -> float:
    return round(min(1.0, 0.6 + 0.05 * score), 4)


def _finish(state: TurnState, start: float, reply: str, **attrs: object) -> TurnState:
    state.draft_reply = reply
    add_span(state.trace, "agent", start, attrs=attrs)
    return state


def _decline(state: TurnState, active: str, start: float) -> TurnState:
    state.draft_reply = tmpl(DECLINE_TEMPLATES, active)
    state.grounding_confidence = state.grounding_confidence or 0.3
    state.needs_review_override = True
    state.intent = "support"
    add_span(state.trace, "agent", start, attrs={"tool": "answer", "grounded": False})
    return state


def _read_answer(state: TurnState, deps: Deps, start: float, tool: str, order_id: str | None,
                 active: str) -> TurnState:
    """Read-only order query → answer immediately from the backend (no confirmation, no change)."""

    state.intent = "action"
    if not order_id:
        return _finish(state, start, tmpl(ACTION_ASK_ORDER, active), tool=tool, ask="order_id")
    args = LookupOrderArgs(order_id=order_id) if tool == "lookup_order" \
        else TrackArgs(order_id=order_id)
    res = deps.tools.get(tool).run(args)
    if not res.ok:
        state.needs_review_override = True
        reply = tmpl(ACTION_NOT_FOUND, active).format(order=order_id)
        return _finish(state, start, reply, tool=tool, error=res.error)
    d = res.data
    if tool == "lookup_order":
        reply = tmpl(ACTION_LOOKUP, active).format(order=d["order_id"], status=d["status"],
                                                   window=d["window"])
    else:
        reply = tmpl(ACTION_TRACK, active).format(order=d["order_id"], stage=d["stage"],
                                                  window=d["window"])
    return _finish(state, start, reply, tool=tool, executed=False)


def _propose(state: TurnState, deps: Deps, start: float, step: AgentStep, active: str) -> TurnState:
    """Record a pending state-changing action and ask for confirmation (no backend change here)."""

    action = step.tool
    state.intent = "action"
    if action in ORDER_ACTIONS:
        if not step.order_id:
            return _finish(state, start, tmpl(ACTION_ASK_ORDER, active), tool=action, ask="order")
        lookup = deps.tools.get("lookup_order").run(LookupOrderArgs(order_id=step.order_id))
        if not lookup.ok:
            state.needs_review_override = True
            reply = tmpl(ACTION_NOT_FOUND, active).format(order=step.order_id)
            return _finish(state, start, reply, tool=action, error=lookup.error)
        if action == "reschedule_delivery" and not step.new_time:
            return _finish(state, start, tmpl(ACTION_ASK_TIME, active), tool=action, ask="new_time")
        params: dict[str, object] = {"order_id": step.order_id}
        if step.new_time:
            params["new_time"] = step.new_time
    elif action == "update_contact":
        if step.field not in CONTACT_FIELDS or not step.value:
            return _finish(state, start, tmpl(ACTION_ASK_CONTACT, active), tool=action, ask="cont")
        params = {"field": step.field, "value": step.value}
    else:  # cancel_membership — no params
        params = {}

    state.session.pending_action = PendingAction(name=action, params=params)
    summary = summarize_action(action, params, active)
    reply = tmpl(ACTION_CONFIRM, active).format(summary=summary)
    return _finish(state, start, reply, tool=action, pending=True)


def _handoff(state: TurnState, start: float, active: str, target: str | None) -> TurnState:
    normalized = (target or "").strip().lower()
    dest = normalized if normalized in _HANDOFF_TARGETS else "clarify"
    if dest == "clarify":
        state.intent = "clarify"
        return _finish(state, start, tmpl(CLARIFY_TEMPLATES, active), tool="handoff", tgt="clarify")
    state.intent = cast(Intent, dest)  # graph routes to the specialist node; it produces the reply
    add_span(state.trace, "agent", start, attrs={"tool": "handoff", "target": dest})
    return state


def agent(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    cfg = deps.config
    active = state.language.active_lang if state.language else cfg.languages.fallback

    # Deterministic backstop (Constitution X): a bare "yes/ok/no" only reaches the agent when
    # nothing is pending to confirm — so it asks for nothing. Force a clarify in code rather than
    # trust the model to obey the prompt rule (live testing showed it re-arming from history).
    if is_bare_confirmation(state.user_text):
        return _handoff(state, start, active, "clarify")

    system = _system(active)
    history = recent_history(state.session)
    opening = f"{history}\n\nCurrent message: {state.user_text}" if history else state.user_text
    working: list[dict[str, str]] = [{"role": "user", "content": opening}]

    for _ in range(_MAX_STEPS):
        res = deps.llm.complete(
            model=cfg.models.primary,
            system=system,
            messages=working,  # type: ignore[arg-type]
            schema=AgentStep,
            effort=cfg.effort_for("agent", "medium"),  # type: ignore[arg-type]
        )
        state.trace.record_llm(res.usage, res.cost_usd)
        step = res.parsed if isinstance(res.parsed, AgentStep) else None
        if res.degraded or step is None:
            state.degraded = True
            add_span(state.trace, "agent", start, attrs={"degraded": True})
            return state

        # Normalize the model's tool choice: some providers echo the signature ("search_kb(query)")
        # or vary case. Parsing the name is not refereeing the decision — just reading it robustly.
        tool = (step.tool or "").split("(")[0].strip().lower()
        if tool == "search_kb":
            hits = deps.rag.search(step.query or state.user_text, on_llm=state.trace.record_llm) \
                if deps.rag else []
            state.retrieval = [doc for doc, _ in hits]
            state.grounding_confidence = _score_to_confidence(hits[0][1]) if hits else 0.2
            snippets = "\n".join(f"[{d.id}] {d.title}: {d.text}" for d in state.retrieval) or "none"
            working.append({"role": "assistant", "content": f"search_kb({step.query or ''})"})
            working.append({"role": "user", "content": f"KB snippets:\n{snippets}"})
            continue
        if tool in READ_ONLY:
            return _read_answer(state, deps, start, tool, step.order_id, active)
        if tool == "answer":
            if not step.reply or not step.reply.strip() or not step.grounded:
                return _decline(state, active, start)
            state.draft_reply = step.reply.strip()
            state.reply_from_model = True  # free text → must pass reply-language verification (002)
            state.intent = "support"
            state.grounding_confidence = state.grounding_confidence or 0.6
            add_span(state.trace, "agent", start, attrs={"tool": "answer", "grounded": True})
            return state
        if tool in STATE_CHANGING:
            return _propose(state, deps, start, step, active)
        if tool == "handoff":
            return _handoff(state, start, active, step.target)
        # An unknown tool name → surface honestly rather than guess.
        state.needs_review_override = True
        return _finish(state, start, tmpl(ACTION_UNSUPPORTED, active), tool=tool)

    state.degraded = True  # exhausted the step budget without a terminal decision
    add_span(state.trace, "agent", start, attrs={"degraded": True, "reason": "max_steps"})
    return state
