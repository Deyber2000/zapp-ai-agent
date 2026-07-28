"""Explicit language-switch request detection (002): `detect_switch_request`, in isolation.

A direct request to change the reply language ("reply in English", "cambia a inglés", "fala em
português") returns the target ISO in any supported tongue; a passing mention of a language
("a Spanish order", "do you speak English?") does not. Deterministic and offline.
"""

from __future__ import annotations

import pytest

from zapp_assist.lang.detector import detect_switch_request

_SUP = ["es", "en", "pt"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("reply in English please", "en"),
        ("Actually I would prefer to continue in English now", "en"),
        ("can you switch to English?", "en"),
        ("háblame en inglés", "en"),
        ("puedes cambiar a inglés", "en"),
        ("cambia al inglés por favor", "en"),
        ("in English, how do I reschedule?", "en"),
        ("responde en español", "es"),
        ("switch to Spanish", "es"),
        ("prefiero español", "es"),
        ("fala em português", "pt"),
        ("muda para português", "pt"),
        ("continue in Portuguese", "pt"),
    ],
)
def test_explicit_requests_return_the_target_language(text: str, expected: str) -> None:
    assert detect_switch_request(text, _SUP) == expected


@pytest.mark.parametrize(
    "text",
    [
        "I have a Spanish invoice for my order",  # passing mention, not a directive
        "do you speak English?",  # capability question, no preposition/switch verb
        "my order shipped in a weird box",
        "cancel my order A1001",
        "gracias por tu ayuda",
        "where is my delivery?",
        "",
    ],
)
def test_non_requests_return_none(text: str) -> None:
    assert detect_switch_request(text, _SUP) is None


def test_unsupported_target_is_ignored() -> None:
    # A request to a language the deployment does not support is not a switch (stays on policy).
    assert detect_switch_request("please reply in English", ["es", "pt"]) is None
