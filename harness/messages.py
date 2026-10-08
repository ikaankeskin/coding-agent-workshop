"""Normalized conversation messages shared by every provider."""

from __future__ import annotations

from dataclasses import dataclass
import json


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class Completion:
    message: Message
    input_tokens: int | None = None


def estimate_text(text: str) -> int:
    if not text:
        return 0
    return (len(text) + 3) // 4


def estimate_messages(messages: list[Message]) -> int:
    total = 0
    for message in messages:
        total += estimate_text(message.content)
        total += estimate_text(message.name or "")
        for call in message.tool_calls or []:
            total += estimate_text(call.name)
            total += estimate_text(json.dumps(call.arguments, ensure_ascii=False))
    return total


def render_transcript(messages: list[Message]) -> str:
    parts: list[str] = []
    for message in messages:
        if message.role == "system":
            continue
        body = message.content or ""
        if message.tool_calls:
            calls = [
                f"{call.name} {json.dumps(call.arguments, ensure_ascii=False)}"
                for call in message.tool_calls
            ]
            body = f"{body}\n" + "\n".join(calls) if body else "\n".join(calls)
        label = message.role
        if message.name:
            label = f"{label} {message.name}"
        parts.append(f"{label}: {body}")
    return "\n\n".join(parts)


@dataclass
class ToolResult:
    ok: bool
    output: str
    error_code: str | None = None


def format_tool_result(result: ToolResult) -> str:
    text = result.output or ""
    if result.ok:
        return text or "(no output)"
    code = result.error_code or "tool_error"
    return f"Error ({code}): {text}" if text else f"Error ({code})"
