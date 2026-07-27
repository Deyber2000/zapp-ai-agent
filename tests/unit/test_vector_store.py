"""VectorStore backends — NumPy (default) and Qdrant (embedded/local mode). All offline, no network.

Both backends run the same assertions (cosine ranking, top_k, payload filter), plus a numpy/qdrant
agreement check and a DenseRetriever-over-Qdrant HyPE recall (parity with NumPy).
"""

from __future__ import annotations

import pytest

from zapp_assist.rag.dense import DenseRetriever
from zapp_assist.rag.store import KnowledgeDocument
from zapp_assist.rag.vector_store import NumpyVectorStore, QdrantVectorStore, VectorStore

_BACKENDS = [NumpyVectorStore, QdrantVectorStore]  # QdrantVectorStore() runs in embedded local mode


def _seed(store: VectorStore) -> None:
    store.add(
        vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.9, 0.1, 0.0]],
        payloads=[
            {"owner": 0, "category": "delivery"},
            {"owner": 1, "category": "payments"},
            {"owner": 2, "category": "delivery"},
        ],
    )


@pytest.mark.parametrize("make", _BACKENDS)
def test_search_ranks_by_cosine(make) -> None:  # type: ignore[no-untyped-def]
    store = make()
    _seed(store)
    hits = store.search([1.0, 0.0, 0.0], top_k=3)
    owners = [p["owner"] for p, _ in hits]
    assert owners[0] == 0  # the exact match ranks first
    assert set(owners) == {0, 1, 2}
    assert hits[0][1] >= hits[-1][1]  # scores descending


@pytest.mark.parametrize("make", _BACKENDS)
def test_payload_category_filter(make) -> None:  # type: ignore[no-untyped-def]
    store = make()
    _seed(store)
    hits = store.search([1.0, 0.0, 0.0], top_k=3, category="payments")
    assert [p["owner"] for p, _ in hits] == [1]  # only the payments payload survives the filter


def test_numpy_and_qdrant_agree_on_top_doc() -> None:
    numpy_store, qdrant_store = NumpyVectorStore(), QdrantVectorStore()
    _seed(numpy_store)
    _seed(qdrant_store)
    top_numpy = numpy_store.search([0.0, 1.0, 0.0], top_k=1)[0][0]["owner"]
    top_qdrant = qdrant_store.search([0.0, 1.0, 0.0], top_k=1)[0][0]["owner"]
    assert top_numpy == top_qdrant == 1


class _StubEmbedder:
    """Deterministic 3-axis keyword embedder (no network) — mirrors the dense-retrieval tests."""

    available = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        axes = ["reschedule", "parcel", "password"]
        out = []
        for text in texts:
            low = text.lower()
            vec = [1.0 if axis in low else 0.0 for axis in axes]
            out.append(vec if any(vec) else [0.25, 0.25, 0.25])
        return out


def test_dense_retriever_over_qdrant_recalls_via_hype() -> None:
    # "parcel" is only in a HyPE question, not the answer text — Qdrant-backed dense recalls it.
    resched = KnowledgeDocument(
        id="resched", title="resched", text="reschedule your delivery", lang="en",
        questions=["can I move my parcel"],
    )
    pwd = KnowledgeDocument(
        id="pwd", title="pwd", text="reset your password", lang="en",
        questions=["forgot my password"],
    )
    dense = DenseRetriever(
        [resched, pwd], _StubEmbedder(), min_similarity=0.5, use_hype=True,
        store=QdrantVectorStore(),
    )
    hits = dense.search("parcel")
    assert hits and hits[0][0].id == "resched"
