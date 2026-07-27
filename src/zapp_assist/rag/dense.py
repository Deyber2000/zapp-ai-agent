"""Dense (semantic) retriever: cosine similarity over embedded KB docs (hybrid RAG upgrade).

Embeds every KB document once at construction (via the `Embedder` seam). With HyPE enabled it
also embeds each doc's *hypothetical questions* as extra representations pointing back to the same
doc, so a user's question can match a stored *question* (symmetric) rather than only the answer
prose — a doc scores by its best-matching representation. It is `enabled` only if the embedder
produced vectors; otherwise it returns nothing, so the hybrid retriever degrades to lexical (BM25).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .embedder import Embedder
from .store import KnowledgeDocument


class DenseRetriever:
    """Semantic retriever over the KB; disabled (returns []) when embeddings are unavailable."""

    def __init__(
        self,
        docs: list[KnowledgeDocument],
        embedder: Embedder,
        min_similarity: float = 0.30,
        use_hype: bool = True,
    ) -> None:
        self._docs = docs
        self._embedder = embedder
        self._min = min_similarity
        self._matrix: np.ndarray | None = None
        self._owner: list[int] = []  # representation-row index -> doc index
        self.enabled = False
        if embedder.available and docs:
            reps, owner = self._representations(docs, use_hype)
            vectors = embedder.embed(reps)
            if len(vectors) == len(reps):
                self._matrix = _l2_normalize(np.asarray(vectors, dtype=float))
                self._owner = owner
                self.enabled = True

    @staticmethod
    def _representations(
        docs: list[KnowledgeDocument], use_hype: bool
    ) -> tuple[list[str], list[int]]:
        reps: list[str] = []
        owner: list[int] = []
        for i, d in enumerate(docs):
            reps.append(f"{d.title} {d.text}")
            owner.append(i)
            if use_hype:
                for q in d.questions:  # HyPE: index the questions the doc answers
                    reps.append(q)
                    owner.append(i)
        return reps, owner

    def search(
        self,
        query: str,
        top_k: int = 3,
        *,
        on_llm: Callable[..., None] | None = None,  # seam-only; dense makes no LLM calls
    ) -> list[tuple[KnowledgeDocument, float]]:
        if not self.enabled or self._matrix is None or not query.strip():
            return []
        vectors = self._embedder.embed([query])
        if not vectors:
            return []
        q = _l2_normalize(np.asarray(vectors[0], dtype=float).reshape(1, -1))[0]
        sims = self._matrix @ q  # both L2-normalized → dot product == cosine similarity
        best: dict[int, float] = {}  # doc index -> best similarity across its representations
        for row, doc_i in enumerate(self._owner):
            s = float(sims[row])
            if s > best.get(doc_i, -1.0):
                best[doc_i] = s
        ranked = sorted(best.items(), key=lambda p: p[1], reverse=True)[:top_k]
        return [(self._docs[i], s) for i, s in ranked if s >= self._min]


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.clip(norms, 1e-9, None)
