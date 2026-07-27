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


class Thresholds(BaseModel):
    review_confidence: float = 0.6
    language_lock: float = 0.75
    grounding_min_score: float = 1.0
    # Multilingual policy (002): confidence floor for a turn to count toward a language switch,
    # number of consecutive confident turns in a new supported language to switch, and the minimum
    # reply length to bother verifying the reply's language (short replies are treated in-language).
    language_switch_min_confidence: float = 0.75
    language_switch_turns: int = 2
    # A turn shorter than this cannot drive a language switch (too little signal to trust — stops a
    # one-word "ok"/"sí" from thrashing the session language).
    language_switch_min_chars: int = 12
    reply_verify_min_chars: int = 15


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
