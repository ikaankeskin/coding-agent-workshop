"""Provider adapters. The loop talks to this interface, not to a vendor SDK."""

from __future__ import annotations

from harness.config import ModelEntry
from harness.messages import Completion, Message


class Providers:
    def __init__(self, by_name: dict):
        self.by_name = by_name

    def stream(self, entry: ModelEntry, messages: list[Message], tools: list[dict], on_text) -> Completion:
        provider = self.by_name.get(entry.provider)
        if provider is None:
            raise RuntimeError(f"No adapter registered for provider {entry.provider!r}")
        return provider.stream(messages, tools, entry.model, on_text)
