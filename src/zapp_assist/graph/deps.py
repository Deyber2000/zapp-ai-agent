"""Injected dependencies for nodes (Constitution II: Modularity).

Bundling the registries/clients here keeps nodes as pure `(state, deps) -> state` handlers and
keeps LangGraph out of node code — only `build.py` knows about the orchestration engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import AppConfig
from ..guardrails.registry import GuardrailRegistry
from ..lang.detector import LanguageDetector
from ..llm.client import LLMClient
from ..tools.registry import ToolRegistry

if TYPE_CHECKING:  # avoid importing rank_bm25 here
    from ..rag.store import BM25Store


@dataclass
class Deps:
    config: AppConfig
    llm: LLMClient
    detector: LanguageDetector
    guardrails: GuardrailRegistry
    tools: ToolRegistry
    rag: BM25Store | None = None
