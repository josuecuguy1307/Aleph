"""Focused provider-state checks; no CLI or user profile is touched."""
import subprocess
import unittest
from unittest.mock import patch

from cli_brain.base import (BrainStatus, STATE_AUTH_UNKNOWN, STATE_NO_AUTH,
                            STATE_READY)
from cli_brain.claude_cli import ClaudeCliProvider
from cli_brain.codex_cli import CodexCliProvider
from cli_brain.grok_cli import GrokCliProvider


class ProviderStateTests(unittest.TestCase):
    def test_unrecognized_auth_is_unknown(self):
        self.assertEqual(CodexCliProvider().parse_detect(2, "", "network error")[0],
                         STATE_AUTH_UNKNOWN)
        self.assertEqual(ClaudeCliProvider().parse_detect(0, '{"newFormat":true}', "")[0],
                         STATE_AUTH_UNKNOWN)
        self.assertEqual(GrokCliProvider().parse_detect(1, "", "network error")[0],
                         STATE_AUTH_UNKNOWN)

    def test_explicit_logout_is_distinct(self):
        self.assertEqual(CodexCliProvider().parse_detect(1, "Not logged in", "")[0],
                         STATE_NO_AUTH)
        self.assertEqual(ClaudeCliProvider().parse_detect(0, '{"loggedIn":false}', "")[0],
                         STATE_NO_AUTH)
        self.assertEqual(GrokCliProvider().parse_detect(1, "You are not authenticated", "")[0],
                         STATE_NO_AUTH)

    def test_auth_timeout_is_unknown(self):
        provider = CodexCliProvider()
        with patch.object(provider, "_resolve_binary", return_value=("/tmp/codex", "manual", "")), \
             patch("cli_brain.base._run_managed", side_effect=subprocess.TimeoutExpired("codex", 1)):
            status = provider.detect()
        self.assertEqual(status.state, STATE_AUTH_UNKNOWN)
        self.assertEqual(status.to_dict(public=True)["auth_state"], "unknown")

    def test_structured_status_does_not_leak_binary_publicly(self):
        status = BrainStatus("codex_cli", STATE_READY, binary="/private/codex")
        public = status.to_dict(public=True)
        self.assertTrue(public["binary_found"])
        self.assertEqual(public["auth_state"], "authenticated")
        self.assertNotIn("binary", public)
        self.assertNotIn("/private/codex", str(public))


if __name__ == "__main__":
    unittest.main()
