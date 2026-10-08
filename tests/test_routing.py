"""Model routing."""

from __future__ import annotations

import unittest

from harness.decisions import Decisions
from harness.errors import NoModelError, OpenJevError
from tests.support import FakeOpenJev, answering, make_settings, model_entry
from harness.routing import Router


class RoutingTests(unittest.TestCase):
    def test_a_model_smaller_than_the_context_is_dropped_before_openjev(self):
        settings = make_settings(
            models=[
                model_entry("small", context_limit=100, notes="too small"),
                model_entry("mid", context_limit=5_000, notes="middle"),
                model_entry("large", context_limit=9_000, notes="large"),
            ],
            default_model="large",
        )
        client = FakeOpenJev(answering(model="mid"))
        router = Router(settings, Decisions(client), has_key=lambda _name: True)
        chosen = router.choose(kind="main", scope="main", task="fix tests", token_estimate=1_000)
        self.assertEqual(chosen.id, "mid")
        criteria = client.calls[0]["questions"]["model"]["criteria"]
        self.assertNotIn("small", criteria)
        self.assertEqual(set(criteria), {"mid", "large"})

    def test_a_single_remaining_model_skips_openjev(self):
        settings = make_settings(
            models=[
                model_entry("small", context_limit=100),
                model_entry("large", context_limit=9_000),
            ],
            default_model="large",
        )
        client = FakeOpenJev(error="should not be called")
        router = Router(settings, Decisions(client), has_key=lambda _name: True)
        chosen = router.choose(kind="main", scope="main", task="fix tests", token_estimate=1_000)
        self.assertEqual(chosen.id, "large")
        self.assertEqual(client.calls, [])

    def test_the_chosen_model_stays_fixed_across_turns(self):
        settings = make_settings(
            models=[
                model_entry("fast", context_limit=8_000, model="fast-api", notes="lookup"),
                model_entry("strong", context_limit=8_000, model="strong-api", notes="coding"),
            ],
            default_model="strong",
        )
        client = FakeOpenJev(answering(model="fast"))
        router = Router(settings, Decisions(client), has_key=lambda _name: True)
        first = router.choose(kind="main", scope="main", task="fix tests", token_estimate=100)
        second = router.choose(kind="main", scope="main", task="fix tests", token_estimate=120)
        self.assertEqual(first.id, "fast")
        self.assertEqual(second.id, "fast")
        self.assertEqual(len(client.calls), 1)

    def test_openjev_failure_falls_back_to_the_default(self):
        settings = make_settings(
            models=[
                model_entry("fast", context_limit=8_000, notes="lookup"),
                model_entry("strong", context_limit=20_000, notes="coding"),
            ],
            default_model="fast",
        )
        client = FakeOpenJev(error="down")
        router = Router(settings, Decisions(client), has_key=lambda _name: True)
        chosen = router.choose(kind="main", scope="main", task="fix tests", token_estimate=100)
        self.assertEqual(chosen.id, "fast")

    def test_fallback_uses_the_largest_window_when_the_default_cannot_fit(self):
        settings = make_settings(
            models=[
                model_entry("fast", context_limit=50, notes="lookup"),
                model_entry("strong", context_limit=20_000, notes="coding"),
            ],
            default_model="fast",
        )
        client = FakeOpenJev(error="down")
        router = Router(settings, Decisions(client), has_key=lambda _name: True)
        chosen = router.choose(kind="main", scope="main", task="fix tests", token_estimate=100)
        self.assertEqual(chosen.id, "strong")

    def test_pinned_model_skips_openjev_for_the_main_conversation(self):
        settings = make_settings(
            models=[
                model_entry("fast", context_limit=8_000),
                model_entry("strong", context_limit=8_000),
            ],
            default_model="strong",
            pinned_model="fast",
        )
        client = FakeOpenJev(error="should not be called")
        router = Router(settings, Decisions(client), has_key=lambda _name: True)
        chosen = router.choose(kind="main", scope="main", task="fix tests", token_estimate=100)
        self.assertEqual(chosen.id, "fast")
        self.assertEqual(client.calls, [])

    def test_missing_keys_leave_no_model(self):
        settings = make_settings()
        router = Router(settings, Decisions(FakeOpenJev()), has_key=lambda _name: False)
        with self.assertRaises(NoModelError):
            router.choose(kind="main", scope="main", task="fix tests", token_estimate=10)


class OpenJevClientTests(unittest.TestCase):
    def test_client_posts_state_and_checks_question_ids(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import json
        import threading

        from harness.decisions import OpenJevClient

        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                seen["body"] = json.loads(self.rfile.read(length))
                seen["auth"] = self.headers.get("Authorization")
                payload = json.dumps({"answers": {"team": {"choice": "billing", "confidence": 0.8}}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            client = OpenJevClient(f"http://127.0.0.1:{port}/v1/systemone", api_key="secret")
            result = client.ask("a ticket", {"team": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "pay"}}})
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(result["answers"]["team"]["choice"], "billing")
        self.assertEqual(seen["body"]["model"], "open-jev")
        self.assertEqual(seen["body"]["state"], "a ticket")
        self.assertEqual(seen["auth"], "Bearer secret")

    def test_mismatched_answers_raise(self):
        from harness.decisions import Decisions
        from tests.support import model_entry

        class Mismatch:
            def ask(self, _state, _questions):
                return {"answers": {"other": {}}}

        decisions = Decisions(Mismatch())
        with self.assertRaises(OpenJevError):
            decisions.choose_model("main", "task", 10, [model_entry("a"), model_entry("b")])


if __name__ == "__main__":
    unittest.main()
