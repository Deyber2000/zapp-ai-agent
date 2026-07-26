# Feature Specification: Multilingual Coherence & Language Policy

**Feature Branch**: `002-multilingual`

**Created**: 2026-07-26

**Status**: Draft

**Input**: User description: "Deepen the baseline language handling delivered inline in spec 001 —
robust detection, verified in-language replies, a mid-session language-switch policy, graceful
degradation on unsupported/low-confidence input, and language-fidelity signals for evaluation."

## Overview

Zapp Assist serves users in **Spanish, English, and Portuguese**. Spec `001` established the turn
lifecycle and populated the language fields of the contract (`detected_lang`, `active_lang`,
`lang_confidence`) with a *baseline* mechanism: detect the language, lock it on the session, and ask
the model to reply in it. This feature makes multilingual behaviour **trustworthy and coherent**:

- the reply is **verified** to actually be in the user's language, not merely requested to be;
- the conversation **stays in one language** across turns, without thrashing on short or mixed input;
- the user can **deliberately switch** language mid-session and the assistant follows;
- **unsupported or unclear** language input degrades safely instead of guessing;
- every turn emits **language-fidelity signals** the evaluation suite (`004`) can score.

It is a cross-cutting concern that `001` explicitly delegates here (per `001` spec §Scope).

## Scope & Boundaries

**In scope**: language detection robustness across ES/EN/PT (including short, ambiguous, and
code-switched input); the policy for locking, persisting, and switching the session's active language;
output-side verification that a reply is in the active language, with a bounded correction path;
graceful degradation for unsupported/low-confidence languages; the per-turn language-fidelity signals
that evaluation consumes.

**Out of scope (delegated or excluded)**: adding languages beyond ES/EN/PT (the mechanism MUST be
configuration-extensible to more languages, but the curated supported set stays ES/EN/PT for this
feature); translating content between languages on the user's behalf; the evaluation harness, datasets,
and metric computation (→ `004`); the guardrail rule set (→ `003`); the turn contract and orchestration
themselves (owned by `001` — this feature refines behaviour behind the same contract fields).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A reply that is actually in the user's language (Priority: P1)

A user writes in Spanish. The assistant answers in Spanish — and the system **confirms** the reply is
in Spanish before sending it. If a reply comes back in the wrong language, the user never sees the
mismatched text: the system corrects it or flags the turn for review.

**Why this priority**: This is the core promise of a multilingual assistant and the concrete
improvement over `001`, which only *asks* the model to reply in-language. Verifying closes the gap
between "requested" and "guaranteed", and it is the single most visible quality signal to a user.

**Independent Test**: Send in-domain questions in ES, EN, and PT; verify each reply is in the request
language. Then force a wrong-language reply and verify the user receives either a corrected in-language
reply or a safe, review-flagged result — never the mismatched text.

**Acceptance Scenarios**:

1. **Given** a message in Spanish, **When** the assistant responds, **Then** the reply is in Spanish
   and the turn records that the reply language matched the active language.
2. **Given** the model produces a reply in the wrong language, **When** the turn is processed, **Then**
   the system attempts one correction to the active language; if it still does not match, the turn is
   flagged `needs_review = true` and a safe in-language message is returned instead of the mismatch.
3. **Given** any turn, **When** the assistant responds, **Then** `detected_lang`, `active_lang`, and
   `lang_confidence` are populated consistently with the message and the reply.

---

### User Story 2 - The conversation stays coherent, and switches only when I mean it (Priority: P2)

A user starts in Portuguese and continues for several turns, including short replies like "ok" or
"obrigado". The assistant stays in Portuguese. Later the user deliberately continues in English for a
few turns; the assistant follows into English. A single stray foreign word does not flip the language.

**Why this priority**: Coherence across turns is what makes the assistant feel reliable rather than
erratic. Getting the switch policy right — persist by default, switch on sustained intent, never
thrash — is the substance of "multilingual coherence".

