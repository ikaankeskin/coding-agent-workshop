"""Tools the model can ask the harness to run."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from harness.messages import ToolResult


@dataclass
class ToolContext:
    workspace: Path
    reads: dict[str, tuple[int, int]]
    depth: int = 0
    user_task: str = ""
    decisions: object | None = None
    spawn: Callable[[str], str] | None = None


@dataclass
class Tool:
    name: str
    description: str
    properties: dict
    required: list[str]
    handler: Callable[[dict, ToolContext], ToolResult]

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.properties,
                "required": self.required,
            },
        }

    def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        return self.handler(arguments, ctx)


class Registry:
    def __init__(self, tools: list[Tool]):
        self.tools = {tool.name: tool for tool in tools}

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def without(self, name: str) -> Registry:
        return Registry([tool for tool in self.tools.values() if tool.name != name])

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self.tools.values()]

    def call(self, name: str, arguments, ctx: ToolContext) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(False, f"Unknown tool {name}.", "unknown_tool")
        parsed, error = _arguments(arguments)
        if error is not None:
            return error
        try:
            return tool.run(parsed, ctx)
        except Exception as exc:
            return ToolResult(False, f"{type(exc).__name__}: {exc}", "tool_error")


def _arguments(arguments) -> tuple[dict, ToolResult | None]:
    if arguments is None:
        return {}, None
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return {}, ToolResult(False, "Tool arguments are not valid JSON.", "invalid_arguments")
    if not isinstance(arguments, dict):
        return {}, ToolResult(False, "Tool arguments must be an object.", "invalid_arguments")
    return arguments, None


def resolve_in_workspace(workspace: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = workspace / path
    resolved = path.resolve()
    root = workspace.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{raw} is outside the workspace")
    return resolved


def resolve_target(workspace: Path, raw: str) -> tuple[Path | None, ToolResult | None]:
    if not isinstance(raw, str) or not raw:
        return None, ToolResult(False, "path is required", "invalid_arguments")
    try:
        return resolve_in_workspace(workspace, raw), None
    except ValueError as exc:
        return None, ToolResult(False, str(exc), "outside_workspace")


def display(workspace: Path, path: Path) -> str:
    return str(path.resolve().relative_to(workspace.resolve()))


def snapshot(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size
