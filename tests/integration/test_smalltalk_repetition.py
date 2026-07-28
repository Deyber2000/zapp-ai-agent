"""Social/meta turns are acknowledged, not refused (#2); verbatim replies are guarded (#4).

Courtesy ("thanks", greetings, language requests) used to fall into out_of_scope and be hard-refused
at high confidence; they now route to a `smalltalk` node. Separately, supplying an already-captured
detail to a completed onboarding re-emitted the confirm verbatim — the repetition guard breaks that.
"""

from __future__ import annotations

from tests.support.mock_llm import MockCall, MockLLMClient, agent_step
from zapp_assist.agent import Agent
from zapp_assist.config import load_config
from zapp_assist.graph.nodes._util import REPETITION_TEMPLATES, SMALLTALK_TEMPLATES


def _agent(responder) -> Agent:  # type: ignore[no-untyped-def]
    return Agent.create(config=load_config(), llm=MockLLMClient(responder=responder))


def test_smalltalk_is_acknowledged_not_refused() -> None:
    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang="en", confidence=0.97)
        if name == "AgentStep":
            return agent_step(call.schema, call, intent="smalltalk")
        return None

    result = _agent(responder).run_turn("st", "thanks a lot for your help!")
    assert result.reply == SMALLTALK_TEMPLATES["en"]  # a warm acknowledgement...
    assert result.needs_review is False
    assert not result.guardrails.input  # ...NOT a refusal recorded as out_of_scope


def test_repetition_guard_breaks_a_verbatim_repeat() -> None:
    # Onboarding completes on turn 1 (confirm). Turn 2 adds an email (not a slot) → the node would
    # re-emit the identical confirm, so the guard substitutes a nudge instead.
    def responder(call: MockCall):  # type: ignore[no-untyped-def]
        if call.schema is None:
            return None
        name = call.schema.__name__
        if name == "LangSignal":
            return call.schema(lang="en", confidence=0.97)
        if name == "AgentStep":
            return agent_step(call.schema, call, intent="onboarding")
        if name == "OnboardingExtraction":
            return call.schema(
                full_name="Ana Ruiz",
                phone_raw="+52 55 1234 5678",
                region_hint="MX",
                phone_normalized="+525512345678",
            )
        return None

    agent = _agent(responder)
    r1 = agent.run_turn("rep", "I'm Ana Ruiz, my phone is +52 55 1234 5678")
    r2 = agent.run_turn("rep", "and my email is ana@example.com")

    assert r1.reply != r2.reply  # not a verbatim repeat
    assert r2.reply == REPETITION_TEMPLATES["en"]  # the nudge replaced the repeated confirm
