"""Hybrid retrieval — RRF fusion, dense (stub embedder), and degrade-to-BM25. All offline.

Uses a deterministic keyword stub embedder and stub searchers so the fusion/degrade logic is tested
without any network or key.
"""

from __future__ import annotations

from zapp_assist.rag.dense import DenseRetriever
from zapp_assist.rag.hybrid import HybridRetriever, reciprocal_rank_fusion
from zapp_assist.rag.store import KnowledgeDocument

_AXES = ["reschedule", "track", "password", "cancel"]


class _StubEmbedder:
    """Deterministic keyword embedder: one axis per topic → controllable cosine similarity."""

    available = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            low = text.lower()
            vec = [1.0 if axis in low else 0.0 for axis in _AXES]
            out.append(vec if any(vec) else [0.25, 0.25, 0.25, 0.25])
        return out


class _Unavailable:
    available = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        return []


class _StubSearcher:
    def __init__(self, results: list[tuple[KnowledgeDocument, float]]) -> None:
        self._results = results

    def search(self, query: str, top_k: int = 3) -> list[tuple[KnowledgeDocument, float]]:
        return self._results[:top_k]


def _doc(doc_id: str, text: str) -> KnowledgeDocument:
    return KnowledgeDocument(id=doc_id, title=doc_id, text=text, lang="en")


def test_rrf_ranks_docs_high_in_both_lists_first() -> None:
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["a", "c", "d"]])
    assert scores["a"] > scores["c"] > scores["b"]  # a is top in both; c beats b (rank0 in list2)


def test_dense_retriever_ranks_by_similarity() -> None:
    docs = [_doc("resched", "reschedule your delivery"), _doc("pwd", "reset your password")]
    dense = DenseRetriever(docs, _StubEmbedder(), min_similarity=0.5)
    hits = dense.search("how do I reschedule my order")
    assert hits and hits[0][0].id == "resched"
    assert all(doc.id != "pwd" for doc, _ in hits)  # below the similarity floor


def test_dense_retriever_disabled_without_embedder() -> None:
    dense = DenseRetriever([_doc("x", "anything")], _Unavailable())
    assert dense.enabled is False
    assert dense.search("anything") == []


def test_hybrid_fuses_sparse_and_dense() -> None:
    a, b = _doc("A", "alpha"), _doc("B", "beta")
    hybrid = HybridRetriever(_StubSearcher([(a, 5.0)]), _StubSearcher([(b, 0.8)]))  # type: ignore[arg-type]
    ids = {doc.id for doc, _ in hybrid.search("q")}
    assert ids == {"A", "B"}  # a doc found by EITHER retriever surfaces


def test_hybrid_degrades_to_sparse_when_dense_is_empty() -> None:
    a = _doc("A", "alpha")
    hybrid = HybridRetriever(_StubSearcher([(a, 5.0)]), _StubSearcher([]))  # type: ignore[arg-type]
    assert hybrid.search("q") == [(a, 5.0)]  # dense off → pure BM25 (offline path)
