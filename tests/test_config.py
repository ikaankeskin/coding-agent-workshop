"""Settings layers."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from harness.config import load_settings
from harness.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def test_later_layers_win_and_permissions_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user = root / "user"
            workspace = root / "work"
            user.mkdir()
            (workspace / ".agent").mkdir(parents=True)
            (user / "settings.json").write_text(
                json.dumps(
                    {
                        "context_limit": 1000,
                        "max_turns": 12,
                        "models": [
                            {
                                "id": "user-model",
                                "provider": "openai",
                                "model": "user-api",
                                "context_limit": 4000,
                                "notes": "user",
                            }
                        ],
                        "default_model": "user-model",
                        "permissions": {"deny_tools": ["bash"]},
                    }
                ),
                encoding="utf-8",
            )
            (workspace / ".agent" / "settings.json").write_text(
                json.dumps({"context_limit": 2000, "permissions": {"allow_patterns": ["pytest"]}}),
                encoding="utf-8",
            )
            (workspace / ".agent" / "settings.local.json").write_text(
                json.dumps({"max_turns": 4}),
                encoding="utf-8",
            )
            settings = load_settings(
                workspace,
                user_dir=user,
                env={"AGENT_CONTEXT_LIMIT": "50", "AGENT_MODEL": "user-model"},
            )
        self.assertEqual(settings.context_limit, 50)
        self.assertEqual(settings.max_turns, 4)
        self.assertEqual(settings.models[0].id, "user-model")
        self.assertEqual(settings.permissions.deny_tools, ["bash"])
        self.assertEqual(settings.permissions.allow_patterns, ["pytest"])
        self.assertEqual(settings.pinned_model, "user-model")

    def test_unknown_default_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with self.assertRaises(ConfigError):
                load_settings(workspace, user_dir=workspace / "missing", env={"AGENT_MODEL": "nope"})


if __name__ == "__main__":
    unittest.main()
