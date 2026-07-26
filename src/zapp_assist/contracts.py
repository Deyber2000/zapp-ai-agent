"""The canonical, validated turn output contract (Constitution VII).

Constructing any of these models runs schema validation; `assemble` therefore either builds a valid
`TurnResult` or substitutes `TurnResult.safe_fallback(...)`, which is guaranteed to validate. The
system NEVER emits a partial, untyped, or schema-invalid result.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GuardrailAction = Literal["allow", "refuse", "redact", "escalate"]
Severity = Literal["low", "medium", "high"]

_ISO_LANG = re.compile(r"^[a-z]{2}$")
_ISO_COUNTRY = re.compile(r"^[A-Z]{2}$")

# A minimal, always-valid safe reply per supported language (fail-closed default).
_SAFE_REPLY = {
    "es": "Lo siento, tuve un problema y lo marqué para que lo revise un compañero.",
    "en": "Sorry — I ran into a problem, so I've flagged this for a teammate to review.",
    "pt": "Desculpe — tive um problema, então sinalizei para um colega revisar.",
}


class GuardrailDecision(BaseModel):
    """A single triggered guardrail rule and the action taken (recorded in the contract)."""

    model_config = ConfigDict(extra="forbid")

    rule: str
    action: GuardrailAction
    severity: Severity
    detail: str | None = None


class Guardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: list[GuardrailDecision] = Field(default_factory=list)
    output: list[GuardrailDecision] = Field(default_factory=list)


class TurnResult(BaseModel):
    """The single object every turn returns — success, blocked, or degraded."""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1)
    detected_lang: str = Field(pattern=r"^[a-z]{2}$")
    active_lang: str = Field(pattern=r"^[a-z]{2}$")
    lang_confidence: float = Field(ge=0.0, le=1.0)
    final_normalized_text: str
    detected_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    confidence_score: float = Field(ge=0.0, le=1.0)
    needs_review: bool
    guardrails: Guardrails = Field(default_factory=Guardrails)

    @classmethod
    def safe_fallback(
        cls,
        *,
        reply: str | None = None,
        active_lang: str = "en",
        detected_lang: str | None = None,
        lang_confidence: float = 0.0,
        final_normalized_text: str = "",
        detected_country: str | None = None,
        confidence_score: float = 0.0,
        guardrails: Guardrails | None = None,
    ) -> TurnResult:
        """Always yields a schema-valid contract with `needs_review=true` (fail-safe, FR-002)."""

        active = active_lang.lower()
        if not _ISO_LANG.match(active):
            active = "en"
        detected = (detected_lang or active).lower()
        if not _ISO_LANG.match(detected):
            detected = active
        country = (
            detected_country
            if (detected_country and _ISO_COUNTRY.match(detected_country))
            else None
        )
        text = (reply or "").strip() or _SAFE_REPLY.get(active, _SAFE_REPLY["en"])
        return cls(
            reply=text,
            detected_lang=detected,
            active_lang=active,
            lang_confidence=_clamp(lang_confidence),
            final_normalized_text=final_normalized_text,
            detected_country=country,
            confidence_score=_clamp(confidence_score),
            needs_review=True,
            guardrails=guardrails or Guardrails(),
        )


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
