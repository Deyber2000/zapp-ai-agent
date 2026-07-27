"""BM25 lexical retrieval over the curated KB (Constitution X; research.md §7).

The sparse, deterministic, offline half of hybrid retrieval — and the floor the retrieval stack
degrades to when no embedding key is present, so grounded answering and the "decline rather than
hallucinate" behaviour never depend on a network. Tokenisation folds diacritics and case so ES/PT
queries match reliably.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel
from rank_bm25 import BM25Okapi

KB_DIR = Path(__file__).resolve().parent / "kb"

_TOKEN_SPLIT = re.compile(r"[^0-9a-z]+")

# Function words across ES/EN/PT. Removing them stops common words ("how", "order", "do", "de")
# from producing spurious grounding matches, so out-of-domain questions score ~0 and are declined.
_STOPWORDS = frozenset(
    """
    a an and any are as at be but by can could do does doing for from get got has have how
    i in is it its me my no not of on or per that the there this to up was what when where which
    who why will with you your
    al algo como con cual cuando cuanto de del donde el en es esta este hay la las lo los mas me mi
    mis no para pero por porque puedo que se si su sus te tu tus un una unas unos y
    ao as até com como da das de do dos e em essa esse esta este eu la mais me meu meus na nao nas
    no nos o os ou para pode por porque posso qual quando quanto que se seu seus sua suas te um uma
    voce você
    """.split()
)


class KnowledgeDocument(BaseModel):
    """A unit of grounding cited in support answers (FR-005/006).

    `category`/`topic` are structured metadata (enable metadata-filtered retrieval); `questions`
    are hypothetical questions the doc answers — indexed by the dense retriever (HyPE) so a user's
    question matches a *question* rather than only the answer prose. All default empty so a bare
    ``{id,title,text,lang}`` doc still validates.
    """

    id: str
    title: str
    text: str
    lang: str
    category: str = ""
    topic: str = ""
    questions: list[str] = []


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def tokenize(text: str) -> list[str]:
    return [
        tok
        for tok in _TOKEN_SPLIT.split(_fold(text).lower())
        if tok and tok not in _STOPWORDS
    ]


class BM25Store:
    """A BM25 retriever with an absolute score threshold for grounding."""

    def __init__(self, docs: list[KnowledgeDocument], threshold: float = 1.0) -> None:
        self._docs = docs
        self._threshold = threshold
        corpus = [tokenize(f"{d.title} {d.text}") for d in docs]
        # BM25Okapi needs a non-empty corpus; guard the degenerate empty-KB case.
        self._bm25 = BM25Okapi(corpus) if corpus else None

    @classmethod
    def from_kb_dir(cls, kb_dir: Path | str = KB_DIR, threshold: float = 1.0) -> BM25Store:
        directory = Path(kb_dir)
        docs: list[KnowledgeDocument] = []
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            docs.append(KnowledgeDocument.model_validate(payload))
        return cls(docs, threshold=threshold)

    @property
    def documents(self) -> list[KnowledgeDocument]:
        return self._docs

    def search(
        self,
        query: str,
        top_k: int = 3,
        *,
        on_llm: Callable[..., None] | None = None,  # seam-only; BM25 makes no LLM calls
    ) -> list[tuple[KnowledgeDocument, float]]:
        if self._bm25 is None or not query.strip():
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(self._docs, scores, strict=True), key=lambda p: p[1], reverse=True)
        return [(doc, float(score)) for doc, score in ranked[:top_k] if score >= self._threshold]
