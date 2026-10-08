"""Provider message translation and stream accumulation."""

from __future__ import annotations

import json
import unittest

from harness.messages import Message, ToolCall
from harness.providers.anthropic import AnthropicProvider
from harness.providers.openai import OpenAIProvider
from harness.providers.translate import anthropic_payload, openai_messages


class TranslateTests(unittest.TestCase):
    def test_openai_tool_messages_keep_ids(self):
        messages = [
            Message("system", "rules"),
            Message("user", "go"),
            Message("assistant", "", [ToolCall("abc", "read_file", {"path": "a"})]),
            Message("tool", "contents", tool_call_id="abc", name="read_file"),
        ]
        converted = openai_messages(messages)
        self.assertEqual(converted[2]["tool_calls"][0]["id"], "abc")
        self.assertEqual(json.loads(converted[2]["tool_calls"][0]["function"]["arguments"]), {"path": "a"})
        self.assertEqual(converted[3]["tool_call_id"], "abc")

    def test_anthropic_groups_tool_results_into_one_user_message(self):
        messages = [
            Message("assistant", "looking", [ToolCall("1", "read_file", {"path": "a"}), ToolCall("2", "grep", {"pattern": "x"})]),
            Message("tool", "one", tool_call_id="1"),
            Message("tool", "two", tool_call_id="2"),
        ]
        _system, payload = anthropic_payload(messages)
        self.assertEqual(payload[1]["role"], "user")
        self.assertEqual(len(payload[1]["content"]), 2)
        self.assertEqual(payload[1]["content"][1]["tool_use_id"], "2")


class StreamTests(unittest.TestCase):
    def test_openai_accumulates_tool_call_deltas(self):
        class Function:
            def __init__(self, name=None, arguments=None):
                self.name = name
                self.arguments = arguments

        class DeltaCall:
            def __init__(self, index, call_id="", name=None, arguments=None):
                self.index = index
                self.id = call_id
                self.function = Function(name, arguments)

        class Chunk:
            def __init__(self, content=None, calls=None, prompt_tokens=None):
                delta = type("Delta", (), {"content": content, "tool_calls": calls})()
                choice = type("Choice", (), {"delta": delta})()
                self.choices = [choice]
                self.usage = type("Usage", (), {"prompt_tokens": prompt_tokens})() if prompt_tokens is not None else None

        chunks = [
            Chunk(content="Hi"),
            Chunk(calls=[DeltaCall(0, "call-1", "read_file", "{\"pa")]),
            Chunk(calls=[DeltaCall(0, arguments="th\": \"a.txt\"}")]),
            Chunk(prompt_tokens=11),
        ]
        chunks[-1].choices = []

        class Completions:
            def create(self, **_kwargs):
                return iter(chunks)

        class Client:
            def __init__(self):
                self.chat = type("Chat", (), {"completions": Completions()})()

        seen = []
        completion = OpenAIProvider(Client()).stream([Message("user", "go")], [], "test", seen.append)
        self.assertEqual(seen, ["Hi"])
        self.assertEqual(completion.message.tool_calls[0].arguments, {"path": "a.txt"})
        self.assertEqual(completion.input_tokens, 11)

    def test_anthropic_streams_text_and_reads_tool_uses_from_the_final_message(self):
        class Block:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class Final:
            content = [
                Block(type="text", text="Hello"),
                Block(type="tool_use", id="t1", name="read_file", input={"path": "a"}),
            ]
            usage = Block(input_tokens=4)

        class Stream:
            text_stream = ["Hello"]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def get_final_message(self):
                return Final()

        class Messages:
            def stream(self, **_kwargs):
                return Stream()

        class Client:
            messages = Messages()

        seen = []
        completion = AnthropicProvider(Client()).stream([Message("user", "go")], [], "test", seen.append)
        self.assertEqual(seen, ["Hello"])
        self.assertEqual(completion.message.content, "Hello")
        self.assertEqual(completion.message.tool_calls[0].name, "read_file")
        self.assertEqual(completion.input_tokens, 4)


if __name__ == "__main__":
    unittest.main()
