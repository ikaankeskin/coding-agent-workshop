"""Structured events for developer logs and the live UI."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable


class Trace:
    def __init__(self, dev: bool = False):
        self.dev = dev
        self.listeners: list[Callable[[dict], None]] = []

    @property
    def active(self) -> bool:
        return self.dev or bool(self.listeners)

    def event(self, kind: str, message: str, *, stage: str | None = None, log: bool = True, **fields) -> None:
        if not self.active:
            return
        record = {
            "kind": kind,
            "stage": stage or kind,
            "message": message,
            "fields": _clip_fields(fields),
        }
        if self.dev and log:
            extra = ""
            if record["fields"]:
                extra = " " + json.dumps(record["fields"], ensure_ascii=False)
            print(f"[{kind}] {message}{extra}", file=sys.stderr, flush=True)
        for listener in list(self.listeners):
            listener(record)


class TracingClient:
    """Records each OpenJev request and response on the trace."""

    def __init__(self, inner, trace: Trace):
        self.inner = inner
        self.trace = trace

    def ask(self, state, questions: dict) -> dict:
        summary = {
            key: {"type": question.get("type"), "instructions": question.get("instructions", "")}
            for key, question in questions.items()
        }
        self.trace.event("openjev", "request", stage="openjev", questions=summary, state=state)
        try:
            result = self.inner.ask(state, questions)
        except Exception as exc:
            self.trace.event("openjev", f"error: {exc}", stage="openjev")
            raise
        answers = result.get("answers") if isinstance(result, dict) else None
        self.trace.event("openjev", "response", stage="openjev", answers=answers)
        return result


def _clip_fields(fields: dict) -> dict:
    clipped = {}
    for key, value in fields.items():
        clipped[key] = _clip(value)
    return clipped


def _clip(value, limit: int = 1200):
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "...[truncated]"
    if isinstance(value, dict):
        return {str(key): _clip(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip(item, limit) for item in value[:30]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)
    if len(text) > limit:
        return text[:limit] + "...[truncated]"
    return text
