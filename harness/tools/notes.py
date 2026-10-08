"""Notes and plans stored on disk, outside the context window."""

from __future__ import annotations

import re

from harness.messages import ToolResult
from harness.tools.common import Tool, ToolContext, display

NAME = re.compile(r"[A-Za-z0-9._-]{1,80}")


def write_note(arguments: dict, ctx: ToolContext) -> ToolResult:
    name = arguments.get("name")
    content = arguments.get("content")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        return ToolResult(False, "name must be a short file-safe token", "invalid_arguments")
    if not isinstance(content, str):
        return ToolResult(False, "content is required", "invalid_arguments")
    directory = ctx.workspace / ".agent" / "memory"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return ToolResult(True, f"Wrote {display(ctx.workspace, path)}")


def note_tool() -> Tool:
    return Tool(
        "write_note",
        "Write a note or plan under .agent/memory so it survives beyond this session.",
        {"name": {"type": "string"}, "content": {"type": "string"}},
        ["name", "content"],
        write_note,
    )
