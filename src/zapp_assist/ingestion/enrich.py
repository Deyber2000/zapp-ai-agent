"""Offline knowledge enrichment (spec 001, FR-024).

Generates the **HyPE** hypothetical questions each document answers (the signal that lets a user's
question match a stored *question* rather than only the answer prose). Enrichment is provider-backed
but never runs on the serving path: results are stored in a committed, content-addressed cache
(`enrichment_cache.json`) keyed by document id + a hash of its text, so rebuilding the KB offline is
deterministic and keyless. A live provider is used only under `--refresh`, and only for docs the
cache doesn't already cover — a curated cache entry is never regenerated (or re-billed).

Cache states, per document:
- **cache**    — a fresh cache entry exists (hash matches) → reuse it (always, even under refresh).
- **adopted**  — no cache entry, but the source file already carries questions → adopt them into the
  cache. This self-seeds the cache from the existing committed KB on the first build.
- **generated**— generated via the LLM under `--refresh`, for a doc the cache doesn't cover.
- **missing**  — no cache, no existing questions, and no LLM available → left empty (a warning).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..llm.client import LLMClient
from ..rag.store import KnowledgeDocument

CACHE_PATH = Path(__file__).resolve().parent / "enrichment_cache.json"
DEFAULT_N_QUESTIONS = 4

EnrichStatus = Literal["cache", "adopted", "generated", "missing"]


class GeneratedQuestions(BaseModel):
    """Structured-output schema for the enrichment LLM call."""

    questions: list[str] = []


class EnrichResult(BaseModel):
    questions: list[str]
    status: EnrichStatus
    cost_usd: float = 0.0


def content_hash(doc: KnowledgeDocument) -> str:
    """Content address for a doc's enrichment; changes only when its text changes."""

    raw = f"{doc.lang}\x1f{doc.title}\x1f{doc.text}".encode()
    return hashlib.sha256(raw).hexdigest()


class EnrichmentCache:
    """Committed `{doc_id: {hash, questions}}` cache; content-addressed so stale entries refresh."""

    def __init__(self, entries: dict[str, dict[str, object]] | None = None) -> None:
        self._entries = entries or {}
        self.dirty = False

    @classmethod
    def load(cls, path: Path = CACHE_PATH) -> EnrichmentCache:
        if not path.exists():
            return cls({})
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data)

    def get(self, doc: KnowledgeDocument) -> list[str] | None:
        entry = self._entries.get(doc.id)
        if entry and entry.get("hash") == content_hash(doc):
            questions = entry.get("questions", [])
            return [str(q) for q in questions] if isinstance(questions, list) else []
        return None

    def put(self, doc: KnowledgeDocument, questions: list[str]) -> None:
        self._entries[doc.id] = {"hash": content_hash(doc), "questions": questions}
        self.dirty = True

    def save(self, path: Path = CACHE_PATH) -> None:
        ordered = {k: self._entries[k] for k in sorted(self._entries)}
        path.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.dirty = False


def _clean(questions: list[str], n: int) -> list[str]:
    """De-dupe (case-insensitively), drop blanks, cap at n — deterministic order-preserving."""

    out: list[str] = []
    seen: set[str] = set()
    for q in questions:
        q = q.strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
    return out[:n]


def _generate(doc: KnowledgeDocument, *, llm: LLMClient, model: str, n: int) -> EnrichResult:
    system = (
        "You write hypothetical customer questions that a specific FAQ document fully answers. "
        "Output ONLY the requested JSON."
    )
    user = (
        f"Document (language={doc.lang}, category={doc.category}, topic={doc.topic}):\n"
        f"Title: {doc.title}\n\n{doc.text}\n\n"
        f"Write {n} short, natural questions a Zapp customer might ask that THIS document answers. "
        "Vary the phrasing and use everyday customer vocabulary and synonyms (e.g. parcel, "
        f"shipment, package) where relevant. Write every question in language '{doc.lang}'. "
        'Return JSON: {"questions": ["...", "..."]}.'
    )
    res = llm.complete(
        model=model,
        system=system,
        messages=[{"role": "user", "content": user}],
        schema=GeneratedQuestions,
        effort="low",
    )
    if res.degraded or not isinstance(res.parsed, GeneratedQuestions):
        return EnrichResult(questions=[], status="missing", cost_usd=res.cost_usd)
    return EnrichResult(
        questions=_clean(res.parsed.questions, n), status="generated", cost_usd=res.cost_usd
    )


def hype_questions(
    doc: KnowledgeDocument,
    *,
    cache: EnrichmentCache,
    llm: LLMClient | None = None,
    model: str = "",
    n: int = DEFAULT_N_QUESTIONS,
    refresh: bool = False,
) -> EnrichResult:
    """Resolve a doc's HyPE questions via cache / adoption / generation (see module docstring)."""

    # The cache is always authoritative: a hit is reused even under refresh, so an existing curated
    # document is never regenerated (and never re-billed). Refresh only fills the gaps below.
    cached = cache.get(doc)
    if cached is not None:
        return EnrichResult(questions=cached, status="cache")

    # No cache entry (a new or content-changed doc). Offline, adopt any authored questions.
    if not refresh and doc.questions:  # self-seed the cache from the already-authored KB
        adopted = _clean(doc.questions, n)
        cache.put(doc, adopted)
        return EnrichResult(questions=adopted, status="adopted")

    if llm is not None and model:  # refresh with a provider: generate for this uncached doc
        result = _generate(doc, llm=llm, model=model, n=n)
        if result.questions:
            cache.put(doc, result.questions)
        return result

    # Refresh requested but no LLM available: fall back to any authored questions, else leave empty.
    if doc.questions:
        adopted = _clean(doc.questions, n)
        cache.put(doc, adopted)
        return EnrichResult(questions=adopted, status="adopted")
    return EnrichResult(questions=[], status="missing")
