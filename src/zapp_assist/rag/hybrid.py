"""Hybrid retrieval: fuse sparse (BM25) + dense (embeddings) via Reciprocal Rank Fusion (RRF).

RRF combines ranked lists without score normalization: each doc scores ``Σ 1/(k + rank)`` across
retrievers, so a doc ranked highly by *either* retriever surfaces. If the dense side is unavailable
(no key / offline), the hybrid retriever degrades to the sparse results — preserving the
"decline rather than hallucinate" gate and the offline/deterministic path.

The returned per-doc score feeds `support_rag`'s grounding confidence: a lexical hit keeps its BM25
score; a dense-only hit uses its (scaled) cosine similarity — so ranking is by RRF while confidence
stays on a BM25-comparable scale (no change needed in the answer node).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .dense import DenseRetriever
from .store import BM25Store, KnowledgeDocument

_CANDIDATES = 10  # per-retriever depth to fuse over (wider than top_k so RRF has signal)
_DENSE_SCORE_SCALE = 10.0  # map dense-only cosine (0-1) onto the BM25-ish scale for confidence


def reciprocal_rank_fusion(ranked_ids: Iterable[list[str]], k: int = 60) -> dict[str, float]:
    """RRF score per id across ranked lists: higher = better; rank is 0-based within each list."""

    scores: dict[str, float] = {}
    for ids in ranked_ids:
        for rank, doc_id in enumerate(ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


class HybridRetriever:
    """Fuses a BM25 store and a dense retriever with RRF; degrades to BM25 when dense is off."""

    def __init__(
        self,
        sparse: BM25Store,
        dense: DenseRetriever,
        rrf_k: int = 60,
        top_k: int = 3,
    ) -> None:
        self._sparse = sparse
        self._dense = dense
        self._k = rrf_k
        self._top_k = top_k

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        on_llm: Callable[..., None] | None = None,  # seam-only; hybrid makes no LLM calls
    ) -> list[tuple[KnowledgeDocument, float]]:
        limit = top_k or self._top_k
        sparse_hits = self._sparse.search(query, top_k=_CANDIDATES)
        dense_hits = self._dense.search(query, top_k=_CANDIDATES)
        if not dense_hits:
            return sparse_hits[:limit]  # degrade to lexical (offline / no dense signal)

        # A doc's confidence score: its BM25 score if it was a lexical hit, else its scaled cosine.
        by_id: dict[str, tuple[KnowledgeDocument, float]] = {}
        for doc, score in sparse_hits:
            by_id[doc.id] = (doc, score)
        for doc, sim in dense_hits:
            by_id.setdefault(doc.id, (doc, sim * _DENSE_SCORE_SCALE))

        rrf = reciprocal_rank_fusion(
            [[d.id for d, _ in sparse_hits], [d.id for d, _ in dense_hits]], self._k
        )
        ranked_ids = sorted(by_id, key=lambda i: rrf.get(i, 0.0), reverse=True)[:limit]
        return [by_id[i] for i in ranked_ids]
