"""Translate normalized messages into each vendor's wire format."""

from __future__ import annotations

import json

from harness.messages import Message


def openai_messages(messages: list[Message]) -> list[dict]:
    converted: list[dict] = []
    for message in messages:
        if message.role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content or "(no output)",
                }
            )
            continue
        payload: dict = {"role": message.role, "content": message.content or ""}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        converted.append(payload)
    return converted


def openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in tools
    ]


def anthropic_payload(messages: list[Message]) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    converted: list[dict] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        if message.role == "user":
            converted.append({"role": "user", "content": message.content or ""})
            continue
        if message.role == "assistant":
            blocks: list[dict] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            converted.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            continue
        if message.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content or "(no output)",
            }
            if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
    return "\n\n".join(system_parts), converted


def anthropic_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["parameters"],
        }
        for tool in tools
    ]
