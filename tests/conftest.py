"""Test-wide fixtures.

Keep the whole suite offline and deterministic: with no LLM/embedding key present, the default
`hybrid` retriever degrades to BM25 and no test can make a live call — even if a real `.env` exists
on the machine. Tests inject a mock `LLMClient`, so the LLM never goes live either; this only guards
the retriever's embedding path.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from zapp_assist.config import get_settings


@pytest.fixture(autouse=True)
def _offline_no_keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
