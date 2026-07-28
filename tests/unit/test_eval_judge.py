"""US3 (004) — the LLM-as-judge: deterministic rule-based scoring, an anchored rubric, and a live
judge that runs at temperature 0 (spec 004 requires deterministic judge settings)."""

from __future__ import annotations

from typing import Any

from evals.judge import RUBRIC, LLMJudge, RuleBasedJudge
from evals.models import EvalCase, Expected, MockScript, RunRecord

from zapp_assist.config import load_config
from zapp_assist.contracts import Guardrails, TurnResult
from zapp_assist.llm.client import LLMResult, Msg, Usage


def _case(lang: str = "en") -> EvalCase:
    return EvalCase(
        id="c", capability="support", turns=["t"], script=MockScript(), expected=Expected(lang=lang)
    )


def _result(active_lang: str = "en", needs_review: bool = False) -> TurnResult:
    return TurnResult(
        reply="A clear, helpful, grounded answer.",
        detected_lang=active_lang,
        active_lang=active_lang,
        lang_confidence=0.9,
        final_normalized_text="x",
        confidence_score=0.9,
        needs_review=needs_review,
        guardrails=Guardrails(),
    )


def test_judge_scores_are_in_range_and_deterministic() -> None:
    judge = RuleBasedJudge()
    record = RunRecord(case_id="c", result=_result())
    v1 = judge.score(_case(), record)
    v2 = judge.score(_case(), record)
    assert v1.model_dump() == v2.model_dump()  # deterministic
    for dim in (v1.helpfulness, v1.groundedness, v1.safety, v1.language):
        assert 1 <= dim <= 5


def test_confident_answer_scores_higher_than_a_hedged_one() -> None:
    judge = RuleBasedJudge()
    confident = judge.score(_case(), RunRecord(case_id="c", result=_result(needs_review=False)))
    hedged = judge.score(_case(), RunRecord(case_id="c", result=_result(needs_review=True)))
    assert confident.helpfulness > hedged.helpfulness


def test_wrong_language_lowers_the_language_score() -> None:
    judge = RuleBasedJudge()
    # case expects Spanish, but the reply is in English.
    record = RunRecord(case_id="c", result=_result(active_lang="en"))
    verdict = judge.score(_case(lang="es"), record)
    assert verdict.language == 2


def test_errored_case_scores_low() -> None:
    verdict = RuleBasedJudge().score(_case(), RunRecord(case_id="c", error="boom"))
    assert verdict.helpfulness == 1


class _TempSpyLLM:
    """Records the temperature the judge asks for; returns a fixed rubric verdict."""

    def __init__(self) -> None:
        self.temperature: Any = "unset"

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Msg],
        schema: Any = None,
        tools: Any = None,
        effort: str = "medium",
        temperature: float | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult:
        self.temperature = temperature
        parsed = schema(helpfulness=5, groundedness=5, safety=4, language=5) if schema else None
        return LLMResult(parsed=parsed, usage=Usage(input_tokens=1, output_tokens=1), cost_usd=0.0)


def test_llm_judge_scores_at_temperature_zero() -> None:
    # spec 004 names deterministic judge settings; the live judge runs on gpt-4o-mini, which IS
    # temperature-capable — the one place the "frontier models reject temperature" argument fails.
    spy = _TempSpyLLM()
    LLMJudge(spy, load_config()).score(_case(), RunRecord(case_id="c", result=_result()))  # type: ignore[arg-type]
    assert spy.temperature == 0.0


def test_rubric_has_level_anchors_for_every_dimension() -> None:
    # A rubric with only named dimensions isn't reproducible; each needs 1/3/5 level anchors.
    assert set(RUBRIC) == {"helpfulness", "groundedness", "safety", "language"}
    for anchor in RUBRIC.values():
        assert "1 =" in anchor and "3 =" in anchor and "5 =" in anchor
