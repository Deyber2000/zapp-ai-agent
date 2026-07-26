"""US3 (003) — configurable guardrail policy + action precedence.

Rules can be disabled or have their severity/action overridden from config with no code change; the
semantic layer is skipped when its classifier is disabled; "most severe action governs".
"""

from __future__ import annotations

from zapp_assist.config import AppConfig, RulePolicy, load_config
from zapp_assist.contracts import GuardrailDecision
from zapp_assist.guardrails.baseline import default_registry
from zapp_assist.guardrails.registry import GuardrailContext, governing_action

_OFFTOPIC = "Write me a poem about the sea."  # triggers the off_topic rule by default


def _cfg(policy: dict[str, RulePolicy]) -> AppConfig:
    base = load_config()
    guardrails = base.guardrails.model_copy(update={"policy": policy})
    return base.model_copy(update={"guardrails": guardrails})


def _input(text: str) -> GuardrailContext:
    return GuardrailContext(stage="input", user_text=text)


def test_rule_fires_by_default() -> None:
    reg = default_registry(load_config())
    assert any(d.rule == "off_topic" for d in reg.run("input", _input(_OFFTOPIC)))


def test_disabled_rule_does_not_fire() -> None:
    reg = default_registry(_cfg({"off_topic": RulePolicy(enabled=False)}))
    assert not any(d.rule == "off_topic" for d in reg.run("input", _input(_OFFTOPIC)))


def test_action_and_severity_override_is_applied() -> None:
    reg = default_registry(_cfg({"off_topic": RulePolicy(action="escalate", severity="high")}))
    decision = next(d for d in reg.run("input", _input(_OFFTOPIC)) if d.rule == "off_topic")
    assert decision.action == "escalate"
    assert decision.severity == "high"


def test_governing_action_precedence() -> None:
    def d(action: str) -> GuardrailDecision:
        return GuardrailDecision(rule="x", action=action, severity="low", category="c")  # type: ignore[arg-type]

    assert governing_action([d("allow"), d("redact"), d("refuse"), d("escalate")]) == "refuse"
    assert governing_action([d("redact"), d("escalate")]) == "escalate"
    assert governing_action([d("redact")]) == "redact"
    assert governing_action([]) == "allow"


def test_disabled_semantic_layer_is_not_run() -> None:
    class _Disabled:
        enabled = False
        degraded = False

        def classify(self, stage: str, ctx: GuardrailContext) -> list[GuardrailDecision]:
            raise AssertionError("disabled semantic layer must not be called")

    reg = default_registry(load_config(), _Disabled())
    assert reg.run("input", _input("hello there")) == []  # benign; semantic skipped
    assert reg.semantic_degraded is False
