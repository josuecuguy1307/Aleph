"""Manual CLI path persistence and validation in an isolated data directory."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli_brain import config
from cli_brain.codex_cli import CodexCliProvider
from cli_brain.base import STATE_CONFIG_INVALID


class CliConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"ALEPH_DATA_DIR": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def fake_binary(self, name, version):
        path = Path(self.temp.name) / name
        path.write_text("#!/bin/sh\necho '" + version + "'\n")
        path.chmod(0o700)
        return str(path)

    def test_manual_choice_persists_and_resolves(self):
        binary = self.fake_binary("codex", "codex-cli 1.0")
        self.assertEqual(config.save("codex_cli", "manual", binary)["path"], binary)
        self.assertEqual(config.get("codex_cli")["mode"], "manual")
        self.assertEqual(CodexCliProvider().binary(), binary)
        self.assertEqual(config.config_path().stat().st_mode & 0o777, 0o600)
        config.save("codex_cli", "auto")
        self.assertEqual(config.get("codex_cli"), {"mode": "auto", "path": ""})

    def test_wrong_binary_rejected(self):
        wrong = self.fake_binary("codex", "Claude Code 1.0")
        with self.assertRaises(config.ConfigError):
            config.save("codex_cli", "manual", wrong)

    def test_disappearing_manual_binary_is_config_invalid(self):
        binary = self.fake_binary("codex", "codex-cli 1.0")
        config.save("codex_cli", "manual", binary)
        Path(binary).unlink()
        status = CodexCliProvider().detect()
        self.assertEqual(status.state, STATE_CONFIG_INVALID)
        self.assertEqual(status.to_dict(public=True)["configuration_state"], "invalid")

    def test_manual_choice_works_with_finder_like_minimal_path(self):
        binary = self.fake_binary("codex", "codex-cli 1.0")
        config.save("codex_cli", "manual", binary)
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            self.assertEqual(CodexCliProvider().binary(), binary)


if __name__ == "__main__":
    unittest.main()
