"""Config-as-data loader (Constitution V: Future-Proofing).

Models, thresholds, supported languages, per-node effort, and the pricing table are read from
`config.yaml` at the repo root; secrets come from the environment via `.env` (never committed).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .contracts import GuardrailAction, Severity

# `config.py` lives at src/zapp_assist/config.py → parents[2] is the repo root, regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


class ModelPricing(BaseModel):
    """Per-model pricing (USD per 1M tokens) and temperature capability."""

    input_per_1m: float
    output_per_1m: float
    temperature_capable: bool = False


class ModelsConfig(BaseModel):
    primary: str
    fallback: str | None = None


class LanguagesConfig(BaseModel):
    supported: list[str]
    fallback: str
    # Honor an explicit request to switch language ("reply in English") immediately, over the
    # sustained-switch accumulator (002) — a direct instruction shouldn't need to be repeated.
    honor_explicit_switch: bool = True


class Thresholds(BaseModel):
    review_confidence: float = 0.6
    language_lock: float = 0.75
    grounding_min_score: float = 1.0
    # Multilingual policy (002): confidence floor for a turn to count toward a language switch,
    # number of consecutive confident turns in a new supported language to switch, and the minimum
    # reply length to bother verifying the reply's language (short replies are treated in-language).
    language_switch_min_confidence: float = 0.75
    language_switch_turns: int = 2
    # A detection is "confident" (to lock or switch) when its absolute confidence clears the floor
    # OR its margin over the runner-up clears this. lingua normalises mass across candidates, so
    # es/pt split it and rarely reach an absolute 0.75 even when unambiguous — the margin rescues
    # those (a right answer the floor would discard; ~35% of es first-turns failed to lock).
    language_confident_min_margin: float = 0.15
    # A switch needs >= this many words. Single-word borrowed tokens (ok/thanks/obrigado) read as
    # confident in another language but are socially borrowed, and the confidence floor can't gate
    # them; a genuine short switch is always >= 2 words. (sí/no are already confidence-blocked.)
    language_switch_min_words: int = 2
    reply_verify_min_chars: int = 15


class RetrievalConfig(BaseModel):
    """RAG retrieval policy (hybrid RAG). `hybrid` fuses BM25 + dense; degrades to BM25 when no
    embedding key is available (offline/CI)."""

    mode: Literal["bm25", "dense", "hybrid"] = "hybrid"
    embedder: Literal["openai"] = "openai"
    # Dense vector backend: "numpy" (exact in-memory cosine, zero-dep) or "qdrant" (a real vector
    # DB; embedded/in-process when qdrant_url is null, else a Qdrant server). Degrades to numpy if
    # qdrant-client is missing. No embedding key → dense is off entirely (BM25 floor).
    vector_store: Literal["numpy", "qdrant"] = "qdrant"
    qdrant_url: str | None = None
    top_k: int = 3
    rrf_k: int = 60
    dense_min_similarity: float = 0.30
    # Index each doc's hypothetical questions on the dense side (HyPE). Offline-safe: without an
    # embedding key the dense retriever is disabled anyway, so this has no effect on the CI path.
    hype: bool = True
    # LLM query expansion / filtering / reranking (opt-in; need a key — each degrades to the base
    # retriever without one, and every enhancement is independently toggleable, config-as-data).
    rag_fusion: bool = False  # rewrite the query into N phrasings, RRF-fuse their retrievals
    rag_fusion_queries: int = 3
    hyde: bool = False  # draft a hypothetical answer passage and use it as an extra query
    self_query: bool = False  # LLM predicts a category filter from the query (metadata filter)
    rerank: bool = False  # LLM reranks the fused candidates by how well they answer the question


class RulePolicy(BaseModel):
    """Per-rule policy override (003). Absent fields keep the rule's code defaults."""

    enabled: bool = True
    severity: Severity | None = None
    action: GuardrailAction | None = None


class GuardrailsConfig(BaseModel):
    """Guardrail policy (003): toggle the semantic layer + per-rule overrides keyed by rule id."""

    semantic_enabled: bool = False
    policy: dict[str, RulePolicy] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """The fully-typed view of `config.yaml`."""

    provider: Literal["anthropic", "openai"] = "anthropic"
    models: ModelsConfig
    node_effort: dict[str, str] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    languages: LanguagesConfig
    pricing: dict[str, ModelPricing] = Field(default_factory=dict)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)

    def pricing_for(self, model: str) -> ModelPricing | None:
        return self.pricing.get(model)

    def temperature_capable(self, model: str) -> bool:
        p = self.pricing.get(model)
        return bool(p and p.temperature_capable)

    def effort_for(self, node: str, default: str = "medium") -> str:
        return self.node_effort.get(node, default)


class Settings(BaseSettings):
    """Environment-sourced secrets/config. `.env` is git-ignored."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None


@lru_cache(maxsize=8)
def load_config(path: str | None = None) -> AppConfig:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
