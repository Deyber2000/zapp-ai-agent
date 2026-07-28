"""Smalltalk / social node (US4 extension): acknowledge courtesy & meta turns, never refuse.

Greetings, thanks, and meta remarks have no data to ground and no action to run — the router sends
them here for a brief, friendly, in-language acknowledgement that redirects to what Zapp Assist can
help with. This is deliberately NOT `out_of_scope`: refusing a "thank you" is a UX failure, not a
safety one, and hard-refusing at high confidence also hid these from the eval signal.
"""

from __future__ import annotations

from ..deps import Deps
from ..state import TurnState
from ._util import LANGUAGE_SWITCH_TEMPLATES, SMALLTALK_TEMPLATES, add_span, now, tmpl


def smalltalk(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    active = state.language.active_lang if state.language else deps.config.languages.fallback
    # An explicit language-switch request (active_lang already flipped by detect_language) gets a
    # confirmation in the new language; any other courtesy/meta turn gets the warm redirect.
    templates = LANGUAGE_SWITCH_TEMPLATES if state.lang_switch_to else SMALLTALK_TEMPLATES
    state.draft_reply = tmpl(templates, active)
    add_span(
        state.trace, "smalltalk", start,
        attrs={"intent": "smalltalk", "lang_switch": state.lang_switch_to},
    )
    return state
