<!--
Constitution — initial ratification (v1.0.0)
- Ratified: 2026-07-24 | Last amended: 2026-07-24
- Part A — Foundational Agentic Principles:
    I. Scalability, II. Modularity, III. Resilience & Security,
    IV. Continuous Learning, V. Future-Proofing
- Part B — Application Principles:
    VI. Spec-Driven & Traceable (NON-NEGOTIABLE), VII. Structured, Validated Output Contract,
    VIII. Guardrails by Default (Fail-Safe), IX. Multilingual Coherence & Graceful Degradation,
    X. Signal Fusion & Deterministic Safety, XI. Observability & Eval-Driven Verification
- Sections: Technology & Architecture Constraints; Development Workflow & Quality Gates; Governance
- Dependent templates reviewed for alignment:
    ✅ .specify/templates/plan-template.md   (Constitution Check gate present)
    ✅ .specify/templates/spec-template.md    (scope/requirements sections compatible)
    ✅ .specify/templates/tasks-template.md   (task categories cover modularity/resilience/observability/eval)
- Deferred TODOs: none
-->

# Zapp Assist Constitution

Zapp Assist is a multilingual, production-minded conversational agent. This constitution defines the
non-negotiable engineering principles that govern every spec, plan, task, and line of code in this
repository. It supersedes convenience and personal preference; when a decision conflicts with a
principle here, the principle wins or the principle is formally amended (see Governance).

Principles are organized in two parts:

- **Part A — Foundational Agentic Principles**: general principles for building effective agentic
  systems (scalability, modularity, resilience, continuous learning, future-proofing). They are
  interpreted at this project's assessment scope: we adopt the design posture and implement it
  pragmatically, documenting explicitly where something is *designed-for* rather than *fully built*.
- **Part B — Application Principles**: the specific mandates of the Zapp Assist agent and the
  assessment brief (output contract, guardrails, multilingual, signal fusion, observability/eval).

---

## Part A — Foundational Agentic Principles

### I. Scalability

The system MUST be horizontally scalable **by construction**: node/tool handlers are stateless and
free of hidden side effects, all session/conversation state lives behind a storage interface
(in-memory implementation now, swappable for Redis/DB with no node changes), and independent work is
parallelizable. At assessment scope we do NOT deploy autoscaling infrastructure; we guarantee the
design does not preclude it and we document the scaling path. Rationale: a support agent that handles
10 turns/min must not need a rewrite to handle 1,000 — scalability is a property of the architecture,
not a later retrofit.

### II. Modularity

The agent is composed of independent, interchangeable components behind clear, typed interfaces: an
explicit orchestration graph of typed nodes, a **tool registry**, a **guardrail registry**, a
provider-abstracted LLM client, a pluggable language detector, and a session-store interface. Adding
or changing a tool, guardrail, or model MUST NOT require editing the orchestrator or unrelated nodes.
No component hardcodes another's internals. Rationale: hardcoding tools into the agent service forces
a full redeploy for any small change; clear seams make maintenance and adaptation cheap.

### III. Resilience & Security

The system MUST handle errors, timeouts, malformed responses, and unexpected conditions gracefully.
Every model/network/tool call has a timeout, bounded retries with backoff, and malformed-response
repair, with a defined fallback (alternate model or safe canned behavior) and redundancy for
critical paths. Security is part of resilience: untrusted input is treated as hostile (see Guardrails),
secrets never enter logs or the repo, and tool inputs are validated. Low confidence, tool failure, or
signal divergence routes to `needs_review` / human escalation rather than guessing, and the agent
stays contract-valid even when a dependency fails. Rationale: an agent without retry/fallback logic
crashes on a single failed API call and leaves the user stranded.

### IV. Continuous Learning

The agent MUST improve from experience through (a) **in-context learning** — session memory that
carries relevant prior turns and corrections forward — and (b) a **feedback loop**: low-confidence
and `needs_review` turns, guardrail triggers, and user corrections are captured in a structured form
that flows into the evaluation dataset to drive refinement. At assessment scope this is
offline/eval-driven refinement (grow the eval set, tune prompts/thresholds), NOT online model
training. Rationale: agents that ignore feedback loops keep making the same mistakes — like
misclassifying an intent or failing to escalate a critical issue.

### V. Future-Proofing

The system MUST be built on open standards and swappable abstractions to avoid vendor lock-in: typed
schemas (Pydantic/JSON Schema) for data, standard structured logging/tracing conventions for
observability, and a provider-agnostic LLM interface so switching or A/B-testing models is an adapter
change, not a rewrite. Prompt formats and model-specific quirks live behind the abstraction, never in
node logic. Configuration (models, thresholds, languages, tools) is data, not code. Rationale: tightly
coupling to one vendor's prompt format makes switching models painful and blocks experimentation.

---

## Part B — Application Principles

### VI. Spec-Driven & Traceable (NON-NEGOTIABLE)

Specs precede code. No implementation is written before a committed specification (`spec.md`),
design (`plan.md`), and task breakdown (`tasks.md`) exist for that feature. Every commit MUST trace
to a spec and/or task, and the git history MUST reflect `specify → design → plan → implement →
verify`. Rationale: the repository itself is the primary evidence of engineering discipline;
requirements MUST NOT live only in chat history.

### VII. Structured, Validated Output Contract

