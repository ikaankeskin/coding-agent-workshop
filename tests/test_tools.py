"""File tools, search, notes, and shell."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from harness.tools import build_registry
from harness.tools.common import Tool, ToolContext, ToolResult


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.ctx = ToolContext(self.workspace, {})
        self.registry = build_registry()

    def tearDown(self):
        self.tmp.cleanup()

    def test_edit_requires_a_prior_read(self):
        path = self.workspace / "note.txt"
        path.write_text("hello\n", encoding="utf-8")
        result = self.registry.call(
            "edit_file",
            {"path": "note.txt", "old_string": "hello", "new_string": "world"},
            self.ctx,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "not_read")
        self.assertEqual(path.read_text(encoding="utf-8"), "hello\n")

    def test_edit_rejects_a_stale_file(self):
        path = self.workspace / "note.txt"
        path.write_text("hello\n", encoding="utf-8")
        self.registry.call("read_file", {"path": "note.txt"}, self.ctx)
        time.sleep(0.01)
        path.write_text("hello!\n", encoding="utf-8")
        result = self.registry.call(
            "edit_file",
            {"path": "note.txt", "old_string": "hello", "new_string": "world"},
            self.ctx,
        )
        self.assertEqual(result.error_code, "stale")
        self.assertIn("hello!", path.read_text(encoding="utf-8"))

    def test_edit_rejects_a_non_unique_old_string(self):
        path = self.workspace / "note.txt"
        path.write_text("foo\nfoo\n", encoding="utf-8")
        self.registry.call("read_file", {"path": "note.txt"}, self.ctx)
        result = self.registry.call(
            "edit_file",
            {"path": "note.txt", "old_string": "foo", "new_string": "bar"},
            self.ctx,
        )
        self.assertEqual(result.error_code, "ambiguous")
        self.assertEqual(path.read_text(encoding="utf-8"), "foo\nfoo\n")

    def test_edit_replaces_one_match_after_a_read(self):
        path = self.workspace / "note.txt"
        path.write_text("hello\n", encoding="utf-8")
        self.registry.call("read_file", {"path": "note.txt"}, self.ctx)
        result = self.registry.call(
            "edit_file",
            {"path": "note.txt", "old_string": "hello", "new_string": "world"},
            self.ctx,
        )
        self.assertTrue(result.ok)
        self.assertEqual(path.read_text(encoding="utf-8"), "world\n")

    def test_write_of_an_existing_file_requires_a_read(self):
        path = self.workspace / "note.txt"
        path.write_text("keep\n", encoding="utf-8")
        result = self.registry.call("write_file", {"path": "note.txt", "content": "new\n"}, self.ctx)
        self.assertEqual(result.error_code, "not_read")
        self.assertEqual(path.read_text(encoding="utf-8"), "keep\n")

    def test_read_pages_long_files(self):
        path = self.workspace / "long.txt"
        path.write_text("\n".join(f"line-{index}" for index in range(1, 11)) + "\n", encoding="utf-8")
        result = self.registry.call("read_file", {"path": "long.txt", "offset": 3, "limit": 2}, self.ctx)
        self.assertTrue(result.ok)
        self.assertIn("3|line-3", result.output)
        self.assertIn("4|line-4", result.output)
        self.assertNotIn("5|line-5", result.output)

    def test_paths_outside_the_workspace_are_rejected(self):
        result = self.registry.call("read_file", {"path": "../outside.txt"}, self.ctx)
        self.assertEqual(result.error_code, "outside_workspace")

    def test_grep_and_glob_format_matches(self):
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "app.py").write_text("token = 1\n", encoding="utf-8")
        grep = self.registry.call("grep", {"pattern": "token"}, self.ctx)
        listed = self.registry.call("glob", {"pattern": "**/*.py"}, self.ctx)
        self.assertIn("src/app.py:1:token = 1", grep.output)
        self.assertIn("src/app.py", listed.output)

    def test_notes_are_written_under_agent_memory(self):
        result = self.registry.call("write_note", {"name": "plan", "content": "next step"}, self.ctx)
        self.assertTrue(result.ok)
        self.assertEqual((self.workspace / ".agent" / "memory" / "plan.md").read_text(encoding="utf-8"), "next step")

    def test_bash_reports_the_exit_code_and_times_out(self):
        ok = self.registry.call("bash", {"command": "echo hi"}, self.ctx)
        self.assertTrue(ok.ok)
        self.assertIn("hi", ok.output)
        timed = self.registry.call("bash", {"command": "sleep 5", "timeout": 1}, self.ctx)
        self.assertEqual(timed.error_code, "timeout")

    def test_registry_accepts_an_extra_tool(self):
        def handler(_arguments, _ctx):
            return ToolResult(True, "extra")

        registry = build_registry(
            [Tool("extra", "extra", {}, [], handler)]
        )
        result = registry.call("extra", {}, self.ctx)
        self.assertEqual(result.output, "extra")

    def test_dispatcher_returns_unknown_tool_errors(self):
        result = self.registry.call("missing", {}, self.ctx)
        self.assertEqual(result.error_code, "unknown_tool")


if __name__ == "__main__":
    unittest.main()
