"""Shell commands, with a timeout and truncated output."""

from __future__ import annotations

import subprocess

from harness.messages import ToolResult
from harness.tools.common import Tool, ToolContext

DEFAULT_TIMEOUT = 30
MAX_OUTPUT = 20_000


def bash(arguments: dict, ctx: ToolContext) -> ToolResult:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolResult(False, "command is required", "invalid_arguments")
    timeout = arguments.get("timeout", DEFAULT_TIMEOUT)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        return ToolResult(False, "timeout must be an integer", "invalid_arguments")
    if timeout < 1:
        return ToolResult(False, "timeout must be positive", "invalid_arguments")
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=ctx.workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(False, "command timed out", "timeout")
    output = _clip(completed.stdout or "")
    error_output = _clip(completed.stderr or "")
    text = f"exit code {completed.returncode}"
    if output:
        text = f"{text}\n{output}"
    if error_output:
        text = f"{text}\n{error_output}"
    if completed.returncode == 0:
        return ToolResult(True, text)
    return ToolResult(False, text, "command_failed")


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + "\n...[truncated]"


def bash_tool() -> Tool:
    return Tool(
        "bash",
        "Run a shell command in the workspace. Output is truncated.",
        {"command": {"type": "string"}, "timeout": {"type": "integer"}},
        ["command"],
        bash,
    )
