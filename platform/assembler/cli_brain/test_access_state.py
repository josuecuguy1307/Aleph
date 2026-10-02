"""Authenticated Claude can still be denied by provider entitlement."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli_brain.base import (BrainStatus, ERR_ACCESS_DENIED, ERR_PROVIDER,
                            STATE_AUTH_EXPIRED, STATE_READY)
from cli_brain.claude_cli import ClaudeCliProvider
from cli_brain import evidence
import time


class AccessStateTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory(prefix="aleph-access-state-test-")
        self.addCleanup(self.data.cleanup)
        override = patch.dict(os.environ, {"ALEPH_DATA_DIR": self.data.name})
        override.start()
        self.addCleanup(override.stop)

    def test_observed_org_denial_is_access_not_auth(self):
        raw = '{"is_error":true,"result":"Your organization has disabled Claude subscription access for Claude Code · Use an Anthropic API key instead, or ask your admin to enable access","api_error_status":403}'
        provider = ClaudeCliProvider()
        result = provider.parse_result(1, raw, "", self.data.name, "sonnet")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, ERR_ACCESS_DENIED)
        self.assertNotIn("API key", result.error_detail)
        result = provider.reconcile_failure(result, BrainStatus("claude_cli", STATE_READY))
        evidence.record("claude_cli", ok=False, error_kind=result.error_kind)
        shown = evidence.decorate_status(BrainStatus("claude_cli", STATE_READY,
                                                    binary="/test/claude").to_dict(public=True))
        self.assertEqual(shown["auth_state"], "authenticated")
        self.assertEqual(shown["access_state"], "denied")
        self.assertEqual(shown["state"], "access_denied")
        self.assertEqual(shown["last_test_state"], "failed")
        self.assertNotIn("binary", shown)
        path = Path(self.data.name) / "modelos" / "cli-provider-evidence.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("organization", path.read_text())

    def test_auth_failure_does_not_get_reclassified_as_denial(self):
        provider = ClaudeCliProvider()
        self.assertEqual(provider.classify_error("Not logged in")[0], "no_auth")
        self.assertEqual(provider.classify_error("usage limit reached")[0], "rate_limit")
        self.assertEqual(provider.classify_error("HTTP 529 overloaded")[0], "service_unavailable")

    def test_explicit_entitlement_phrase_requires_fresh_authenticated_status(self):
        provider = ClaudeCliProvider()
        raw = '{"is_error":true,"api_error_status":403,"result":"Your organization has disabled Claude subscription access for Claude Code"}'
        result = provider.parse_result(1, raw, "", self.data.name, "sonnet")
        unknown = provider.reconcile_failure(result, BrainStatus("claude_cli", STATE_AUTH_EXPIRED))
        self.assertNotEqual(unknown.error_kind, ERR_ACCESS_DENIED)
        self.assertEqual(unknown.error_kind, "auth_expired")

    def test_generic_403_is_provider_error_after_fresh_auth(self):
        provider = ClaudeCliProvider()
        result = provider.parse_result(1, '{"is_error":true,"api_error_status":403,"result":"Forbidden"}', "", self.data.name, "sonnet")
        result = provider.reconcile_failure(result, BrainStatus("claude_cli", STATE_READY))
        self.assertEqual(result.error_kind, ERR_PROVIDER)
        self.assertNotEqual(result.error_kind, ERR_ACCESS_DENIED)

    def test_old_denial_returns_to_unverified(self):
        evidence.record("claude_cli", ok=False, error_kind=ERR_ACCESS_DENIED)
        future = time.time() + evidence.EVIDENCE_TTL_S + 1
        with patch("cli_brain.evidence.time.time",
                   return_value=future):
            shown = evidence.decorate_status(BrainStatus("claude_cli", STATE_READY,
                                                        binary="/test/claude").to_dict(public=True))
        self.assertEqual(shown["state"], STATE_READY)
        self.assertEqual(shown["access_state"], "unknown")
        self.assertEqual(shown["last_test_state"], "not_run")


if __name__ == "__main__":
    unittest.main()
