"""US3 (004) — the rule-based LLM-as-judge is deterministic and on-rubric."""

from __future__ import annotations

from evals.judge import RuleBasedJudge
from evals.models import EvalCase, Expected, MockScript, RunRecord

from zapp_assist.contracts import Guardrails, TurnResult


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
