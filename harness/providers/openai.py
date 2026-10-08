"""Streaming OpenAI chat-completions adapter."""

from __future__ import annotations

import json

from harness.messages import Completion, Message, ToolCall
from harness.providers.translate import openai_messages, openai_tools


class OpenAIProvider:
    def __init__(self, client=None):
        self._client = client

    def stream(self, messages, tools, model: str, on_text) -> Completion:
        client = self._client if self._client is not None else _sdk_client()
        kwargs = {
            "model": model,
            "messages": openai_messages(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = openai_tools(tools)
        text: list[str] = []
        tool_acc: dict[int, dict[str, str]] = {}
        input_tokens = None
        for chunk in client.chat.completions.create(**kwargs):
            usage = getattr(chunk, "usage", None)
            if usage is not None and getattr(usage, "prompt_tokens", None) is not None:
                input_tokens = usage.prompt_tokens
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                on_text(content)
                text.append(content)
            for tool_call in getattr(delta, "tool_calls", None) or []:
                slot = tool_acc.setdefault(tool_call.index, {"id": "", "name": "", "arguments": ""})
                if tool_call.id:
                    slot["id"] = tool_call.id
                function = getattr(tool_call, "function", None)
                if function is None:
                    continue
                if function.name:
                    slot["name"] = function.name
                if function.arguments:
                    slot["arguments"] += function.arguments
        calls = [_tool_call(index, tool_acc[index]) for index in sorted(tool_acc)]
        return Completion(
            Message("assistant", "".join(text), calls or None),
            input_tokens,
        )


def _tool_call(index: int, slot: dict[str, str]) -> ToolCall:
    raw = slot["arguments"] or "{}"
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError:
        arguments = {"_raw": raw}
    if not isinstance(arguments, dict):
        arguments = {"_raw": raw}
    return ToolCall(slot["id"] or f"call_{index}", slot["name"], arguments)


def _sdk_client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The openai package is not installed.") from exc
    return OpenAI()
