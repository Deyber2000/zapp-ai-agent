"""Tool registry (Constitution II: Modularity).

Tools (signal-fusion normalization, mock backend actions) plug in here without touching the
orchestrator. `001` ships the registry and its seams; concrete tools arrive with US2/US3.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ToolSpec(BaseModel):
    """A tool's advertised interface (passed to the LLM)."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: type[BaseModel]

    def run(self, args: BaseModel) -> ToolResult: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=tool.name,
                description=getattr(tool, "description", ""),
                input_schema=tool.input_schema.model_json_schema(),
            )
            for tool in self._tools.values()
        ]
