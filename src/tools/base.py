from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Type


@dataclass
class ToolContext:
    chat_id: int
    user_id: int
    message_id: int | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    on_status_update: Callable[[str], Awaitable[None]] | None = None
    on_request_confirmation: Callable[[str, str], Awaitable[bool]] | None = None
    on_token: Callable[[str], Awaitable[None]] | None = None


@dataclass
class ToolResult:
    success: bool
    output: str
    media_path: str | None = None
    media_type: str | None = None  # "photo" or "document"
    error: str | None = None

    def to_llm_response(self) -> str:
        if self.success:
            if self.media_path:
                return f"{self.output}\n[Media generated and sent: {self.media_path}]"
            return self.output
        return f"ERROR: {self.error or self.output}"


class BaseTool(ABC):
    """Abstract base class for all faf-agent tools."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    @abstractmethod
    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool action with given context and arguments."""
        pass

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert tool schema to OpenAI Tool function format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry managing available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def get_all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    async def execute(
        self, name: str, context: ToolContext, arguments: dict[str, Any]
    ) -> ToolResult:
        tool = self.get(name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{name}' is not registered in faf-agent.",
            )
        try:
            return await tool.execute(context, **arguments)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{name}' execution failed: {str(e)}",
            )
