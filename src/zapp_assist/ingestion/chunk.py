"""Deterministic text chunking for ingestion (spec 001, FR-023).

FAQ articles here are short — one chunk each — but the pipeline runs every document through the
chunker, so longer policy documents split into overlapping, embedding-friendly windows on natural
(paragraph → sentence) boundaries. Pure and deterministic: the same text always yields the same
chunks, so the built index is reproducible.
"""

from __future__ import annotations

import re

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _split_units(text: str) -> list[str]:
    """Break text into its smallest natural units — paragraphs, then sentences — for packing."""

    units: list[str] = []
    for para in _PARAGRAPH.split(text.strip()):
        para = para.strip()
        if not para:
            continue
        units.extend(s.strip() for s in _SENTENCE.split(para) if s.strip())
    return units


def chunk_text(text: str, *, max_chars: int = 900, overlap: int = 150) -> list[str]:
    """Split `text` into ≤ `max_chars` chunks, each carrying ~`overlap` chars of trailing context.

    A document shorter than `max_chars` returns a single chunk (`[text]`) — the common case for this
    FAQ KB. Splitting only ever happens on sentence/paragraph boundaries, so chunks stay readable.
    """

    normalized = text.strip()
    if len(normalized) <= max_chars:
        return [normalized] if normalized else []

    chunks: list[str] = []
    current = ""
    for unit in _split_units(normalized):
        if not current:
            current = unit
        elif len(current) + 1 + len(unit) <= max_chars:
            current = f"{current} {unit}"
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            # Resume from a whole-word boundary within the overlap so we never cut a word.
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1 :]
            current = f"{tail} {unit}".strip() if tail else unit
    if current:
        chunks.append(current)
    return chunks
