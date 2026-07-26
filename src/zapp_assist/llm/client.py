"""Provider-agnostic LLM interface (Constitution II/V).

Nodes depend only on this protocol; the sole Anthropic-specific implementation lives in
`anthropic_adapter.py`. Swapping providers is an adapter change, not a rewrite.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

Effort = Literal["low", "medium", "high"]


class Usage(BaseModel):
    """Token accounting for one LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


class ToolCall(BaseModel):
    id: str = ""
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Msg(TypedDict):
    role: str
    content: str


class LLMResult(BaseModel):
    """The uniform result of an LLM call, whatever the provider.

    `degraded=True` signals that a fallback/repair path was taken (timeout, malformed output,
    refusal, exhausted retries) so the caller can set `needs_review`. Expected API failures are
    never raised to node callers.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    parsed: Any = None  # a BaseModel instance when `schema` was requested
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    stop_reason: str = "end_turn"
    degraded: bool = False


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Msg],
        schema: type[BaseModel] | None = None,
        tools: list[Any] | None = None,
        effort: Effort = "medium",
        temperature: float | None = None,
        timeout_s: float | None = None,
    ) -> LLMResult: ...
