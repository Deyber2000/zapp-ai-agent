"""US4 (002) — language-fidelity signals for the 004 evaluation suite.

Both language spans carry the fidelity attributes, and `language_fidelity` computes the share of
verified turns whose reply matched the active language — with no reply-text inspection.
"""

from __future__ import annotations

from tests.support.mock_llm import scripted_llm
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.graph.build import build_graph
from zapp_assist.graph.state import TurnState
from zapp_assist.memory.session_store import Session
from zapp_assist.obs.trace import Span, Trace, language_fidelity


def test_spans_carry_language_fidelity_attributes() -> None:
    reply = "You can reschedule your delivery up to two hours before the estimated window."
    llm = scripted_llm(
        lang="en", intent="support", reply=reply, citations=["delivery_reschedule_en"]
    )
    graph = build_graph(Agent.create(config=load_config(), llm=llm).deps)

    trace = Trace(turn_id="t", session_id="s")
    state = TurnState(
        turn_id="t",
        session=Session(session_id="s"),
        user_text="How late can I reschedule a delivery?",
        trace=trace,
    )
    result_trace = graph.invoke({"ts": state})["ts"].trace

    detect = next(s for s in result_trace.spans if s.node == "detect_language")
    assert {"detected", "active", "confidence"} <= set(detect.attrs)

    verify = next(s for s in result_trace.spans if s.node == "verify_reply_language")
    assert "reply_match" in verify.attrs
    assert verify.attrs["reply_match"] is True  # the English reply matched active_lang=en


def _verified_trace(match: bool) -> Trace:
    trace = Trace(turn_id="x", session_id="s")
    trace.add_span(Span(node="verify_reply_language", attrs={"reply_match": match}))
    return trace


def _short_trace() -> Trace:
    trace = Trace(turn_id="x", session_id="s")
    trace.add_span(Span(node="verify_reply_language", attrs={"skipped_short": True}))
    return trace


def test_language_fidelity_rate_over_traces() -> None:
    fid = language_fidelity([_verified_trace(True), _verified_trace(True), _verified_trace(False)])
    assert fid.turns == 3
    assert fid.verified == 3
    assert fid.matched == 2
    assert fid.rate == round(2 / 3, 4)


def test_short_replies_are_excluded_from_the_rate() -> None:
    # A skipped-short turn is not "verified", so it neither helps nor hurts the fidelity rate.
    fid = language_fidelity([_verified_trace(True), _short_trace()])
    assert fid.turns == 2
    assert fid.verified == 1
    assert fid.matched == 1
    assert fid.rate == 1.0
