# Research: Agent Core

## Decision: structured-output tool selection vs. native function-calling

**Decision**: Build the agent loop on the shared `LLMClient.complete(schema=AgentStep)` structured
output, not on native provider function-calling.

**Rationale**: The `LLMClient` protocol declares `tools` / `tool_calls` / `stop_reason`, and the
Anthropic adapter forwards `tools` — but the **OpenAI adapter (the configured live path) does not wire
`tools` and never parses tool calls**. Structured output works today on all three implementations (mock,
OpenAI, Anthropic) on one code path, keeps the eval deterministic offline, and needs no per-adapter
function-calling work. A single `AgentStep` schema per loop step gives the model a genuine multi-step
ReAct loop (search → observe → answer) while staying provider-agnostic.

**Alternatives considered**:
- *Native function-calling*: most "standard", but requires implementing and testing tool-call parsing in
  each adapter first; larger blast radius, and the OpenAI path would have to be built from scratch.
- *Single-shot planner (one call, no loop)*: simpler, but loses the search→reason→answer chain and reads
  as a smarter router rather than an agent.

## Decision: keep determinism at boundaries, not over understanding

**Decision**: The refactor removes the regex routing guard from the earlier attempt and keeps
deterministic checks only at the irreversible/confirmation boundary and for in-progress multi-turn flows.

**Rationale**: A first attempt bolted regex validators (interrogative/action-verb detection) on top of
the router. That referees the model's *understanding* — brittle and the wrong instinct for an agent. The
correct application of Constitution X is at the boundary: confirm-before-execute is the only path to a
mutation, a bare acknowledgement with nothing pending is a deterministic clarify, and an in-flight
onboarding continues deterministically. Live testing confirmed the model does not always obey a prompt
rule (it re-armed an action from history), which is exactly why the bare-acknowledgement check is in code
rather than in the prompt.

## Decision: normalize the model's tool name

**Decision**: `tool = step.tool.split("(")[0].strip().lower()` before dispatch.

**Rationale**: Live `gpt-4o-mini` sometimes echoed the signature (`search_kb(query)`) from the prompt.
Normalizing the name is parsing the model's choice robustly, not overriding it; without it, a valid
`search_kb` fell through to the "unknown tool" branch and broke retrieval.
