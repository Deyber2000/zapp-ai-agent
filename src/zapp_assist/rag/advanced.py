"""Advanced retrieval: LLM query expansion (RAG-Fusion + HyDE) over a base retriever.

Wraps any base `Retriever` and widens the query before retrieval, then fuses the per-variant ranked
lists with Reciprocal Rank Fusion (the same RRF used by the hybrid retriever):

- **RAG-Fusion** — the LLM rewrites the question into N alternative phrasings (synonyms, different
  ways a customer asks); each is retrieved and the lists are RRF-fused, lifting docs found by *any*
  phrasing. Directly targets the lexical/vocabulary gap.
- **HyDE** (Hypothetical Document Embeddings) — the LLM drafts a short plausible answer passage and
  that passage is used as an extra query, so retrieval matches answer-shaped text.

Both are opt-in (`config.retrieval.rag_fusion` / `.hyde`). Every LLM call degrades safely: on a
timeout / malformed / refused result the variant is simply dropped, so with no key (or the mock in
tests) expansion yields nothing and this collapses to a single base search — the offline path is
unchanged. Expansion token usage is reported through the `on_llm` callback so it lands in the trace.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..llm.client import LLMClient, Msg
from .hybrid import reciprocal_rank_fusion
from .store import KnowledgeDocument

if TYPE_CHECKING:
    from .retriever import Retriever

_CANDIDATES = 10  # per-variant depth to fuse over (wider than top_k so RRF has signal)

_FUSION_SYSTEM = (
    "You expand a customer's support question to improve retrieval. Produce {n} alternative "
    "phrasings of the SAME question that a different customer might use — vary the vocabulary and "
    "synonyms, keep the user's original language. Do not answer the question; only rephrase it."
)
_HYDE_SYSTEM = (
    "Write a brief, plausible support knowledge-base passage (1-2 sentences) that would directly "
    "answer the user's question, in the user's language. It is used only to improve retrieval, so "
    "it need not be factually correct — just realistic."
)


class QueryVariants(BaseModel):
    """RAG-Fusion output: alternative phrasings of the user's question."""

    queries: list[str] = []


class HypotheticalDoc(BaseModel):
    """HyDE output: a hypothetical answer passage used as an extra query."""

    passage: str = ""


class AdvancedRetriever:
    """Expands the query (RAG-Fusion / HyDE) then RRF-fuses per-variant retrievals over a base."""

    def __init__(
        self,
        base: Retriever,
        llm: LLMClient,
        *,
        model: str,
        rag_fusion: bool,
        n_queries: int,
        hyde: bool,
        rrf_k: int = 60,
        top_k: int = 3,
    ) -> None:
        self._base = base
        self._llm = llm
        self._model = model
        self._rag_fusion = rag_fusion
        self._n_queries = max(1, n_queries)
        self._hyde = hyde
        self._rrf_k = rrf_k
        self._top_k = top_k

    def search(
        self,
        query: str,
        top_k: int = 3,
        *,
        on_llm: Callable[..., None] | None = None,
    ) -> list[tuple[KnowledgeDocument, float]]:
        limit = top_k or self._top_k
        variants = self._expand(query, on_llm)

        ranked_lists: list[list[str]] = []
        by_id: dict[str, tuple[KnowledgeDocument, float]] = {}
        for variant in variants:
            hits = self._base.search(variant, top_k=_CANDIDATES)
            ranked_lists.append([doc.id for doc, _ in hits])
            for doc, score in hits:
                prev = by_id.get(doc.id)
                if prev is None or score > prev[1]:  # keep best base score for confidence
                    by_id[doc.id] = (doc, score)
        if not by_id:
            return []

        rrf = reciprocal_rank_fusion(ranked_lists, self._rrf_k)
        ranked_ids = sorted(by_id, key=lambda i: rrf.get(i, 0.0), reverse=True)[:limit]
        return [by_id[i] for i in ranked_ids]

    def _expand(self, query: str, on_llm: Callable[..., None] | None) -> list[str]:
        """Original query plus any HyDE passage and RAG-Fusion phrasings (de-duped, ordered)."""

        variants = [query]
        if self._hyde:
            passage = self._hypothetical(query, on_llm)
            if passage:
                variants.append(passage)
        if self._rag_fusion:
            variants.extend(self._paraphrases(query, on_llm))

        seen: set[str] = set()
        unique: list[str] = []
        for variant in variants:
            if variant and variant not in seen:
                seen.add(variant)
                unique.append(variant)
        return unique

    def _paraphrases(self, query: str, on_llm: Callable[..., None] | None) -> list[str]:
        messages: list[Msg] = [{"role": "user", "content": query}]
        res = self._llm.complete(
            model=self._model,
            system=_FUSION_SYSTEM.format(n=self._n_queries),
            messages=messages,
            schema=QueryVariants,
            effort="low",
        )
        if on_llm:
            on_llm(res.usage, res.cost_usd)
        parsed = res.parsed
        if res.degraded or not isinstance(parsed, QueryVariants):
            return []
        return [q.strip() for q in parsed.queries if q.strip()][: self._n_queries]

    def _hypothetical(self, query: str, on_llm: Callable[..., None] | None) -> str | None:
        messages: list[Msg] = [{"role": "user", "content": query}]
        res = self._llm.complete(
            model=self._model,
            system=_HYDE_SYSTEM,
            messages=messages,
            schema=HypotheticalDoc,
            effort="low",
        )
        if on_llm:
            on_llm(res.usage, res.cost_usd)
        parsed = res.parsed
        if res.degraded or not isinstance(parsed, HypotheticalDoc) or not parsed.passage.strip():
            return None
        return parsed.passage.strip()
