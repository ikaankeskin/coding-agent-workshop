"""Developer trace events."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from harness.loop import run
from harness.trace import Trace, TracingClient
from tests.support import make_settings, tool_call, wire


class TraceTests(unittest.TestCase):
    def test_a_run_records_route_openjev_tool_and_stop(self):
        events = []
        trace = Trace()
        trace.listeners.append(events.append)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
            settings = make_settings()
            _provider, client, providers, router, decisions = wire(
                settings,
                [
                    {"tool_calls": [tool_call("read_file", {"path": "note.txt"})]},
                    {"content": "read it"},
                ],
            )
            router.trace = trace
            decisions.client = TracingClient(client, trace)
            result = run(
                "read the note",
                workspace=workspace,
                settings=settings,
                providers=providers,
                decisions=decisions,
                router=router,
                trace=trace,
            )
        kinds = [event["kind"] for event in events]
        self.assertEqual(result.reason, "completed")
        self.assertIn("route", kinds)
        self.assertIn("context", kinds)
        self.assertIn("openjev", kinds)
        self.assertIn("tool", kinds)
        self.assertIn("permit", kinds)
        self.assertIn("stop", kinds)
        self.assertIn("only model that fits this context", _message(events, "route"))


def _message(events, kind: str) -> str:
    return next(event["message"] for event in events if event["kind"] == kind)


if __name__ == "__main__":
    unittest.main()
