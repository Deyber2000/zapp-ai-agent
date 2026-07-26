"""Placeholder node for not-yet-implemented intents (onboarding / action / out_of_scope).

Spec `001` implements US1 (support). Those other intents route here for a polite "not available
yet" reply with `needs_review=true` and a valid contract. US2/US3/US4 replace this with the real
`onboarding`, `action_plan`/`action_execute`, and `out_of_scope` nodes; the routing seam in
`build.py` is already in place.
"""

from __future__ import annotations

from ..deps import Deps
from ..state import TurnState
from ._util import PLACEHOLDER_TEMPLATES, add_span, now, tmpl


def placeholder(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    active = state.language.active_lang if state.language else deps.config.languages.fallback
    state.draft_reply = tmpl(PLACEHOLDER_TEMPLATES, active)
    state.needs_review_override = True
    add_span(state.trace, "placeholder", start, attrs={"intent": state.intent})
    return state
