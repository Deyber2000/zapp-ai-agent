# Data Model: Multilingual Coherence & Language Policy (002)

Additive only. The `001` `TurnResult` contract is **unchanged**. New state is bounded and lives on the
existing `Session`; new signals live on the existing `Trace`.

## 1. Session switch-state (extends `memory/session_store.py::Session`)

Two bounded fields drive the sustained-switch policy (R3). Both default empty and reset on any turn
that matches `active_lang` or is weak/short/mixed.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `pending_switch_lang` | `str \| None` | `None` | a supported language, different from `active_lang`, currently accumulating consecutive confident turns |
| `pending_switch_count` | `int` | `0` | number of consecutive confident turns seen for `pending_switch_lang` |

**Existing (unchanged)**: `active_lang: str | None` — the locked session language.

**Transitions** (evaluated in `detect_language`, using the deterministic detection `d` and its
confidence `c`):

```
if active_lang is None:
    if d supported and c >= language_lock:   active_lang = d   (first lock)   [reset pending]
    else:                                     active_lang = fallback (unlocked, no reset needed)
else:  # already locked
    if d == active_lang or c < language_switch_min_confidence or d unsupported:
        reset pending (pending_switch_lang=None, count=0)          # weak / match → no switch
    elif d == pending_switch_lang:
        pending_switch_count += 1
        if pending_switch_count >= language_switch_turns:
            active_lang = d; reset pending                          # sustained switch
    else:  # a new candidate different language
        pending_switch_lang = d; pending_switch_count = 1
```

**Validation / invariants**: `pending_switch_lang` ∈ supported ∪ {None}; `pending_switch_count ≥ 0`;
`active_lang` only ever changes to a supported language. State is O(1) per session (Scalability).

## 2. Reply-language check (transient, in `graph/state.py::TurnState`)

Carried within a turn to feed the trace; **not** part of the contract.

| Field | Type | Meaning |
|---|---|---|
| `reply_lang` | `str \| None` | deterministic language of the (final) draft reply, or None if unverified-short/skipped |
| `reply_match` | `bool \| None` | whether the reply language matched `active_lang` (None = not verified) |
| `reply_corrected` | `bool` | whether the single correction re-ask was used |

## 3. Config additions (`config.py::Thresholds` + `config.yaml`)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `language_switch_min_confidence` | float | `0.75` | confidence floor for a turn to count toward a switch |
| `language_switch_turns` | int | `2` | consecutive confident turns in a new supported language to switch |
| `reply_verify_min_chars` | int | `15` | replies shorter than this skip verification (treated in-language) |

Existing and reused: `language_lock` (0.75), `languages.supported` (`[es, en, pt]`),
`languages.fallback` (`en`).

## 4. Trace signals (extends existing `Span.attrs`; no new types)

Language-fidelity signals for the `004` eval suite (FR-011/012), emitted as span attributes:

| Span | Attributes added |
|---|---|
| `detect_language` (existing) | `detected`, `active`, `confidence`, `switched` (bool), `pending` (lang or null) |
| `verify_reply_language` (new) | `active`, `reply_lang`, `reply_match`, `corrected`, `skipped_short` |

A turn's language-fidelity record is therefore reconstructable from its trace alone, with no reply-text
inspection.

## 5. Per-language templates (extends `graph/nodes/_util.py`)

A safe "let me make sure I answer you in your language" message per supported language, used when the
single correction still does not match — reuses the existing `tmpl()` + per-language dict pattern.

## Relationships

```
Session (per conversation)
  ├─ active_lang            (locked; may switch per policy)
  ├─ pending_switch_lang    (NEW, bounded switch accumulator)
  └─ pending_switch_count   (NEW)

TurnState (per turn)
  ├─ language: LanguageResult      (existing; from detect_language + fuse)
  ├─ reply_lang / reply_match / reply_corrected  (NEW, transient → trace)
  └─ draft_reply                   (existing; may be corrected/replaced by verify_reply_language)

Trace (per turn)
  └─ spans[*].attrs                (NEW language-fidelity attributes → consumed by 004)
```
