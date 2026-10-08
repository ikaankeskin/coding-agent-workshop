"""Search tools with model-oriented output."""

from __future__ import annotations

import re

from harness.messages import ToolResult
from harness.tools.common import Tool, ToolContext, display, resolve_target

MATCH_LIMIT = 100
GLOB_LIMIT = 200


def grep(arguments: dict, ctx: ToolContext) -> ToolResult:
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return ToolResult(False, "pattern is required", "invalid_arguments")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return ToolResult(False, str(exc), "invalid_pattern")
    base, error = resolve_target(ctx.workspace, arguments.get("path") or ".")
    if error:
        return error
    assert base is not None
    if not base.exists():
        return ToolResult(False, "path does not exist", "not_found")
    files = [base] if base.is_file() else [path for path in base.rglob("*") if path.is_file()]
    matches: list[str] = []
    root = ctx.workspace.resolve()
    for path in files:
        if ".git" in path.parts:
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved != root and root not in resolved.parents:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "\0" in text:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                matches.append(f"{display(ctx.workspace, path)}:{number}:{line}")
                if len(matches) >= MATCH_LIMIT:
                    matches.append("Results truncated.")
                    return ToolResult(True, "\n".join(matches))
    if not matches:
        return ToolResult(True, "No matches.")
    return ToolResult(True, "\n".join(matches))


def glob_paths(arguments: dict, ctx: ToolContext) -> ToolResult:
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return ToolResult(False, "pattern is required", "invalid_arguments")
    if pattern.startswith("/"):
        return ToolResult(False, "pattern must be relative", "invalid_arguments")
    base, error = resolve_target(ctx.workspace, arguments.get("path") or ".")
    if error:
        return error
    assert base is not None
    if not base.is_dir():
        return ToolResult(False, "path is not a directory", "not_found")
    root = ctx.workspace.resolve()
    matches: list[str] = []
    for path in sorted(base.glob(pattern)):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved != root and root not in resolved.parents:
            continue
        matches.append(display(ctx.workspace, path))
        if len(matches) >= GLOB_LIMIT:
            break
    if not matches:
        return ToolResult(True, "No matches.")
    return ToolResult(True, "\n".join(matches))


def search_tools() -> list[Tool]:
    return [
        Tool(
            "grep",
            "Search file contents with a regular expression. Returns path:line:text.",
            {"pattern": {"type": "string"}, "path": {"type": "string"}},
            ["pattern"],
            grep,
        ),
        Tool(
            "glob",
            "List files matching a glob pattern, relative to the workspace.",
            {"pattern": {"type": "string"}, "path": {"type": "string"}},
            ["pattern"],
            glob_paths,
        ),
    ]