Every conversational turn MUST emit the canonical JSON contract (`reply`, `detected_lang`,
`active_lang`, `lang_confidence`, `final_normalized_text`, `detected_country`, `confidence_score`,
`needs_review`, `guardrails.input`, `guardrails.output`), defined once as a typed schema and
validated before it leaves the system. Malformed model output MUST be repaired or the turn MUST fail
closed with `needs_review = true`; the system MUST NEVER emit partial, untyped, or schema-invalid
output. Rationale: a stable typed contract is what makes the agent composable, testable, and safe to
integrate.

### VIII. Guardrails by Default, Fail-Safe

Input and output guardrails run on EVERY turn — never opt-in. Input guardrails screen for prompt
injection, PII, abuse, and out-of-scope requests; output guardrails screen for PII leakage,
ungrounded claims, and policy violations. On any violation the system MUST degrade safely (refuse,
redact, or escalate) and MUST NEVER leak unsafe content or private data. Every guardrail decision
(triggered rule + action) is recorded in the output contract. Rationale: safety is a property of the
default path, not an add-on.

### IX. Multilingual Coherence & Graceful Degradation

The agent MUST detect the user's language, reply in it, and lock the session's `active_lang` for
coherence across turns. It MUST support at least ES, EN, and PT. On unsupported or low-confidence
detection it MUST degrade gracefully: fall back to a documented default language, set
`needs_review = true`, and never silently answer in the wrong language. Rationale: an inconsistent or
wrong-language reply is a correctness failure, not a cosmetic one.

### X. Signal Fusion & Deterministic Safety

The agent FUSES LLM judgment with deterministic tool/API signals to produce `final_normalized_text`,
`detected_country`, and `confidence_score`. For safety- or correctness-critical decisions,
deterministic checks take precedence over the LLM. Divergence between LLM and deterministic signals
MUST lower confidence and MAY trigger `needs_review`. Rationale: production reliability comes from
constraining and cross-checking the LLM with deterministic structure, not from trusting it blindly.

### XI. Observability & Eval-Driven Verification

The system MUST be observable and verified by evidence. Every node emits a structured trace span;
token usage, latency, and estimated cost are recorded per turn and per conversation, so the system is
debuggable from logs/traces alone. Every capability ships with evaluation cases, and a single command
runs a CI-ready suite producing one report: task success, language fidelity, guardrail
precision/recall, LLM-as-judge quality (temperature 0, documented 1–5 rubric), latency p50/p95, and
estimated cost per conversation — with configurable thresholds and non-zero exit on failure. Changes
MUST NOT regress the configured thresholds. Rationale: you cannot operate, cost-control, or improve
what you cannot see and measure; quality is claimed with evidence, not assertion.

---

## Technology & Architecture Constraints

- **Language & typing**: Python 3.11+; all cross-boundary data is typed (Pydantic models). No
  untyped dicts crossing node boundaries.
- **LLM access**: a single provider-abstracted client (Future-Proofing, Modularity) with timeout,
  retry, and cost accounting built in. No direct SDK calls scattered through node logic.
- **Determinism where it matters**: the LLM-as-judge and all deterministic reasoning paths run at
  temperature 0. Randomness in behavior MUST be justified.
- **Secrets**: environment variables only. No secrets/keys/tokens committed; `.env` is git-ignored
  and `.env.example` documents required variables.
- **Dependencies**: minimal and pinned; a new dependency MUST be justified against building it
  in-repo. Prefer deterministic libraries for validation/normalization tools.
- **Configuration as data**: models, thresholds, supported languages, and tool registration are
  config-driven, not hardcoded (Future-Proofing).
- **Scope honesty**: features cut for time — and foundational principles implemented as design
  posture rather than fully built (Scalability, Continuous Learning) — are documented in the README
  as explicit, justified decisions rather than silently omitted or over-claimed.

## Development Workflow & Quality Gates

- **SDD flow**: work proceeds `/speckit-specify → /speckit-plan → /speckit-tasks → /speckit-implement`
  per feature, optionally gated by `/speckit-clarify` and `/speckit-analyze`. Each feature is a
  vertical slice — spec → design → tasks → implement → verify — developed on its own branch with the
  spec committed before that feature's code.
- **Constitution Check**: every `plan.md` MUST include a Constitution Check confirming the design
  honors these principles; unjustified violations block the plan.
- **Verification before done**: a task is complete only when its acceptance criteria and relevant
  eval cases pass. "It runs" is not "it is verified."
- **AI copilot transparency**: where AI-copilot suggestions were accepted or rejected, the reasoning
  is noted (README and/or commit messages), per the assessment's expectations.
- **Commits**: reference the feature/spec; keep specs-before-code ordering intact in history.

## Governance

This constitution supersedes other practices in this repository. Amendments MUST be committed with a
version bump and dated Sync Impact Report:

- **MAJOR**: backward-incompatible removal or redefinition of a principle.
- **MINOR**: a new principle or section, or materially expanded guidance.
- **PATCH**: clarifications, wording, and non-semantic refinements.

All plans and reviews MUST verify compliance with the current version. Complexity that appears to
violate a principle MUST be justified in the relevant `plan.md` or removed. The constitution is
reviewed at the start of every feature's planning phase.

**Version**: 1.0.0 | **Ratified**: 2026-07-24 | **Last Amended**: 2026-07-24
