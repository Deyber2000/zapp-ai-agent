"""Ingestion pipeline orchestration (spec 001, FR-023/024).

Runs the knowledge base through **validate → chunk → enrich → build index** and writes the
retrieval-ready `KnowledgeDocument` files back to the KB directory. Offline and deterministic by
default (enrichment served from the committed cache); a live provider is used only under `refresh`.
Validation errors fail closed — a broken corpus is never written.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from ..llm.client import LLMClient
from ..rag.store import KB_DIR, KnowledgeDocument
from .chunk import chunk_text
from .enrich import CACHE_PATH, DEFAULT_N_QUESTIONS, EnrichmentCache, EnrichStatus, hype_questions
from .validate import ValidationReport, validate_documents

# Canonical field order for a written KB doc (authored fields first, generated `questions` last).
_FIELD_ORDER = ("id", "title", "text", "lang", "category", "topic", "questions")


class DocBuildResult(BaseModel):
    id: str
    status: EnrichStatus
    chunks: int


class BuildReport(BaseModel):
    ok: bool
    total: int = 0
    from_cache: int = 0
    adopted: int = 0
    generated: int = 0
    missing: int = 0
    cost_usd: float = 0.0
    validation: ValidationReport = ValidationReport()
    results: list[DocBuildResult] = []


def load_sources(kb_dir: Path = KB_DIR) -> list[KnowledgeDocument]:
    """Load and validate every KB document (schema-level) from `kb_dir`."""

    return [doc for _, doc in _load_pairs(kb_dir)]


def _load_pairs(kb_dir: Path) -> list[tuple[Path, KnowledgeDocument]]:
    pairs: list[tuple[Path, KnowledgeDocument]] = []
    for path in sorted(kb_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        pairs.append((path, KnowledgeDocument.model_validate(payload)))
    return pairs


def _write_doc(path: Path, doc: KnowledgeDocument) -> None:
    obj = {field: getattr(doc, field) for field in _FIELD_ORDER}
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_kb(
    *,
    kb_dir: Path = KB_DIR,
    cache_path: Path = CACHE_PATH,
    supported_langs: list[str],
    llm: LLMClient | None = None,
    model: str = "",
    n_questions: int = DEFAULT_N_QUESTIONS,
    refresh: bool = False,
    write: bool = True,
) -> BuildReport:
    """Validate, enrich, and (re)build the KB. Returns a report; exits without writing on errors."""

    pairs = _load_pairs(kb_dir)
    docs = [doc for _, doc in pairs]

    validation = validate_documents(docs, supported_langs=supported_langs)
    if not validation.ok:
        return BuildReport(ok=False, total=len(docs), validation=validation)

    cache = EnrichmentCache.load(cache_path)
    results: list[DocBuildResult] = []
    total_cost = 0.0
    for path, doc in pairs:
        enriched = hype_questions(
            doc, cache=cache, llm=llm, model=model, n=n_questions, refresh=refresh
        )
        doc.questions = enriched.questions
        total_cost += enriched.cost_usd
        results.append(
            DocBuildResult(id=doc.id, status=enriched.status, chunks=len(chunk_text(doc.text)))
        )
        if write:
            _write_doc(path, doc)

    if write and cache.dirty:
        cache.save(cache_path)

    counts = Counter(r.status for r in results)
    return BuildReport(
        ok=True,
        total=len(docs),
        from_cache=counts["cache"],
        adopted=counts["adopted"],
        generated=counts["generated"],
        missing=counts["missing"],
        cost_usd=total_cost,
        validation=validation,
        results=results,
    )
