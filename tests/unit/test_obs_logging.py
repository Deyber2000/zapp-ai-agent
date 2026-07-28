"""Observability (Constitution XI): run_turn emits exactly one structured line per turn.

structlog was declared but never called — the Trace was captured and dropped. This locks in that a
turn now emits a single `turn_complete` event carrying the fields needed to debug and cost-account
the turn from logs alone.
"""

from __future__ import annotations

from structlog.testing import capture_logs

from tests.support.mock_llm import scripted_llm
from zapp_assist.agent import Agent
from zapp_assist.config import load_config


def test_run_turn_emits_one_structured_turn_log() -> None:
    agent = Agent.create(config=load_config(), llm=scripted_llm(lang="en", intent="support"))
    with capture_logs() as logs:
        agent.run_turn("obs", "how late can I reschedule my delivery?")

    turns = [e for e in logs if e.get("event") == "turn_complete"]
    assert len(turns) == 1  # exactly one line per turn
    event = turns[0]
    assert event["session_id"] == "obs"
    assert event["active_lang"] == "en"
    assert event["intent"] == "support"
    # the accounting fields an operator needs are all present
    for field in ("latency_ms", "cost_usd", "input_tokens", "output_tokens", "spans"):
        assert field in event
    assert isinstance(event["guardrails_in"], list)
