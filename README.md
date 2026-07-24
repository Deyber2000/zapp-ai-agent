# zapp-ai-agent

A production-minded, **multilingual conversational AI agent**, built with **Spec-Driven Development (SDD)**.

> Take-home assessment for the **AI Agent Engineer** position at Zapp Global.

---

## Methodology: Spec-Driven Development

This repository is developed spec-first: every feature is **specified, designed, and broken into tasks before implementation**. The git history is intended to reflect the flow `specify → design → plan → implement → verify`, with specs committed before code.

The SDD framework used is **[GitHub Spec Kit](https://github.com/github/spec-kit)**, driven through Claude Code skills. Feature artifacts live under `specs/<NNN-feature>/`.

### Spec Kit ↔ assessment file mapping

Spec Kit uses fixed artifact filenames. They map 1:1 onto the structure requested in the assessment brief:

| Assessment deliverable | This repo (Spec Kit) | Contents |
| --- | --- | --- |
| `specs/<feature>/requirements.md` | `specs/<NNN-feature>/spec.md` | User stories, acceptance criteria, functional requirements |
| `specs/<feature>/design.md` | `specs/<NNN-feature>/plan.md` (+ `research.md`, `data-model.md`, `contracts/`) | Architecture, components, contracts, open decisions |
| `specs/<feature>/tasks.md` | `specs/<NNN-feature>/tasks.md` | Verifiable implementation plan (exact match) |

**Decision:** we use Spec Kit's native filenames rather than editing the tool's internals to rename them. This keeps the tooling upgrade-safe and idiomatic; the mapping above makes the correspondence explicit.

### Workflow (Spec Kit skills)

```
/speckit-constitution  →  /speckit-specify  →  /speckit-plan  →  /speckit-tasks  →  /speckit-implement
        (optional: /speckit-clarify, /speckit-analyze, /speckit-checklist)
```

---

## Planned specs

Per the assessment, at least four specs:

- **`multilingual`** — language detection, in-language replies, cross-session language coherence, graceful degradation on unsupported languages (≥ 3 languages: ES / EN / PT).
- **`guardrails`** — input and output guardrails.
- **`evaluation`** — one-command, CI-ready eval suite + pre-generated report (task success, language fidelity, guardrail precision/recall, LLM-as-judge quality, latency & cost).
- **`<domain>`** — the chosen product domain _(TBD)_.

---

## Status

🚧 **Setup complete** — SDD tooling (GitHub Spec Kit) scaffolded. Specs and implementation in progress.

## Run instructions

_TBD — documented alongside implementation._

## Trade-offs & known limitations

_TBD — captured here as decisions are made._
