"""Embedding seam for dense retrieval (Constitution V — same adapter pattern as LLMClient).

`Embedder` is the interface; `OpenAIEmbedder` is the shipped backend (`text-embedding-3-small`). A
local sentence-transformers implementation is a documented drop-in behind the same protocol. The
embedder is `available` only when a key is present, and never raises — so the dense/hybrid retriever
degrades to lexical (BM25) when embeddings can't be produced (offline CI, transient outage).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    available: bool

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """OpenAI embeddings backend. The ONLY OpenAI-embedding import lives here (vendor isolation)."""

    def __init__(self, api_key: str | None, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key or None
        self._model = model
        self.available = bool(self._api_key)
        self._client: Any = None

    def _lazy_client(self) -> Any:
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=self._api_key)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input; [] on no key / empty input / any error (fail-safe)."""

        if not self.available or not texts:
            return []
        try:
            resp = self._lazy_client().embeddings.create(model=self._model, input=texts)
            return [list(item.embedding) for item in resp.data]
        except Exception:  # never raise — the retriever degrades to lexical
            return []
