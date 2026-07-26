"""Deterministic contact normalization tool (US2 — Constitution X: signal fusion).

`phonenumbers` (offline, no network) parses a messy phone string into canonical E.164 plus its
ISO-3166 region. This is the DETERMINISTIC half of onboarding fusion: the `onboarding` node fuses
this result with the LLM's own extraction and — per Principle X — the deterministic value wins for
the correctness-critical canonical number/country, while any divergence lowers confidence and flags
the turn for review. The tool never raises; an unparseable/invalid number returns `ok=False`.
"""

from __future__ import annotations

import phonenumbers
from pydantic import BaseModel

from .registry import ToolRegistry, ToolResult


class NormalizeContactArgs(BaseModel):
    """Inputs to `normalize_contact`."""

    raw: str
    # ISO-3166 alpha-2 hint (e.g. "MX") used to resolve a national number that lacks a country code.
    region_hint: str | None = None


def _clean_region(region: str | None) -> str | None:
    if not region:
        return None
    code = region.strip().upper()
    return code if len(code) == 2 and code.isalpha() else None


def normalize_phone(raw: str, region_hint: str | None = None) -> ToolResult:
    """Parse a raw phone string → E.164 + ISO country (deterministic, offline). Never raises."""

    text = (raw or "").strip()
    if not text:
        return ToolResult(ok=False, error="empty")

    try:
        parsed = phonenumbers.parse(text, _clean_region(region_hint))
    except phonenumbers.NumberParseException:
        return ToolResult(ok=False, error="unparseable")

    valid = phonenumbers.is_valid_number(parsed)
    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    # `region_code_for_number` can return None or a non-geographic code ("001"); keep only a valid
    # ISO-3166 alpha-2 so it satisfies the contract's `detected_country` pattern downstream.
    country = _clean_region(phonenumbers.region_code_for_number(parsed))

    return ToolResult(
        ok=valid,
        data={"canonical": e164, "country": country, "valid": valid},
        error=None if valid else "invalid_number",
    )


class NormalizeContactTool:
    """Tool-protocol wrapper so the normalizer plugs into the `ToolRegistry` (Constitution II)."""

    name: str = "normalize_contact"
    description: str = (
        "Normalize a phone number to canonical E.164 and detect its ISO-3166 country, offline."
    )
    input_schema: type[BaseModel] = NormalizeContactArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, NormalizeContactArgs)
        return normalize_phone(args.raw, args.region_hint)


def register_normalize_tools(registry: ToolRegistry) -> None:
    """Register the US2 normalization tool(s) on a registry."""

    registry.register(NormalizeContactTool())
