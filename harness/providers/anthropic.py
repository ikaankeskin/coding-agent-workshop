"""Streaming Anthropic messages adapter."""

from __future__ import annotations

from harness.messages import Completion, Message, ToolCall
from harness.providers.translate import anthropic_payload, anthropic_tools


class AnthropicProvider:
    def __init__(self, client=None, max_tokens: int = 8192):
        self._client = client
        self.max_tokens = max_tokens

    def stream(self, messages, tools, model: str, on_text) -> Completion:
        client = self._client if self._client is not None else _sdk_client()
        system, payload = anthropic_payload(messages)
        kwargs = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": payload or [{"role": "user", "content": ""}],
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = anthropic_tools(tools)
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                on_text(text)
            final = stream.get_final_message()
        content: list[str] = []
        calls: list[ToolCall] = []
        for block in final.content:
            if block.type == "text":
                content.append(block.text)
            elif block.type == "tool_use":
                arguments = block.input if isinstance(block.input, dict) else {}
                calls.append(ToolCall(block.id, block.name, arguments))
        input_tokens = getattr(getattr(final, "usage", None), "input_tokens", None)
        return Completion(Message("assistant", "".join(content), calls or None), input_tokens)


def _sdk_client():
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("The anthropic package is not installed.") from exc
    return Anthropic()
