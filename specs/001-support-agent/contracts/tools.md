# Contract: Tools, Guardrails & LLM Client

Interfaces that let capabilities be added without touching the orchestrator (Modularity). All are
Python `Protocol`s / ABCs; registrations are config-driven.

## LLMClient (provider-agnostic)

```text
class LLMClient(Protocol):
    def complete(
        self, *, model: str, system: str, messages: list[Msg],
        schema: type[BaseModel] | None = None,   # structured output → parsed instance
        tools: list[ToolSpec] | None = None,
        effort: Literal["low","medium","high"] = "medium",
        temperature: float | None = None,        # forwarded ONLY to models that accept it
        timeout_s: float | None = None,
    ) -> LLMResult: ...

class LLMResult:
    parsed: BaseModel | None      # when schema given
    text: str | None
    tool_calls: list[ToolCall]
    usage: Usage                  # input/output/cache tokens
    cost_usd: float               # from config pricing table
    stop_reason: str              # includes "refusal"
    degraded: bool                # True if a fallback/repair path was taken
```

Guarantees (Resilience, Principle III): explicit timeout; bounded retries with backoff (429/5xx/
connection); one bounded repair re-ask on malformed/parse failure, then fail closed; `refusal`
handled; on exhaustion returns `degraded=True` so the caller sets `needs_review`. Never raises to the
node for expected API failures. The Anthropic implementation lives only in `llm/anthropic_adapter.py`.

## Tool + ToolRegistry (signal-fusion & actions)

```text
class Tool(Protocol):
    name: str
    input_schema: type[BaseModel]     # strict; validated before execution (Security)
    def run(self, args: BaseModel) -> ToolResult: ...

class ToolRegistry:
    def register(self, tool: Tool) -> None
    def get(self, name: str) -> Tool
    def specs(self) -> list[ToolSpec]   # for the LLM
```

Built-ins in `001`:
- `normalize_contact` — `phonenumbers` → E.164 + region; returns a `NormalizationSignal` (deterministic
  side of fusion, Principle X).
- `mock_backend` — deterministic order/account operations (`lookup_order`, `reschedule_delivery`,
  `cancel_order`); state-changing ops require HITL confirmation upstream (FR-012/013).

## Guardrail + GuardrailRegistry

```text
class Guardrail(Protocol):
    id: str
    stage: Literal["input","output"]
    def check(self, ctx: GuardrailContext) -> GuardrailDecision | None   # None = pass
```

Baseline set in `001` (full taxonomy in `003`): input — prompt-injection, PII, abuse, out-of-scope;
output — PII-leakage, ungrounded-claim, policy. Registry runs all guardrails for a stage; any
non-`allow` decision is recorded in the contract and can force a safe reply (Principle VIII).

## SessionStore & LanguageDetector (swap points)

```text
class SessionStore(Protocol):
    def load(self, session_id: str) -> Session
    def save(self, session: Session) -> None      # in-memory now; Redis/DB later (Scalability)

class LanguageDetector(Protocol):
    def detect(self, text: str) -> LanguageResult # lingua baseline; deepened in 002
```
