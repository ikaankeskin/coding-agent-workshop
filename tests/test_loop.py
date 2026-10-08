"""Loop, permissions, compression, hooks, and sub-agents."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from harness.context import COMPRESSED_PREFIX, summary_instructions
from harness.loop import CONTINUATION, run
from tests.support import answering, make_settings, tool_call, wire


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, responses, settings=None, handler=None, error=None):
        settings = settings or make_settings()
        provider, client, providers, router, _decisions = wire(settings, responses, handler, error)
        result = run(
            "fix the failing tests",
            workspace=self.workspace,
            settings=settings,
            providers=providers,
            decisions=router.decisions,
            router=router,
        )
        return result, provider, client

    def test_allow_and_deny_do_not_call_openjev(self):
        from harness.config import Permissions

        allowed = make_settings(max_turns=1, permissions=Permissions(allow_patterns=["echo"]))
        marker = self.workspace / "ran.txt"
        provider, client, providers, router, _decisions = wire(allowed, [
            {"tool_calls": [tool_call("bash", {"command": "echo hi > ran.txt"})]},
        ], error="should not be called")
        run("task", workspace=self.workspace, settings=allowed, providers=providers, decisions=router.decisions, router=router)
        self.assertTrue(marker.exists())
        self.assertEqual(client.calls, [])

        denied = make_settings(max_turns=1, permissions=Permissions(deny_patterns=["echo"]))
        skipped = self.workspace / "skipped.txt"
        provider, client, providers, router, _decisions = wire(denied, [
            {"tool_calls": [tool_call("bash", {"command": f"echo hi > {skipped}"})]},
        ], error="should not be called")
        run("task", workspace=self.workspace, settings=denied, providers=providers, decisions=router.decisions, router=router)
        self.assertFalse(skipped.exists())
        self.assertEqual(client.calls, [])

    def test_permission_failure_denies_without_running_the_tool(self):
        from harness.config import Permissions

        settings = make_settings(max_turns=1, permissions=Permissions())
        marker = self.workspace / "blocked.txt"
        _result, _provider, client = self._run(
            [{"tool_calls": [tool_call("bash", {"command": f"echo hi > {marker}"})]}],
            settings=settings,
            error="down",
        )
        self.assertFalse(marker.exists())
        self.assertTrue(client.calls)
        self.assertIn("permit", client.calls[0]["questions"])

    def test_one_termination_nudge_then_stop(self):
        result, provider, client = self._run(
            [{"content": "I think I am done"}, {"content": "still going"}],
            handler=answering(noul=0.1),
        )
        self.assertEqual(result.reason, "completed")
        self.assertEqual(len(provider.calls), 2)
        self.assertIn(CONTINUATION, provider.calls[1]["messages"][-1].content)
        done_calls = [call for call in client.calls if "done" in call["questions"]]
        self.assertEqual(len(done_calls), 1)

    def test_openjev_outage_accepts_the_model_stop(self):
        result, provider, _client = self._run(
            [{"content": "done"}],
            error="down",
        )
        self.assertEqual(result.reason, "completed")
        self.assertEqual(len(provider.calls), 1)

    def test_compression_replaces_the_transcript_with_a_clear_context(self):
        (self.workspace / "AGENTS.md").write_text("PROJECT_RULES run the unit tests\n", encoding="utf-8")
        (self.workspace / "wide.txt").write_text("UNIQUE_FILE_BODY\n" * 800, encoding="utf-8")
        settings = make_settings(context_limit=800, reply_reserve=0, max_turns=3)
        summary = "\n".join([
            "Task: fix the failing tests",
            "Decisions: keep the parser",
            "Files changed: none",
            "Files read: wide.txt showed UNIQUE was noise",
            "Commands: none",
            "Unresolved: none",
            "Next: edit the parser",
        ])
        result, provider, _client = self._run(
            [
                {"tool_calls": [tool_call("read_file", {"path": "wide.txt"})]},
                {"content": summary},
                {"tool_calls": [tool_call("edit_file", {"path": "wide.txt", "old_string": "UNIQUE_FILE_BODY", "new_string": "x"}, "edit")]},
                {"content": "finished"},
            ],
            settings=settings,
        )
        self.assertEqual(result.reason, "completed")
        self.assertIn("Files changed", provider.calls[1]["messages"][0].content)
        self.assertIn(summary_instructions().splitlines()[0], provider.calls[1]["messages"][0].content)
        agent_call = provider.calls[2]
        self.assertEqual([message.role for message in agent_call["messages"]], ["system", "user"])
        self.assertTrue(agent_call["messages"][1].content.startswith(COMPRESSED_PREFIX.strip()))
        self.assertIn("PROJECT_RULES", agent_call["messages"][0].content)
        self.assertNotIn("UNIQUE_FILE_BODY", agent_call["messages"][1].content)
        edit_result = result.messages[-2]
        self.assertEqual(edit_result.role, "tool")
        self.assertIn("not_read", edit_result.content)

    def test_a_long_summary_is_rewritten_once(self):
        settings = make_settings(context_limit=500, reply_reserve=0, summary_token_cap=40)
        short = "Task: fix tests\nDecisions: none\nFiles changed: none\nFiles read: none\nCommands: none\nUnresolved: none\nNext: stop"
        provider, _client, providers, router, decisions = wire(
            settings,
            [{"content": "x" * 200}, {"content": short}, {"content": "finished"}],
        )
        result = run(
            "OLD_TOOL_DUMP " * 400,
            workspace=self.workspace,
            settings=settings,
            providers=providers,
            decisions=decisions,
            router=router,
        )
        self.assertIn("Rewrite", provider.calls[1]["messages"][0].content)
        self.assertTrue(provider.calls[2]["messages"][1].content.startswith(COMPRESSED_PREFIX.strip()))
        self.assertIn(short, provider.calls[2]["messages"][1].content)
        self.assertNotIn("OLD_TOOL_DUMP", provider.calls[2]["messages"][1].content)
        self.assertEqual(result.reason, "completed")

    def test_post_tool_hook_output_is_appended(self):
        from harness.config import HookSpec, Permissions

        (self.workspace / "note.txt").write_text("hello\n", encoding="utf-8")
        settings = make_settings(
            permissions=Permissions(allow_tools=["edit_file"]),
            post_tool=[HookSpec(command="printf HOOK_OUTPUT", tool="edit_file")],
        )
        result, _provider, _client = self._run(
            [
                {"tool_calls": [tool_call("read_file", {"path": "note.txt"})]},
                {"tool_calls": [tool_call("edit_file", {"path": "note.txt", "old_string": "hello", "new_string": "world"}, "edit")]},
                {"content": "edited"},
            ],
            settings=settings,
        )
        tool_messages = [message.content for message in result.messages if message.role == "tool"]
        self.assertTrue(any("HOOK_OUTPUT" in content for content in tool_messages))
        self.assertEqual((self.workspace / "note.txt").read_text(encoding="utf-8"), "world\n")

    def test_sub_agent_returns_only_its_summary(self):
        from harness.config import Permissions

        settings = make_settings(max_turns=4, subagent_max_turns=2, permissions=Permissions(allow_tools=["bash"]))
        result, provider, client = self._run(
            [
                {"tool_calls": [tool_call("spawn_agent", {"task": "find call sites"})]},
                {"tool_calls": [tool_call("bash", {"command": "echo SECRET_TRANSCRIPT"})]},
                {"content": "investigated the module"},
                {"content": "parent finished"},
            ],
            settings=settings,
            handler=answering(spawn="spawn"),
        )
        spawn_results = [message.content for message in result.messages if message.name == "spawn_agent"]
        self.assertEqual(spawn_results, ["investigated the module"])
        self.assertNotIn("SECRET_TRANSCRIPT", spawn_results[0])
        route = next(call for call in client.calls if "route" in call["questions"])
        self.assertIn("user request: fix the failing tests", route["state"])
        self.assertIn("investigation: find call sites", route["state"])
        self.assertEqual(result.reason, "completed")
        self.assertLessEqual(len(provider.calls), 4)

    def test_inline_spawn_does_not_start_a_child_loop(self):
        result, provider, _client = self._run(
            [
                {"tool_calls": [tool_call("spawn_agent", {"task": "look around"})]},
                {"content": "did it inline"},
            ],
            handler=answering(spawn="inline"),
        )
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("main conversation", result.messages[3].content)
        self.assertEqual(result.reason, "completed")

    def test_uncertain_spawn_explains_the_refusal(self):
        result, provider, _client = self._run(
            [
                {"tool_calls": [tool_call("spawn_agent", {"task": "look around"})]},
                {"content": "did it inline"},
            ],
            handler=answering(spawn="spawn", confidence=0.1),
        )
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("not confident enough", result.messages[3].content)


class RewriteLimitTests(unittest.TestCase):
    def test_user_task_over_the_limit_is_compressed_before_the_agent_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            settings = make_settings(context_limit=500, reply_reserve=0, summary_token_cap=40)
            short = "Task: big\nDecisions: none\nFiles changed: none\nFiles read: none\nCommands: none\nUnresolved: none\nNext: stop"
            provider, _client, providers, router, decisions = wire(
                settings,
                [{"content": "y" * 400}, {"content": short}, {"content": "finished"}],
            )
            result = run(
                "OLD_TOOL_DUMP " * 400,
                workspace=workspace,
                settings=settings,
                providers=providers,
                decisions=decisions,
                router=router,
            )
        self.assertNotIn("OLD_TOOL_DUMP", provider.calls[2]["messages"][1].content)
        self.assertTrue(provider.calls[2]["messages"][1].content.startswith(COMPRESSED_PREFIX.strip()))
        self.assertEqual(result.text, "finished")


if __name__ == "__main__":
    unittest.main()