**Independent Test**: Run a multi-turn session in one language including short/ambiguous turns and
verify the language never drifts; then send sustained input in a different supported language and
verify the active language updates; then send a one-off foreign phrase and verify it does **not**.

**Acceptance Scenarios**:

1. **Given** an active language locked earlier in the session, **When** the user sends a short or
   ambiguous message, **Then** the assistant keeps the active language rather than falling back or
   guessing a different one.
2. **Given** an active language, **When** the user sends sustained, confident input in a different
   **supported** language, **Then** the assistant adopts that language as the new active language.
3. **Given** an active language, **When** the user includes a single foreign phrase or mixes languages
   within one message, **Then** the active language does **not** change.

---

### User Story 3 - Safe handling of an unsupported or unclear language (Priority: P2)

A user writes in a language the assistant does not support (e.g., French), or sends input too short or
mixed to identify confidently. The assistant does not pretend to understand or reply in a language it
cannot sustain — it responds safely in the fallback language and flags the turn for review.

**Why this priority**: The safety/degradation envelope for language, mirroring the resilience posture
of `001`. Lower priority than the core in-language and coherence guarantees, but required for a
production-minded assistant.

**Independent Test**: Send input in an unsupported language and separately send genuinely
low-confidence input; verify each returns a valid contract, a safe reply in the fallback language,
`needs_review = true`, and never a reply in an unsupported language.

**Acceptance Scenarios**:

1. **Given** input in an unsupported language, **When** the turn is processed, **Then** the assistant
   replies in the configured fallback language and sets `needs_review = true`.
2. **Given** input whose language cannot be identified with sufficient confidence, **When** the turn is
   processed, **Then** the assistant keeps the session's active language (if any) or the fallback,
   replies safely, and does not assert a language it is unsure of.
3. **Given** any degraded-language turn, **When** the assistant responds, **Then** the contract remains
   schema-valid and the reply is never in an unsupported language.

---

### User Story 4 - Language-fidelity signals for evaluation (Priority: P3)

An operator running the evaluation suite needs to measure, across a dataset, how often the assistant
replies in the correct language and how confident detection was — without reading transcripts by hand.

**Why this priority**: Enables the `004` evaluation metric for language fidelity (SC-007 of `001`).
It adds observable signals rather than user-facing behaviour, so it is lowest priority here but is the
integration surface evaluation depends on.

**Independent Test**: Process a set of turns and confirm each one exposes the detected language, the
active language, a detection-confidence value, and whether the reply matched the active language.

**Acceptance Scenarios**:

1. **Given** any processed turn, **When** its record is inspected, **Then** it exposes the detected
   language, active language, detection confidence, and a reply-language-match indicator.
2. **Given** a batch of turns, **When** aggregated, **Then** a language-fidelity rate (share of replies
   in the active language) can be computed without inspecting reply text manually.

---

### Edge Cases

- **Short input** ("ok", "sí", "👍"): keep the locked active language; do not re-decide from too little
  signal.
- **Code-switching within one message** ("necesito help con mi order"): pick a single active language
  by the dominant/deterministic signal and do not thrash on subsequent turns.
- **Sustained switch vs one-off**: distinguish a genuine language change (sustained, confident) from a
  single borrowed word or quote.
- **Unsupported language**: never reply in it; fall back and flag.
- **Empty / whitespace-only input**: handled without error; active language unchanged.
- **First turn of a session**: no prior active language — pick the fallback until a confident detection
  locks a supported language.
- **Detection vs reply disagreement**: if the reply's language cannot be verified as the active
  language after one correction attempt, prefer a safe flagged result over shipping a mismatch.

## Requirements *(mandatory)*

### Functional Requirements

**Detection**
- **FR-001**: The system MUST identify the language of each user message across the supported set
  (ES/EN/PT) by combining a deterministic detector with the model's opinion, with the deterministic
  result taking precedence for the language choice.
- **FR-002**: The system MUST handle short, ambiguous, and mixed-language input without erratic
  language changes, preferring the session's established language when the new signal is weak.

