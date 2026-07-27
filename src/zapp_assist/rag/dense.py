"""Dense (semantic) retriever: cosine similarity over embedded KB docs (hybrid RAG upgrade).

Embeds every KB document once at construction (via the `Embedder` seam), then ranks by cosine
similarity against the embedded query. It is `enabled` only if the embedder produced vectors;
otherwise it returns nothing, so the hybrid retriever degrades to lexical (BM25). Never raises.
"""

from __future__ import annotations

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
    ) -> None:
        self._docs = docs
        self._embedder = embedder
        self._min = min_similarity
        self._matrix: np.ndarray | None = None
        self.enabled = False
        if embedder.available and docs:
            vectors = embedder.embed([f"{d.title} {d.text}" for d in docs])
            if len(vectors) == len(docs):
                self._matrix = _l2_normalize(np.asarray(vectors, dtype=float))
                self.enabled = True

    def search(self, query: str, top_k: int = 3) -> list[tuple[KnowledgeDocument, float]]:
        if not self.enabled or self._matrix is None or not query.strip():
            return []
        vectors = self._embedder.embed([query])
        if not vectors:
            return []
        q = _l2_normalize(np.asarray(vectors[0], dtype=float).reshape(1, -1))[0]
        sims = self._matrix @ q  # both L2-normalized → dot product == cosine similarity
        order = np.argsort(-sims)[:top_k]
        return [(self._docs[i], float(sims[i])) for i in order if sims[i] >= self._min]


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.clip(norms, 1e-9, None)
