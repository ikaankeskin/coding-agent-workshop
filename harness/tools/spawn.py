"""Sub-agent tool. The spawn callback is supplied by the loop."""

from __future__ import annotations

from harness.errors import AppaError
from harness.messages import ToolResult
from harness.tools.common import Tool, ToolContext


def spawn_agent(arguments: dict, ctx: ToolContext) -> ToolResult:
    if ctx.depth >= 1 or ctx.spawn is None:
        return ToolResult(False, "Sub-agents cannot spawn further agents.", "spawn_denied")
    task = arguments.get("task")
    if not isinstance(task, str) or not task.strip():
        return ToolResult(False, "task is required", "invalid_arguments")
    decisions = ctx.decisions
    if decisions is None:
        return ToolResult(False, "Do this investigation in the main conversation.", "spawn_inline")
    allowed, reason = decisions.spawn_gate(task.strip(), ctx.user_task)
    if not allowed:
        return ToolResult(False, reason, "spawn_inline")
    try:
        summary = ctx.spawn(task.strip())
    except AppaError as exc:
        return ToolResult(False, str(exc), "appa_blocked")
    return ToolResult(True, summary)


def spawn_tool() -> Tool:
    return Tool(
        "spawn_agent",
        "Investigate a substantial question in a fresh context. Only the summary comes back.",
        {"task": {"type": "string"}},
        ["task"],
        spawn_agent,
    )
