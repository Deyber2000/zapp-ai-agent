"""Advanced retrieval: LLM query expansion, metadata filtering, and reranking over a base retriever.

Wraps any base `Retriever` and improves grounding in up to four config-gated stages:

- **RAG-Fusion** — the LLM rewrites the question into N alternative phrasings (synonyms, different
  ways a customer asks); each is retrieved and the ranked lists are RRF-fused, lifting docs found by
  *any* phrasing. Targets the lexical/vocabulary gap.
- **HyDE** (Hypothetical Document Embeddings) — the LLM drafts a short plausible answer passage used
  as an extra query, so retrieval matches answer-shaped text.
- **Self-Query** — the LLM classifies the question into one KB `category`, then the fused candidates
  are filtered to that category (a metadata filter *derived from the query*). It never filters down
  to nothing: an empty result falls back to the unfiltered ranking.
- **Rerank** — the LLM reorders the top fused candidates by how well each *answers* the question,
  correcting lexical mis-rankings before the final trim to `top_k`.

Every stage is opt-in and degrades safely: on a timeout / malformed / refused LLM result the stage
is a no-op, so with no key (or the mock in tests) this collapses to a single base search — the
offline path is unchanged. All LLM token usage is reported via `on_llm` so it reaches the trace.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..llm.client import LLMClient
from .hybrid import reciprocal_rank_fusion
from .store import KnowledgeDocument

if TYPE_CHECKING:
    from .retriever import Retriever

_CANDIDATES = 10  # per-variant retrieval depth / rerank pool (wider than top_k for fusion signal)

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
_SELFQUERY_SYSTEM = (
    "Classify the customer's support question into exactly one category from this list: "
    "{categories}. Reply with only the single best-matching category id. If none clearly fits, "
    "reply with an empty string."
)
_RERANK_SYSTEM = (
    "You rerank candidate support documents by how well each one ANSWERS the user's question. "
    "Reply with the document indices ordered from most to least relevant."
)


class QueryVariants(BaseModel):
    """RAG-Fusion output: alternative phrasings of the user's question."""

    queries: list[str] = []


class HypotheticalDoc(BaseModel):
    """HyDE output: a hypothetical answer passage used as an extra query."""

    passage: str = ""


class QueryFilter(BaseModel):
    """Self-Query output: the KB category the question belongs to (empty = no confident filter)."""

    category: str = ""


class Reranking(BaseModel):
    """Rerank output: candidate indices ordered from most to least relevant."""

    order: list[int] = []


class AdvancedRetriever:
    """Query expansion + Self-Query filter + rerank over a base retriever (all config-gated)."""

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
        self_query: bool = False,
        rerank: bool = False,
        categories: list[str] | None = None,
    ) -> None:
        self._base = base
        self._llm = llm
        self._model = model
        self._rag_fusion = rag_fusion
        self._n_queries = max(1, n_queries)
        self._hyde = hyde
        self._rrf_k = rrf_k
        self._top_k = top_k
        self._self_query = self_query
        self._rerank = rerank
        self._categories = [c.lower() for c in (categories or [])]

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
        ranked_ids = sorted(by_id, key=lambda i: rrf.get(i, 0.0), reverse=True)

        if self._self_query:
            ranked_ids = self._filter_by_category(query, ranked_ids, by_id, on_llm)
        if self._rerank:
            ranked_ids = self._rerank_candidates(query, ranked_ids, by_id, on_llm)

        return [by_id[i] for i in ranked_ids[:limit]]

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
        res = self._llm.complete(
            model=self._model,
            system=_FUSION_SYSTEM.format(n=self._n_queries),
            messages=[{"role": "user", "content": query}],
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
        res = self._llm.complete(
            model=self._model,
            system=_HYDE_SYSTEM,
            messages=[{"role": "user", "content": query}],
            schema=HypotheticalDoc,
            effort="low",
        )
        if on_llm:
            on_llm(res.usage, res.cost_usd)
        parsed = res.parsed
        if res.degraded or not isinstance(parsed, HypotheticalDoc) or not parsed.passage.strip():
            return None
        return parsed.passage.strip()

    def _filter_by_category(
        self,
        query: str,
        ranked_ids: list[str],
        by_id: dict[str, tuple[KnowledgeDocument, float]],
        on_llm: Callable[..., None] | None,
    ) -> list[str]:
        """Keep only candidates in the LLM-predicted category; never narrow to an empty result."""

        category = self._predict_category(query, on_llm)
        if not category:
            return ranked_ids
        matching = [i for i in ranked_ids if by_id[i][0].category.lower() == category]
        return matching or ranked_ids

    def _predict_category(self, query: str, on_llm: Callable[..., None] | None) -> str:
        if not self._categories:
            return ""
        res = self._llm.complete(
            model=self._model,
            system=_SELFQUERY_SYSTEM.format(categories=", ".join(self._categories)),
            messages=[{"role": "user", "content": query}],
            schema=QueryFilter,
            effort="low",
        )
        if on_llm:
            on_llm(res.usage, res.cost_usd)
        parsed = res.parsed
        if res.degraded or not isinstance(parsed, QueryFilter):
            return ""
        category = parsed.category.strip().lower()
        return category if category in self._categories else ""

    def _rerank_candidates(
        self,
        query: str,
        ranked_ids: list[str],
        by_id: dict[str, tuple[KnowledgeDocument, float]],
        on_llm: Callable[..., None] | None,
    ) -> list[str]:
        """Ask the LLM to reorder the top pool by answer-relevance; degrade to the fused order."""

        pool = ranked_ids[:_CANDIDATES]
        if len(pool) < 2:
            return ranked_ids
        listing = "\n".join(
            f"[{i}] {by_id[did][0].title}: {by_id[did][0].text[:160]}" for i, did in enumerate(pool)
        )
        res = self._llm.complete(
            model=self._model,
            system=_RERANK_SYSTEM,
            messages=[{"role": "user", "content": f"Question: {query}\n\nDocuments:\n{listing}"}],
            schema=Reranking,
            effort="low",
        )
        if on_llm:
            on_llm(res.usage, res.cost_usd)
        parsed = res.parsed
        if res.degraded or not isinstance(parsed, Reranking) or not parsed.order:
            return ranked_ids

        seen: set[int] = set()
        reordered: list[str] = []
        for idx in parsed.order:
            if 0 <= idx < len(pool) and idx not in seen:
                seen.add(idx)
                reordered.append(pool[idx])
        for i, did in enumerate(pool):  # append any indices the LLM omitted, original order
            if i not in seen:
                reordered.append(did)
        return reordered + ranked_ids[len(pool):]