**In-language replies (verification)**
- **FR-003**: The system MUST reply in the session's active language on every turn.
- **FR-004**: The system MUST verify that the produced reply is actually in the active language before
  returning it.
- **FR-005**: When a reply is not in the active language, the system MUST attempt exactly one
  correction to the active language; if it still does not match, the system MUST return a safe
  in-language message and set `needs_review = true` rather than send the mismatched reply.

**Language policy (lock / persist / switch)**
- **FR-006**: The system MUST lock a session's active language on the first sufficiently confident
  detection of a supported language and persist it across turns.
- **FR-007**: The system MUST update the active language when the user provides sustained, confident
  input in a different supported language, per a configurable switch policy.
- **FR-008**: The system MUST NOT change the active language on a single foreign phrase, a mixed
  message, or a low-confidence/short message.

**Graceful degradation**
- **FR-009**: For an unsupported language, the system MUST reply in the configured fallback language and
  set `needs_review = true`, and MUST NOT reply in the unsupported language.
- **FR-010**: For input whose language cannot be confidently identified, the system MUST retain the
  active language (or the fallback if none) and respond safely without asserting an uncertain language.

**Observability / evaluation signals**
- **FR-011**: The system MUST record, per turn, the detected language, the active language, a detection
  confidence, and whether the reply matched the active language.
- **FR-012**: These signals MUST be available to the evaluation suite (`004`) without manual inspection
  of reply text.

**Configuration**
- **FR-013**: Supported languages, the fallback language, and the lock/switch/confidence thresholds
  MUST be configuration, not hardcoded, and the supported set MUST be extensible to additional
  languages without code changes to the policy.

**Compatibility**
- **FR-014**: This feature MUST operate behind the existing turn contract and populate the same
  language fields defined in `001`; it MUST NOT break the `001` contract or its guarantees.

### Key Entities *(include if feature involves data)*

- **Language Signal**: a per-turn detection result — detected language + a confidence value — from the
  deterministic detector fused with the model's opinion.
- **Active Language State**: the session-scoped locked language plus the information needed to apply the
  switch policy (e.g., recent per-turn language evidence).
- **Reply-Language Verification**: the check that a produced reply is in the active language, its
  outcome (match / mismatch), and the correction attempt if any.
- **Language-Fidelity Record**: the per-turn signals (detected, active, confidence, reply-match) that
  evaluation aggregates.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the ES/EN/PT evaluation set, ≥ 98% of turns produce a reply in the session's active
  language (after the correction path).
- **SC-002**: 100% of injected wrong-language replies are either corrected to the active language or
  returned as a safe, `needs_review = true` result — 0 mismatched replies are shipped.
- **SC-003**: Across a multi-turn session in one language that includes short/ambiguous turns, the
  active language changes 0 times due to those weak-signal turns.
- **SC-004**: A sustained switch (confident input in another supported language for the configured
  number of turns) updates the active language in ≥ 95% of cases, while a single foreign phrase updates
  it in 0% of cases.
- **SC-005**: 100% of unsupported-language and low-confidence turns return a schema-valid contract, a
  safe reply in the fallback language, and `needs_review = true`, with 0 replies in an unsupported
  language.
- **SC-006**: 100% of turns expose the four language-fidelity signals, enabling a language-fidelity
  rate to be computed automatically over any dataset.

## Assumptions

- Supported languages are ES/EN/PT; the fallback is English (configurable). The detection mechanism is
  extensible to more languages via configuration, but expanding the curated set is out of scope here.
- "Sufficiently confident" detection and "sustained switch" are governed by configurable thresholds
  (e.g., a confidence floor to lock, and a number of consecutive confident turns to switch); default
  values are chosen at design time and tunable as configuration.
- Reply-language verification reuses the same detection capability applied to the assistant's reply; a
  single correction attempt is a deliberate bound (fail safe over loop).
- The language-fidelity signals are exposed as observable per-turn data for evaluation; whether they
  extend the contract or ride in the turn's trace is a design decision left to `plan.md`, provided the
  `001` contract remains intact.
- The assistant does not translate on the user's behalf; it converses in the user's language.
