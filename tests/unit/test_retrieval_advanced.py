"""Advanced retrieval — HyPE (dense indexes hypothetical questions), RAG-Fusion + HyDE expansion,
and degrade-to-base. All offline: a deterministic keyword stub embedder and a scripted fake LLM.
"""

from __future__ import annotations

from zapp_assist.llm.client import LLMResult, Usage
from zapp_assist.rag.advanced import AdvancedRetriever, HypotheticalDoc, QueryVariants
from zapp_assist.rag.dense import DenseRetriever
from zapp_assist.rag.store import KnowledgeDocument

# Axes include "parcel" — a synonym absent from the answer prose but present in a HyPE question.
_AXES = ["reschedule", "parcel", "password", "track"]


class _StubEmbedder:
    available = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            low = text.lower()
            vec = [1.0 if axis in low else 0.0 for axis in _AXES]
            out.append(vec if any(vec) else [0.25, 0.25, 0.25, 0.25])
        return out


def _doc(doc_id: str, text: str, questions: list[str]) -> KnowledgeDocument:
    return KnowledgeDocument(id=doc_id, title=doc_id, text=text, lang="en", questions=questions)


# ---- HyPE ----------------------------------------------------------------------------------------


def test_hype_recalls_via_hypothetical_question_not_answer_text() -> None:
    # The answer text has no "parcel"; only a hypothetical question does. HyPE must still recall it.
    resched = _doc("resched", "reschedule your delivery", ["can I move my parcel"])
    pwd = _doc("pwd", "reset your password", ["forgot my password"])
    dense = DenseRetriever([resched, pwd], _StubEmbedder(), min_similarity=0.5, use_hype=True)
    hits = dense.search("parcel")
    assert hits and hits[0][0].id == "resched"


def test_hype_off_misses_the_question_only_synonym() -> None:
    resched = _doc("resched", "reschedule your delivery", ["can I move my parcel"])
    dense = DenseRetriever([resched], _StubEmbedder(), min_similarity=0.5, use_hype=False)
    assert dense.search("parcel") == []  # no question indexed → the synonym is unreachable


# ---- RAG-Fusion / HyDE ---------------------------------------------------------------------------


class _RecordingBase:
    """Base retriever that records the queries it saw and returns a fixed hit per query token."""

    def __init__(self, table: dict[str, KnowledgeDocument]) -> None:
        self._table = table
        self.queries: list[str] = []

    def search(self, query: str, top_k: int = 3, *, on_llm=None):  # type: ignore[no-untyped-def]
        self.queries.append(query)
        hits = [(doc, 5.0) for token, doc in self._table.items() if token in query.lower()]
        return hits[:top_k]


class _ScriptedLLM:
    """Returns scripted expansion output by schema; `degraded=True` simulates no key / failure."""

    def __init__(self, *, paraphrases: list[str], passage: str, degraded: bool = False) -> None:
        self._paraphrases = paraphrases
        self._passage = passage
        self._degraded = degraded
        self.calls = 0

    def complete(self, *, schema=None, **_):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self._degraded:
            return LLMResult(degraded=True, usage=Usage())
        if schema is QueryVariants:
            return LLMResult(parsed=QueryVariants(queries=self._paraphrases), usage=Usage())
        if schema is HypotheticalDoc:
            return LLMResult(parsed=HypotheticalDoc(passage=self._passage), usage=Usage())
        return LLMResult(degraded=True, usage=Usage())


def test_rag_fusion_recalls_docs_only_a_paraphrase_reaches() -> None:
    a, b = _doc("A", "alpha", []), _doc("B", "beta", [])
    base = _RecordingBase({"alpha": a, "beta": b})
    llm = _ScriptedLLM(paraphrases=["beta please"], passage="")
    adv = AdvancedRetriever(
        base, llm, model="m", rag_fusion=True, n_queries=3, hyde=False  # type: ignore[arg-type]
    )
    ids = {doc.id for doc, _ in adv.search("alpha")}
    assert ids == {"A", "B"}  # "A" from the original query, "B" only via the paraphrase
    assert "beta please" in base.queries


def test_hyde_passage_used_as_extra_query() -> None:
    b = _doc("B", "beta", [])
    base = _RecordingBase({"beta": b})
    llm = _ScriptedLLM(paraphrases=[], passage="a beta answer")
    adv = AdvancedRetriever(
        base, llm, model="m", rag_fusion=False, n_queries=3, hyde=True  # type: ignore[arg-type]
    )
    ids = {doc.id for doc, _ in adv.search("unrelated")}
    assert ids == {"B"}  # only the HyDE passage matched "beta"
    assert "a beta answer" in base.queries


def test_expansion_degrades_to_single_base_search() -> None:
    a = _doc("A", "alpha", [])
    base = _RecordingBase({"alpha": a})
    llm = _ScriptedLLM(paraphrases=["x"], passage="y", degraded=True)
    adv = AdvancedRetriever(
        base, llm, model="m", rag_fusion=True, n_queries=3, hyde=True  # type: ignore[arg-type]
    )
    hits = adv.search("alpha")
    assert [doc.id for doc, _ in hits] == ["A"]
    assert base.queries == ["alpha"]  # LLM degraded → only the original query is retrieved


def test_expansion_reports_usage_via_on_llm() -> None:
    a = _doc("A", "alpha", [])
    base = _RecordingBase({"alpha": a})
    llm = _ScriptedLLM(paraphrases=["alpha again"], passage="")
    adv = AdvancedRetriever(
        base, llm, model="m", rag_fusion=True, n_queries=3, hyde=False  # type: ignore[arg-type]
    )
    seen: list[tuple[Usage, float]] = []
    adv.search("alpha", on_llm=lambda usage, cost: seen.append((usage, cost)))
    assert len(seen) == 1  # the one RAG-Fusion call was reported for the trace
