"""Ingestion validation stage (spec 001, FR-023).

Structural + coverage checks over the knowledge base before it is built, so a malformed or
incomplete corpus fails the build (and CI) loudly instead of silently degrading grounding. Pure over
already loaded `KnowledgeDocument`s — no I/O, so it is trivially testable.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel

from ..rag.store import KnowledgeDocument

# A doc longer than this is retrieved as one unit but flagged so an author can split it (or rely on
# the chunker) — long single vectors dilute dense-retrieval precision.
MAX_DOC_CHARS = 1200


class Issue(BaseModel):
    level: Literal["error", "warning"]
    doc_id: str
    message: str


class ValidationReport(BaseModel):
    issues: list[Issue] = []

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


_REQUIRED_TEXT_FIELDS = ("title", "text", "category", "topic")


def validate_documents(
    docs: list[KnowledgeDocument], *, supported_langs: list[str]
) -> ValidationReport:
    """Validate fields, id uniqueness, language support, and cross-language coverage."""

    issues: list[Issue] = []
    supported = set(supported_langs)
    seen_ids: set[str] = set()
    # (category, topic) -> set of languages present, for the coverage check.
    coverage: dict[tuple[str, str], set[str]] = defaultdict(set)

    for doc in docs:
        if not doc.id.strip():
            issues.append(Issue(level="error", doc_id="<blank>", message="empty document id"))
        elif doc.id in seen_ids:
            issues.append(Issue(level="error", doc_id=doc.id, message="duplicate document id"))
        seen_ids.add(doc.id)

        for field in _REQUIRED_TEXT_FIELDS:
            if not str(getattr(doc, field)).strip():
                issues.append(
                    Issue(level="error", doc_id=doc.id, message=f"empty required field: {field}")
                )

        if doc.lang not in supported:
            issues.append(
                Issue(
                    level="error",
                    doc_id=doc.id,
                    message=f"unsupported language '{doc.lang}' (supported: {sorted(supported)})",
                )
            )

        if len(doc.text) > MAX_DOC_CHARS:
            issues.append(
                Issue(
                    level="warning",
                    doc_id=doc.id,
                    message=f"text is {len(doc.text)} chars (> {MAX_DOC_CHARS}); consider a split",
                )
            )

        if doc.category and doc.topic and doc.lang in supported:
            coverage[(doc.category, doc.topic)].add(doc.lang)

    for (category, topic), langs in sorted(coverage.items()):
        missing = supported - langs
        if missing:
            issues.append(
                Issue(
                    level="warning",
                    doc_id=f"{category}/{topic}",
                    message=f"missing translations for: {sorted(missing)}",
                )
            )

    return ValidationReport(issues=issues)
