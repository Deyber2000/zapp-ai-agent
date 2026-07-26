"""Unit tests for BM25 retrieval + tokenization (Constitution X; grounding backstop).

In-domain queries retrieve grounding above the score threshold; out-of-domain queries return nothing
(so the agent declines rather than inventing); tokenization folds accents and drops ES/EN/PT
stopwords; an empty KB is handled without error.
"""

from __future__ import annotations

from zapp_assist.rag.store import KB_DIR, BM25Store, tokenize


def test_in_domain_query_retrieves_grounding_above_threshold() -> None:
    store = BM25Store.from_kb_dir(KB_DIR, threshold=1.0)
    hits = store.search("How late can I reschedule a delivery?")
    assert hits
    doc, score = hits[0]
    assert score >= 1.0
    assert "reschedule" in doc.id


def test_out_of_domain_query_returns_nothing() -> None:
    store = BM25Store.from_kb_dir(KB_DIR, threshold=1.0)
    assert store.search("Can I pay with cryptocurrency?") == []


def test_tokenize_folds_accents_and_drops_stopwords() -> None:
    tokens = tokenize("¿Cómo cambio mi contraseña?")
    assert "contrasena" in tokens  # ñ folded to n
    assert "mi" not in tokens  # stopword removed
    assert "como" not in tokens  # stopword removed


def test_empty_kb_search_is_safe() -> None:
    assert BM25Store([], threshold=1.0).search("anything at all") == []
