"""Retriever seam + factory (Constitution II/V).

`Retriever` is the interface `support_rag` depends on (BM25 / dense / hybrid / advanced all satisfy
it). `build_retriever` wires the configured mode from `config.retrieval`. Hybrid is the default;
when no embedding key is available it degrades to BM25 (offline/CI), so nothing here requires a
network or a key to construct. Query expansion (RAG-Fusion / HyDE) is layered on top when enabled
*and* an LLM is available, and it too degrades to the base retriever when the LLM cannot answer.

`on_llm` lets a retriever report LLM token usage/cost (usage, cost_usd) for the trace; the lexical
and dense retrievers make no LLM calls and ignore it — only the advanced retriever uses it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from ..config import AppConfig
from ..llm.client import LLMClient, Usage
from .store import KB_DIR, BM25Store, KnowledgeDocument

OnLLM = Callable[[Usage, float], None]


@runtime_checkable
class Retriever(Protocol):
    def search(
        self, query: str, top_k: int = 3, *, on_llm: OnLLM | None = None
    ) -> list[tuple[KnowledgeDocument, float]]: ...


def build_retriever(
    config: AppConfig,
    llm: LLMClient | None = None,
    api_key: str | None = None,
) -> Retriever:
    """Build the retriever for `config.retrieval` (bm25 | dense | hybrid, + optional expansion)."""

    rc = config.retrieval
    store = BM25Store.from_kb_dir(KB_DIR, config.thresholds.grounding_min_score)
    base = _base_retriever(config, store, api_key)

    # The advanced techniques need an LLM; without one (or all off) return the base unchanged.
    if llm is not None and (rc.rag_fusion or rc.hyde or rc.self_query or rc.rerank):
        from .advanced import AdvancedRetriever

        categories = sorted({d.category for d in store.documents if d.category})
        return AdvancedRetriever(
            base,
            llm,
            model=config.models.primary,
            rag_fusion=rc.rag_fusion,
            n_queries=rc.rag_fusion_queries,
            hyde=rc.hyde,
            rrf_k=rc.rrf_k,
            top_k=rc.top_k,
            self_query=rc.self_query,
            rerank=rc.rerank,
            categories=categories,
        )
    return base


def _base_retriever(config: AppConfig, store: BM25Store, api_key: str | None) -> Retriever:
    rc = config.retrieval
    if rc.mode == "bm25":
        return store

    from .dense import DenseRetriever
    from .embedder import OpenAIEmbedder

    embedder = OpenAIEmbedder(api_key)  # `embedder: openai` is the only shipped backend today
    dense = DenseRetriever(store.documents, embedder, rc.dense_min_similarity, use_hype=rc.hype)
    if rc.mode == "dense":
        return dense

    from .hybrid import HybridRetriever

    return HybridRetriever(store, dense, rc.rrf_k, rc.top_k)
