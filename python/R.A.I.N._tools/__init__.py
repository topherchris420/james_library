"""R.A.I.N. Tools — LangGraph-based tool calling for consistent LLM agent execution."""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T", bound=Callable[..., Any])

def tool(name: str | None = None, description: str | None = None) -> Callable[[T], T]:
    """Decorator to mark a function as a R.A.I.N. tool."""

    def decorator(func: T) -> T:
        func.name = name or func.__name__
        func.description = description or (func.__doc__ or "")
        if not hasattr(func, "invoke"):
            func.invoke = func
        return func

    return decorator

class ShellTool:
    """Shell execution tool."""

    name = "shell"
    description = "Execute a shell command and return its output."

    async def ainvoke(self, input: dict[str, Any]) -> str:
        if asyncio.get_event_loop().is_running():
            raise RuntimeError(
                "ShellTool.ainvoke cannot be called from an active event loop. "
                "Use agent.ainvoke() instead."
            )
        if os.getenv("RAIN_TOOLS_ENABLE_SHELL") != "1":
            return "Error: shell tool is disabled by default. Set RAIN_TOOLS_ENABLE_SHELL=1 to enable."

        command = input.get("command", "")
        if not isinstance(command, str) or not command.strip():
            return "Error: command must be a non-empty string"

        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"Error: invalid command: {exc}"

        result = subprocess.run(argv, shell=False, capture_output=True, text=True)
        return result.stdout or result.stderr

def _workspace_root() -> Path:
    return Path(os.getenv("RAIN_TOOLS_WORKSPACE", os.getcwd())).resolve()

def _resolve_workspace_path(raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("path must be a non-empty string")

    base = _workspace_root()
    candidate = Path(raw_path)
    candidate = candidate if candidate.is_absolute() else (base / candidate)
    resolved = candidate.resolve()

    resolved.relative_to(base)
    return resolved

class FileReadTool:
    """File read tool."""

    name = "file_read"
    description = "Read the contents of a file."

    async def ainvoke(self, input: dict[str, Any]) -> str:
        try:
            path = _resolve_workspace_path(input.get("path", ""))
        except ValueError as exc:
            return f"Error: {exc}"
        if not path.exists():
            return f"Error: file not found: {path}"
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return f"Error reading file: {e}"

class FileWriteTool:
    """File write tool."""

    name = "file_write"
    description = "Write content to a file."

    async def ainvoke(self, input: dict[str, Any]) -> str:
        try:
            path = _resolve_workspace_path(input.get("path", ""))
        except ValueError as exc:
            return f"Error: {exc}"
        content = input.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

class Agent:
    """Simple agent wrapper."""

    def __init__(self, tools: list[Any], model: str, api_key: str):
        self.tools = tools
        self.model = model
        self.api_key = api_key

    async def ainvoke(self, input: dict[str, Any]) -> str:
        if asyncio.get_event_loop().is_running():
            raise RuntimeError(
                "Agent.ainvoke cannot be called from an active event loop. "
                "Use agent.ainvoke() from a non-async context."
            )
        # Stub implementation — real LangGraph agent in full package
        return f"Agent(model={self.model}, tools={len(self.tools)})"

def create_agent(tools: list[Any], model: str, api_key: str) -> Agent:
    """Create a R.A.I.N. agent with the given tools."""
    return Agent(tools=tools, model=model, api_key=api_key)

# Tool singletons
shell = ShellTool()
file_read = FileReadTool()
file_write = FileWriteTool()

__all__ = [
    "tool",
    "create_agent",
    "Agent",
    "shell",
    "file_read",
    "file_write",
]
