"""US2 (002) — the pure language switch policy (`apply_switch_policy`).

Covers the transition table: first-lock, keep-on-match/weak/short, accumulate on a new confident
supported language, and switch only after `switch_turns` consecutive turns (never on a one-off).
"""

from __future__ import annotations

from zapp_assist.lang.detector import apply_switch_policy

_SUP = ["es", "en", "pt"]


def _call(
    active: str | None,
    detected: str,
    *,
    conf: float = 0.9,
    substantial: bool = True,
    pend: str | None = None,
    count: int = 0,
    turns: int = 2,
) -> tuple[str | None, str | None, int, bool]:
    return apply_switch_policy(
        active_lang=active,
        detected=detected,
        confidence=conf,
        substantial=substantial,
        pending_lang=pend,
        pending_count=count,
        supported=_SUP,
        lock_threshold=0.75,
        switch_min_confidence=0.75,
        switch_turns=turns,
    )


def test_first_lock_on_confident_supported() -> None:
    assert _call(None, "es", conf=0.80) == ("es", None, 0, False)


def test_no_lock_when_unconfident() -> None:
    assert _call(None, "es", conf=0.50) == (None, None, 0, False)


def test_matching_turn_keeps_lock_and_resets_pending() -> None:
    assert _call("es", "es", pend="en", count=1) == ("es", None, 0, False)


def test_weak_confidence_keeps_lock() -> None:
    assert _call("es", "en", conf=0.50, pend="en", count=1) == ("es", None, 0, False)


def test_short_turn_cannot_switch() -> None:
    result = _call("es", "en", conf=0.99, substantial=False, pend="en", count=1)
    assert result == ("es", None, 0, False)


def test_new_candidate_starts_accumulator() -> None:
    assert _call("es", "en") == ("es", "en", 1, False)


def test_one_off_phrase_does_not_switch() -> None:
    locked, pend, count, switched = _call("es", "en")
    assert locked == "es" and switched is False and pend == "en" and count == 1


def test_sustained_switch_after_threshold() -> None:
    assert _call("es", "en", pend="en", count=1) == ("en", None, 0, True)


def test_a_different_new_candidate_restarts_the_count() -> None:
    assert _call("es", "pt", pend="en", count=1) == ("es", "pt", 1, False)


def test_switch_turns_is_configurable() -> None:
    assert _call("es", "en", pend="en", count=1, turns=3) == ("es", "en", 2, False)
    assert _call("es", "en", pend="en", count=2, turns=3) == ("en", None, 0, True)
