"""Retriever seam + factory (Constitution II/V).

`Retriever` is the interface `support_rag` depends on (BM25 / dense / hybrid all satisfy it).
`build_retriever` wires the configured mode from `config.retrieval`. Hybrid is the default; when no
embedding key is available it degrades to BM25 (offline/CI), so nothing here requires a network or a
key to construct.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import AppConfig
from .store import KB_DIR, BM25Store, KnowledgeDocument


@runtime_checkable
class Retriever(Protocol):
    def search(self, query: str, top_k: int = 3) -> list[tuple[KnowledgeDocument, float]]: ...


def build_retriever(config: AppConfig, api_key: str | None = None) -> Retriever:
    """Build the retriever for `config.retrieval.mode` (bm25 | dense | hybrid)."""

    store = BM25Store.from_kb_dir(KB_DIR, config.thresholds.grounding_min_score)
    mode = config.retrieval.mode
    if mode == "bm25":
        return store

    from .dense import DenseRetriever
    from .embedder import OpenAIEmbedder

    embedder = OpenAIEmbedder(api_key)  # `embedder: openai` is the only shipped backend today
    dense = DenseRetriever(store.documents, embedder, config.retrieval.dense_min_similarity)
    if mode == "dense":
        return dense

    from .hybrid import HybridRetriever

    return HybridRetriever(store, dense, config.retrieval.rrf_k, config.retrieval.top_k)
