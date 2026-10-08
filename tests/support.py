"""Shared fakes for harness tests."""

from __future__ import annotations

from harness.config import ModelEntry, Permissions, Settings
from harness.decisions import Decisions
from harness.errors import OpenJevError
from harness.messages import Completion, Message, ToolCall
from harness.providers import Providers
from harness.routing import Router


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, messages, tools, model, on_text):
        self.calls.append({"messages": list(messages), "tools": list(tools), "model": model})
        if not self.responses:
            raise AssertionError(f"no scripted response left for model {model}")
        item = self.responses.pop(0)
        if callable(item):
            item = item(messages, tools, model)
        text = item.get("content", "")
        if text:
            on_text(text)
        return Completion(Message("assistant", text, item.get("tool_calls")), item.get("input_tokens"))


class FakeOpenJev:
    def __init__(self, handler=None, error=None):
        self.handler = handler or answering()
        self.error = error
        self.calls = []

    def ask(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        if self.error:
            raise OpenJevError(self.error)
        return self.handler(state, questions)


def answering(noul=0.9, permit="allow", spawn="spawn", model=None, confidence=0.9):
    def handler(_state, questions):
        question_id, question = next(iter(questions.items()))
        if question["type"] == "noul":
            return {"answers": {question_id: {"type": "noul", "noul": noul}}}
        criteria = question.get("criteria") or {}
        if "allow" in criteria:
            choice = permit
        elif "spawn" in criteria:
            choice = spawn
        else:
            choice = model or next(iter(criteria))
        return {
            "answers": {
                question_id: {
                    "type": "choice",
                    "choice": choice,
                    "confidence": confidence,
                    "probabilities": {},
                }
            }
        }

    return handler


def tool_call(name, arguments, call_id="call-1"):
    return ToolCall(call_id, name, arguments)


def model_entry(model_id, context_limit=1_000_000, provider="openai", model="test-model", notes=""):
    return ModelEntry(model_id, provider, model, context_limit, notes)


def make_settings(**overrides) -> Settings:
    settings = Settings(
        models=[model_entry("strong", notes="hard coding")],
        default_model="strong",
        reply_reserve=0,
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def wire(settings, responses, handler=None, error=None):
    client = FakeOpenJev(handler=handler, error=error)
    decisions = Decisions(client, settings.confidence_min)
    provider = ScriptedProvider(responses)
    providers = Providers({"openai": provider, "anthropic": provider})
    router = Router(settings, decisions, has_key=lambda _name: True)
    return provider, client, providers, router, decisions
