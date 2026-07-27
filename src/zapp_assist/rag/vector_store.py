"""Vector store seam for dense retrieval (Constitution II/V).

The dense retriever stores its embedded representations here and searches by cosine similarity. Two
interchangeable backends behind one protocol:

- `NumpyVectorStore` — exact in-memory cosine over a NumPy matrix. Zero extra dependency, offline,
  deterministic; the in-code default and the backend the unit tests use.
- `QdrantVectorStore` — a real vector database (Qdrant) in **embedded/local mode** by default
  (in-process, no server, no network), or a Qdrant **server** via `url`. Supports server-side
  **payload filtering** (category/topic) — the scale path for metadata-filtered retrieval.

Selected by `config.retrieval.vector_store`. At this KB size exact NumPy cosine is optimal; Qdrant
makes the store a real, swappable component and turns server-mode into a one-line config change
(`qdrant_url`) the day the KB outgrows memory. `qdrant_client` is lazily imported, so this module
loads (and the Numpy backend works) even if Qdrant is not installed.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class VectorStore(Protocol):
    """Stores embedded representations (with payloads) and searches them by cosine similarity."""

    def add(self, vectors: list[list[float]], payloads: list[dict[str, Any]]) -> None: ...

    def search(
        self, query: list[float], top_k: int, *, category: str | None = None
    ) -> list[tuple[dict[str, Any], float]]:
        """Top-`top_k` (payload, cosine-score), optionally restricted to a `category` payload."""
        ...


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.clip(norms, 1e-9, None)


class NumpyVectorStore:
    """Exact in-memory cosine store (default; zero-dependency, offline, deterministic)."""

    def __init__(self) -> None:
        self._matrix: np.ndarray | None = None
        self._payloads: list[dict[str, Any]] = []

    def add(self, vectors: list[list[float]], payloads: list[dict[str, Any]]) -> None:
        if not vectors:
            return
        self._matrix = _l2_normalize(np.asarray(vectors, dtype=float))
        self._payloads = list(payloads)

    def search(
        self, query: list[float], top_k: int, *, category: str | None = None
    ) -> list[tuple[dict[str, Any], float]]:
        if self._matrix is None or not query:
            return []
        q = _l2_normalize(np.asarray(query, dtype=float).reshape(1, -1))[0]
        sims = self._matrix @ q  # both L2-normalized → dot product == cosine similarity
        out: list[tuple[dict[str, Any], float]] = []
        for i in np.argsort(sims)[::-1]:  # descending similarity
            payload = self._payloads[int(i)]
            if category is not None and payload.get("category") != category:
                continue
            out.append((payload, float(sims[int(i)])))
            if len(out) >= top_k:
                break
        return out


class QdrantVectorStore:
    """A Qdrant-backed store — embedded/local mode by default, or a Qdrant server via `url`."""

    def __init__(self, url: str | None = None, collection: str = "kb") -> None:
        from qdrant_client import QdrantClient  # lazy: only when this backend is selected

        self._collection = collection
        # `location=":memory:"` runs Qdrant in-process (no server / no network); a url hits a server
        self._client = QdrantClient(url=url) if url else QdrantClient(location=":memory:")
        self._ready = False

    def add(self, vectors: list[list[float]], payloads: list[dict[str, Any]]) -> None:
        if not vectors:
            return
        from qdrant_client.models import Distance, PointStruct, VectorParams

        if self._client.collection_exists(self._collection):
            self._client.delete_collection(self._collection)
        self._client.create_collection(
            self._collection,
            vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE),
        )
        points = [
            PointStruct(id=i, vector=list(vectors[i]), payload=payloads[i])
            for i in range(len(vectors))
        ]
        self._client.upsert(self._collection, points=points)
        self._ready = True

    def search(
        self, query: list[float], top_k: int, *, category: str | None = None
    ) -> list[tuple[dict[str, Any], float]]:
        if not self._ready or not query:
            return []
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_filter = None
        if category is not None:
            query_filter = Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            )
        result = self._client.query_points(
            self._collection, query=list(query), limit=top_k, query_filter=query_filter
        )
        return [(dict(point.payload or {}), float(point.score)) for point in result.points]
