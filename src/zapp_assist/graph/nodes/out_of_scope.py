"""Out-of-scope handling node (US4, FR-003).

Reached when the router classifies a turn as out-of-scope but no keyword input guardrail fired (a
semantic off-topic/unsafe request the deterministic rules missed). It declines safely in the active
language and records the decision in `guardrails.input` so the refusal is auditable in the contract.

Keyword-matched injection/abuse/off-topic is handled earlier by `guardrail_in` (the blocked path);
this node is the model-classified backstop, keeping the safety envelope closed on both routes.
"""

from __future__ import annotations

from ...contracts import GuardrailDecision
from ..deps import Deps
from ..state import TurnState
from ._util import GUARDRAIL_DECLINE_TEMPLATES, add_span, now, tmpl


def out_of_scope(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    active = state.language.active_lang if state.language else deps.config.languages.fallback

    # Record the refusal as an input guardrail decision (auditable in the contract).
    state.guardrails_in.append(
        GuardrailDecision(
            rule="out_of_scope",
            action="refuse",
            severity="low",
            layer="semantic",  # model-classified backstop (see docstring), not deterministic
            detail="request outside the Zapp support domain",
        )
    )
    # Safe decline that redirects to what the agent can help with, in the user's language.
    state.draft_reply = tmpl(GUARDRAIL_DECLINE_TEMPLATES, active)

    add_span(state.trace, "out_of_scope", start, attrs={"intent": "out_of_scope"})
    return state
