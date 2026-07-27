"""Zapp Assist evaluation suite (spec 004).

A pure OBSERVER of the agent: it imports `zapp_assist`, runs it over a labeled dataset, and scores
the emitted signals (the `TurnResult` contract + per-turn `Trace`). Nothing here is imported by
the agent. Deterministic by default (per-case scripted model + rule-based judge) so the committed
report is reproducible with no key or network.
"""
