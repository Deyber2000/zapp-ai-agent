"""Onboarding intake node (US2, FR-009/010; Constitution X).

Slot-fill `full_name` + `phone` across turns. Each turn:
  1. the LLM extracts whatever fields the message contains (never fabricating the rest);
  2. a phone is normalized deterministically (`normalize_contact` tool → E.164 + country);
  3. the two signals are FUSED — the deterministic canonical/country win (Principle X), and if the
     LLM's own normalization disagrees the turn's confidence drops and it is flagged for review;
  4. we ask for exactly one still-missing field, or confirm once everything is collected.

Collected slots live on the `Session`, so a value given in an earlier turn is not re-requested.
"""

from __future__ import annotations

from pydantic import BaseModel

from ...memory.session_store import SlotValue
from ...tools.normalize import NormalizeContactArgs
from ..deps import Deps
from ..state import NormalizationSignal, TurnState
from ._util import (
    ONBOARDING_ASK_NAME,
    ONBOARDING_ASK_PHONE,
    ONBOARDING_CONFIRM,
    ONBOARDING_UNVERIFIED,
    add_span,
    now,
    tmpl,
)

# Required onboarding fields, in the order we ask for them.
REQUIRED_SLOTS = ("full_name", "phone")

_ONBOARD_SYSTEM = (
    "You collect onboarding details for Zapp Assist. From the user's message, extract ONLY the "
    "fields that are actually present — never invent a name or phone number. Return:\n"
    "- full_name: the person's full name if stated, else null.\n"
    "- phone_raw: the phone number exactly as written if present, else null.\n"
    "- region_hint: the ISO-3166 alpha-2 country code you can infer for the phone "
    "(e.g. MX, BR, US) from explicit context, else null.\n"
    "- phone_normalized: your own best E.164 rendering of the phone if present, else null. "
    "This is only a cross-check; the system normalizes deterministically."
)


class OnboardingExtraction(BaseModel):
    """What the LLM pulls from the user's message for slot-filling."""

    full_name: str | None = None
    phone_raw: str | None = None
    region_hint: str | None = None
    phone_normalized: str | None = None


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _fill_phone(state: TurnState, extraction: OnboardingExtraction, deps: Deps) -> None:
    """Normalize the phone deterministically and fuse it with the LLM's rendering (Principle X)."""

    raw = (extraction.phone_raw or "").strip()
    if not raw:
        return

    tool = deps.tools.get("normalize_contact")
    result = tool.run(NormalizeContactArgs(raw=raw, region_hint=extraction.region_hint))
    canonical = result.data.get("canonical") if result.ok else None
    country = result.data.get("country") if result.ok else None
    valid = bool(result.data.get("valid")) if result.ok else False

    # Fusion: deterministic canonical is authoritative; the LLM's guess only cross-checks it.
    llm_value = (extraction.phone_normalized or "").strip() or None
    agrees = True
    if llm_value and canonical:
        agrees = _digits(llm_value) == _digits(canonical)

    state.normalization = NormalizationSignal(
        raw=raw,
        canonical=canonical,
        country=country,
        valid=valid,
        llm_value=llm_value,
        agrees=agrees,
    )
    state.session.slots["phone"] = SlotValue(raw=raw, canonical=canonical, valid=valid)


def onboarding(state: TurnState, deps: Deps) -> TurnState:
    start = now()
    cfg = deps.config
    active = state.language.active_lang if state.language else cfg.languages.fallback
    state.intent = "onboarding"  # set regardless of how we arrived (agent handoff or the slot gate)

    res = deps.llm.complete(
        model=cfg.models.primary,
        system=_ONBOARD_SYSTEM,
        messages=[{"role": "user", "content": state.user_text}],
        schema=OnboardingExtraction,
        effort=cfg.effort_for("onboarding", "low"),  # type: ignore[arg-type]
    )
    state.trace.record_llm(res.usage, res.cost_usd)

    extraction = res.parsed if isinstance(res.parsed, OnboardingExtraction) else None
    if res.degraded or extraction is None:
        # Cannot extract → fail safe; downstream assembles a valid, flagged fallback contract.
        state.degraded = True
        add_span(state.trace, "onboarding", start, attrs={"degraded": True})
        return state

    slots = state.session.slots
    if extraction.full_name and extraction.full_name.strip():
        name = extraction.full_name.strip()
        slots["full_name"] = SlotValue(raw=name, canonical=name, valid=True)

    _fill_phone(state, extraction, deps)

    missing = [slot for slot in REQUIRED_SLOTS if slot not in slots]
    if missing:
        # Ask for exactly ONE missing field; never fabricate the others.
        asks = {"full_name": ONBOARDING_ASK_NAME, "phone": ONBOARDING_ASK_PHONE}
        state.draft_reply = tmpl(asks[missing[0]], active)
        add_span(
            state.trace,
            "onboarding",
            start,
            attrs={"asked": missing[0], "collected": sorted(slots)},
        )
        return state

    # Everything collected — confirm once. An unvalidated phone is flagged for review.
    name = slots["full_name"].canonical or slots["full_name"].raw
    phone_slot = slots["phone"]
    phone = phone_slot.canonical or phone_slot.raw
    template = ONBOARDING_CONFIRM if phone_slot.valid else ONBOARDING_UNVERIFIED
    state.draft_reply = tmpl(template, active).format(name=name, phone=phone)
    if not phone_slot.valid:
        state.needs_review_override = True

    add_span(
        state.trace,
        "onboarding",
        start,
        attrs={"complete": True, "phone_valid": phone_slot.valid},
    )
    return state
