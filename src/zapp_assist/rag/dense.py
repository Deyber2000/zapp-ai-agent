"""Dense (semantic) retriever: cosine similarity over embedded KB docs (hybrid RAG upgrade).

Embeds every KB document once at construction (via the `Embedder` seam) and stores the vectors in a
`VectorStore` (in-memory NumPy by default, or Qdrant — see `vector_store.py`). With HyPE enabled it
also embeds each doc's *hypothetical questions* as extra representations pointing back to the same
doc, so a user's question can match a stored *question* (symmetric) rather than only the answer
prose — a doc scores by its best-matching representation. It is `enabled` only if the embedder
produced vectors; otherwise it returns nothing, so the hybrid retriever degrades to lexical (BM25).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .embedder import Embedder
from .store import KnowledgeDocument
from .vector_store import NumpyVectorStore, VectorStore

# Representations pulled from the store before reducing to per-doc best (docs have several via HyPE)
_REP_CANDIDATES = 25


class DenseRetriever:
    """Semantic retriever over the KB; disabled (returns []) when embeddings are unavailable."""

    def __init__(
        self,
        docs: list[KnowledgeDocument],
        embedder: Embedder,
        min_similarity: float = 0.30,
        use_hype: bool = True,
        store: VectorStore | None = None,
    ) -> None:
        self._docs = docs
        self._embedder = embedder
        self._min = min_similarity
        self._store: VectorStore = store or NumpyVectorStore()
        self.enabled = False
        if embedder.available and docs:
            reps, payloads = self._representations(docs, use_hype)
            vectors = embedder.embed(reps)
            if len(vectors) == len(reps):
                self._store.add(vectors, payloads)
                self.enabled = True

    @staticmethod
    def _representations(
        docs: list[KnowledgeDocument], use_hype: bool
    ) -> tuple[list[str], list[dict[str, Any]]]:
        reps: list[str] = []
        payloads: list[dict[str, Any]] = []
        for i, d in enumerate(docs):
            meta = {"owner": i, "category": d.category, "topic": d.topic}
            reps.append(f"{d.title} {d.text}")
            payloads.append(meta)
            if use_hype:
                for q in d.questions:  # HyPE: index the questions the doc answers
                    reps.append(q)
                    payloads.append(meta)
        return reps, payloads

    def search(
        self,
        query: str,
        top_k: int = 3,
        *,
        on_llm: Callable[..., None] | None = None,  # seam-only; dense makes no LLM calls
    ) -> list[tuple[KnowledgeDocument, float]]:
        if not self.enabled or not query.strip():
            return []
        vectors = self._embedder.embed([query])
        if not vectors:
            return []
        # Pull several representations, then reduce to each doc's best-matching representation.
        hits = self._store.search(list(vectors[0]), max(top_k * 5, _REP_CANDIDATES))
        best: dict[int, float] = {}  # doc index -> best similarity across its representations
        for payload, score in hits:
            owner = int(payload["owner"])
            if score > best.get(owner, -1.0):
                best[owner] = score
        ranked = sorted(best.items(), key=lambda p: p[1], reverse=True)[:top_k]
        return [(self._docs[i], s) for i, s in ranked if s >= self._min]
