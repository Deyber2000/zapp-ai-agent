"""Knowledge ingestion pipeline (spec 001, FR-023–FR-027).

Turns authored source documents into the retrieval-ready knowledge base with a reproducible,
offline-by-default pipeline: **validate → chunk → enrich → build index**. Provider-dependent
enrichment (HyPE questions, translation gap-fill) is generated offline, cached in a committed
content-addressed cache, and never runs on the serving path — so rebuilding the KB is deterministic
and keyless in CI (FR-024). The `zapp-ingest` CLI is the one-command entry point.
"""

from __future__ import annotations

from .pipeline import BuildReport, build_kb, load_sources
from .validate import Issue, ValidationReport, validate_documents

__all__ = [
    "BuildReport",
    "Issue",
    "ValidationReport",
    "build_kb",
    "load_sources",
    "validate_documents",
]
