"""OpenAPPA gates a sub-agent before it starts and before its summary returns."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from harness.appa import AppaClient, AppaSession, Decision
from harness.config import Permissions
from harness.errors import AppaError
from harness.loop import run
from tests.support import answering, make_settings, tool_call, wire


class RecordingClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.events = []

    def post(self, event):
        self.events.append(event)
        if not self.replies:
            raise AppaError("no scripted OpenAPPA decision")
        item = self.replies.pop(0)
        return Decision(**item)

    def execute_remedy(self, offer_id, actor):
        self.events.append({"mcp": offer_id, "actor": actor})


def _ack():
    return {"decision": "ack"}


class OpenAppaSpawnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, responses, replies, permissions=None):
        settings = make_settings(max_turns=4, subagent_max_turns=2, permissions=permissions or Permissions(allow_tools=["bash"]))
        provider, _client, providers, router, decisions = wire(settings, responses, answering(spawn="spawn"))
        appa_client = RecordingClient(replies)
        result = run(
            "fix the failing tests",
            workspace=self.workspace,
            settings=settings,
            providers=providers,
            decisions=decisions,
            router=router,
            appa=AppaSession(appa_client, root_id="root-1"),
        )
        return result, provider, appa_client

    def test_a_released_spawn_checks_the_child_and_returns_only_the_summary(self):
        result, provider, client = self._run(
            [
                {"tool_calls": [tool_call("spawn_agent", {"task": "find call sites"})]},
                {"tool_calls": [tool_call("bash", {"command": "echo SECRET_TRANSCRIPT"})]},
                {"content": "investigated the module"},
                {"content": "parent finished"},
            ],
            [
                _ack(),
                _ack(),
                {"decision": "allow_call", "spawn_binding": "bind-1"},
                _ack(),
                {"decision": "allow_call"},
                _ack(),
                _ack(),
                _ack(),
            ],
        )
        names = [event.get("event") for event in client.events]
        self.assertEqual(
            names,
            ["session_start", "prompt", "tool_call", "child_start", "tool_call", "tool_result", "child_end", "spawn_result"],
        )
        self.assertEqual(client.events[2]["tool"], "Agent")
        self.assertEqual(client.events[3]["spawn_binding"], "bind-1")
        self.assertEqual(client.events[3]["child_id"], "sub-1")
        self.assertEqual(client.events[4]["tool"], "Bash")
        self.assertEqual(client.events[4]["child_id"], "sub-1")
        spawn = next(message.content for message in result.messages if message.name == "spawn_agent")
        self.assertIn("investigated the module", spawn)
        self.assertNotIn("SECRET_TRANSCRIPT", spawn)
        self.assertGreaterEqual(len(provider.calls), 3)

    def test_a_denied_spawn_never_starts_the_child(self):
        result, provider, client = self._run(
            [
                {"tool_calls": [tool_call("spawn_agent", {"task": "find call sites"})]},
                {"content": "stayed here"},
            ],
            [_ack(), _ack(), {"decision": "deny_call", "feedback": "spawn is not released"}],
        )
        self.assertEqual(len(provider.calls), 2)
        self.assertNotIn("child_start", [event.get("event") for event in client.events])
        spawn = next(message.content for message in result.messages if message.name == "spawn_agent")
        self.assertIn("not released", spawn)
        self.assertNotIn("SECRET", spawn)

    def test_a_blocked_return_does_not_reach_the_parent(self):
        result, _provider, _client = self._run(
            [
                {"tool_calls": [tool_call("spawn_agent", {"task": "find call sites"})]},
                {"content": "SECRET_SUMMARY"},
                {"content": "parent finished"},
            ],
            [
                _ack(),
                _ack(),
                {"decision": "allow_call", "spawn_binding": "bind-1"},
                _ack(),
                {"decision": "block", "reason": "the return is not admissible"},
                _ack(),
            ],
        )
        spawn = next(message.content for message in result.messages if message.name == "spawn_agent")
        self.assertIn("not admissible", spawn)
        self.assertNotIn("SECRET_SUMMARY", spawn)

    def test_a_return_declaration_is_sent_before_the_spawn_is_retried(self):
        _result, provider, client = self._run(
            [
                {"tool_calls": [tool_call("spawn_agent", {"task": "find call sites"})]},
                {"content": "investigated the module"},
                {"content": "parent finished"},
            ],
            [
                _ack(),
                _ack(),
                {"decision": "deny_call", "offers": [{"offer_id": "offer-1", "returns": "as_spoken"}]},
                {"decision": "pass_control"},
                {"decision": "allow_call", "spawn_binding": "bind-2"},
                _ack(),
                _ack(),
                _ack(),
            ],
        )
        tools = [event.get("tool") for event in client.events if event.get("event") == "tool_call"]
        self.assertEqual(tools[0], "Agent")
        self.assertEqual(tools[1], "mcp__appa__execute_remedy_plan")
        self.assertEqual(client.events[4]["mcp"], "offer-1")
        self.assertEqual(len(provider.calls), 3)

    def test_a_silent_runtime_refuses_the_run(self):
        settings = make_settings()
        provider, _client, providers, router, decisions = wire(settings, [{"content": "hi"}], answering())

        class Down:
            def post(self, _event):
                raise AppaError("OpenAPPA did not answer: timed out")

            def execute_remedy(self, _offer, _actor):
                raise AssertionError("no remedy")

        with self.assertRaises(AppaError):
            run(
                "fix the failing tests",
                workspace=self.workspace,
                settings=settings,
                providers=providers,
                decisions=decisions,
                router=router,
                appa=AppaSession(Down(), root_id="root-1"),
            )
        self.assertEqual(provider.calls, [])


class ClientPostTests(unittest.TestCase):
    def test_the_hook_url_is_posted_as_json(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                seen["path"] = self.path
                seen["body"] = self.rfile.read(length)
                body = b'{"protocol":1,"decision":"ack"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            decision = AppaClient(f"http://127.0.0.1:{port}").post({"protocol": 1, "event": "ping"})
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(decision.decision, "ack")
        self.assertEqual(seen["path"], "/hook")
        self.assertIn(b'"event": "ping"', seen["body"])
