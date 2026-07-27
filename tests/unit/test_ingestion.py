"""Ingestion pipeline tests (spec 001, FR-023/024, SC-009).

All offline: chunking, validation, the content-addressed enrichment cache (cache / adopt / generate
/ missing), and a deterministic keyless rebuild over a temp KB. A scripted fake LLM covers the
generate path so no test touches the network.
"""

from __future__ import annotations

from pathlib import Path

from zapp_assist.ingestion.chunk import chunk_text
from zapp_assist.ingestion.enrich import (
    CACHE_PATH,
    EnrichmentCache,
    GeneratedQuestions,
    content_hash,
    hype_questions,
)
from zapp_assist.ingestion.pipeline import build_kb
from zapp_assist.ingestion.validate import validate_documents
from zapp_assist.llm.client import LLMResult, Usage
from zapp_assist.rag.store import KB_DIR, KnowledgeDocument

_LANGS = ["en", "es", "pt"]


def _doc(
    doc_id: str, *, text: str = "body text", lang: str = "en", questions: list[str] | None = None
) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=doc_id,
        title=doc_id.replace("_", " "),
        text=text,
        lang=lang,
        category="delivery",
        topic="reschedule",
        questions=questions or [],
    )


def _write_kb(kb_dir: Path, docs: list[KnowledgeDocument]) -> None:
    kb_dir.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (kb_dir / f"{doc.id}.json").write_text(doc.model_dump_json(), encoding="utf-8")


# ---- chunking ------------------------------------------------------------------------------------


def test_chunk_short_text_is_single_chunk() -> None:
    assert chunk_text("A short FAQ answer.") == ["A short FAQ answer."]
    assert chunk_text("   ") == []


def test_chunk_long_text_splits_within_budget() -> None:
    text = " ".join(f"Sentence number {i} explains a policy detail." for i in range(60))
    chunks = chunk_text(text, max_chars=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


# ---- validation ----------------------------------------------------------------------------------


def test_validate_flags_duplicate_id_and_unsupported_lang() -> None:
    docs = [_doc("a"), _doc("a"), _doc("b", lang="fr")]
    report = validate_documents(docs, supported_langs=_LANGS)
    assert not report.ok
    messages = " ".join(i.message for i in report.errors)
    assert "duplicate document id" in messages
    assert "unsupported language" in messages


def test_validate_warns_on_missing_translation() -> None:
    # Only EN present for delivery/reschedule → ES/PT missing → a coverage warning (not an error).
    report = validate_documents([_doc("only_en")], supported_langs=_LANGS)
    assert report.ok  # warnings do not block
    assert any("missing translations" in w.message for w in report.warnings)


# ---- enrichment cache ----------------------------------------------------------------------------


def test_cache_hit_and_adopt_and_missing() -> None:
    cache = EnrichmentCache()
    doc = _doc("d1", questions=["Q one", "Q two"])

    # No cache entry but the doc already has questions → adopt (self-seed).
    adopted = hype_questions(doc, cache=cache)
    assert adopted.status == "adopted" and adopted.questions == ["Q one", "Q two"]

    # Second call now hits the cache.
    assert hype_questions(doc, cache=cache).status == "cache"

    # A bare doc with no cache, no questions, no LLM → missing.
    assert hype_questions(_doc("d2"), cache=cache).status == "missing"


def test_cache_invalidates_when_text_changes() -> None:
    cache = EnrichmentCache()
    doc = _doc("d1", questions=["Q"])
    hype_questions(doc, cache=cache)
    changed = _doc("d1", text="different body", questions=[])
    # Same id, different text → hash mismatch → cache miss (here: missing, no LLM).
    assert cache.get(changed) is None
    assert content_hash(doc) != content_hash(changed)


class _ScriptedLLM:
    def __init__(self, questions: list[str]) -> None:
        self._q = questions
        self.calls = 0

    def complete(self, *, schema=None, **_):  # type: ignore[no-untyped-def]
        self.calls += 1
        return LLMResult(parsed=GeneratedQuestions(questions=self._q), usage=Usage(), cost_usd=0.01)


def test_generate_path_populates_cache_and_reports_cost() -> None:
    cache = EnrichmentCache()
    llm = _ScriptedLLM(["Generated one?", "Generated two?"])
    result = hype_questions(_doc("g1"), cache=cache, llm=llm, model="m", refresh=True)
    assert result.status == "generated"
    assert result.questions == ["Generated one?", "Generated two?"]
    assert result.cost_usd == 0.01 and llm.calls == 1
    # Now cached: an offline call returns it without the LLM.
    assert hype_questions(_doc("g1"), cache=cache).status == "cache"


# ---- pipeline (build) ----------------------------------------------------------------------------


def test_build_rejects_malformed_corpus_without_writing(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir(parents=True)
    # Two distinct files carrying the same id → a duplicate-id validation error.
    (kb / "one.json").write_text(_doc("dup").model_dump_json(), encoding="utf-8")
    (kb / "two.json").write_text(_doc("dup").model_dump_json(), encoding="utf-8")
    report = build_kb(kb_dir=kb, cache_path=tmp_path / "c.json", supported_langs=_LANGS)
    assert not report.ok
    assert not (tmp_path / "c.json").exists()  # failed closed — nothing written


def test_build_is_deterministic_and_keyless(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    cache = tmp_path / "c.json"
    _write_kb(kb, [_doc("a", questions=["Q a1", "Q a2"]), _doc("b", lang="es", questions=["Q b1"])])

    first = build_kb(kb_dir=kb, cache_path=cache, supported_langs=_LANGS)
    assert first.ok and first.adopted == 2 and first.missing == 0
    built_once = sorted(p.read_text(encoding="utf-8") for p in kb.glob("*.json"))

    # Rebuild with no LLM: served entirely from cache, byte-for-byte identical (SC-009).
    second = build_kb(kb_dir=kb, cache_path=cache, supported_langs=_LANGS)
    assert second.from_cache == 2 and second.adopted == 0
    assert sorted(p.read_text(encoding="utf-8") for p in kb.glob("*.json")) == built_once


def test_committed_kb_rebuilds_from_cache_offline() -> None:
    """The real committed KB rebuilds with no key — every doc is a cache hit, nothing missing."""

    report = build_kb(
        kb_dir=KB_DIR, cache_path=CACHE_PATH, supported_langs=_LANGS, write=False
    )
    assert report.ok
    assert report.missing == 0
    assert report.from_cache == report.total
