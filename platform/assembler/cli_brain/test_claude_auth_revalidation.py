"""Claude auth expiry, cache bypass, and entitlement classification without provider calls."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from cli_brain import detect, evidence
from cli_brain.base import (
    BrainResult, BrainStatus, ERR_ACCESS_DENIED, ERR_AUTH_EXPIRED,
    ERR_AUTH_UNKNOWN, ERR_MODEL, ERR_NO_AUTH, ERR_PROVIDER,
    STATE_AUTH_EXPIRED, STATE_AUTH_UNKNOWN, STATE_NOT_INSTALLED,
    STATE_NO_AUTH, STATE_READY,
)
from cli_brain.claude_cli import ClaudeCliProvider


class ClaudeAuthRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory(prefix="aleph-claude-auth-")
        self.addCleanup(self.data.cleanup)
        env = patch.dict(os.environ, {"ALEPH_DATA_DIR": self.data.name})
        env.start()
        self.addCleanup(env.stop)
        self.provider = ClaudeCliProvider()

    def test_a_binary_absent_is_not_installed(self):
        with patch.object(self.provider, "_resolve_binary", return_value=(None, "auto", "")):
            self.assertEqual(self.provider.detect().state, STATE_NOT_INSTALLED)

    def test_b_logged_out_is_not_authenticated(self):
        state, _, _ = self.provider.parse_detect(0, '{"loggedIn":false}', "")
        self.assertEqual(state, STATE_NO_AUTH)

    def test_c_explicit_expiry_is_distinct(self):
        state, detail, _ = self.provider.parse_detect(
            1, '{"loggedIn":false,"tokenExpired":true}', "")
        self.assertEqual(state, STATE_AUTH_EXPIRED)
        self.assertIn("claude auth login", detail)

    def test_d_auth_probe_timeout_is_unknown(self):
        with patch.object(self.provider, "_resolve_binary", return_value=("/tmp/claude", "auto", "")), \
             patch("cli_brain.base._run_managed", side_effect=subprocess.TimeoutExpired("claude", 1)):
            self.assertEqual(self.provider.detect().state, STATE_AUTH_UNKNOWN)

    def test_force_refresh_bypasses_cached_authenticated_state(self):
        cached = BrainStatus("claude_cli", STATE_READY, checked_at=time.time())
        detect._cache["claude_cli"] = cached
        self.addCleanup(lambda: detect._cache.pop("claude_cli", None))
        expired = BrainStatus("claude_cli", STATE_AUTH_EXPIRED, checked_at=time.time())
        with patch.object(detect.PROVIDERS["claude_cli"], "detect", return_value=expired) as probe:
            got = detect.detect_one("claude_cli", force_refresh=True)
        probe.assert_called_once_with()
        self.assertEqual(got.state, STATE_AUTH_EXPIRED)

    def _error(self, status, message="provider request failed"):
        raw = json.dumps({"is_error": True, "api_error_status": status,
                          "terminal_reason": "api_error", "result": message})
        return self.provider.parse_result(1, raw, "", self.data.name, "opus")

    def test_e_and_f_stale_authenticated_then_403_or_502_expired(self):
        fresh_expired = BrainStatus("claude_cli", STATE_AUTH_EXPIRED)
        for status in (403, 502):
            with self.subTest(status=status):
                got = self.provider.reconcile_failure(self._error(status), fresh_expired)
                self.assertEqual(got.error_kind, ERR_AUTH_EXPIRED)

    def test_403_alone_is_not_access_denied(self):
        result = self._error(403)
        self.assertNotEqual(result.error_kind, ERR_ACCESS_DENIED)
        got = self.provider.reconcile_failure(result, BrainStatus("claude_cli", STATE_READY))
        self.assertEqual(got.error_kind, ERR_PROVIDER)

    def test_g_access_denial_needs_fresh_auth_and_explicit_policy_evidence(self):
        raw = json.dumps({"is_error": True, "api_error_status": 403,
                          "result": "Your organization has disabled Claude subscription access for Claude Code"})
        denied = self.provider.parse_result(1, raw, "", self.data.name, "opus")
        self.assertEqual(denied.error_kind, ERR_ACCESS_DENIED)
        accepted = self.provider.reconcile_failure(denied, BrainStatus("claude_cli", STATE_READY))
        self.assertEqual(accepted.error_kind, ERR_ACCESS_DENIED)
        stale = self.provider.reconcile_failure(denied, BrainStatus("claude_cli", STATE_AUTH_UNKNOWN))
        self.assertEqual(stale.error_kind, ERR_AUTH_UNKNOWN)

    def test_h_generic_502_after_fresh_auth_is_provider_error(self):
        got = self.provider.reconcile_failure(self._error(502), BrainStatus("claude_cli", STATE_READY))
        self.assertEqual(got.error_kind, ERR_PROVIDER)

    def test_i_reauthentication_clears_old_access_verdict(self):
        evidence.record("claude_cli", ok=True, actual_model="claude-opus-4-1")
        evidence.clear_access("claude_cli")
        shown = evidence.decorate_status(
            BrainStatus("claude_cli", STATE_READY, checked_at=time.time()).to_dict(public=True))
        self.assertEqual(shown["auth_state"], "authenticated")
        self.assertEqual(shown["access_state"], "unknown")

    def test_j_success_records_authenticated_and_allowed(self):
        raw = json.dumps({"result": "ok", "modelUsage": {"claude-opus-4-1": {
            "inputTokens": 2, "outputTokens": 1}}, "usage": {
                "input_tokens": 2, "output_tokens": 1}, "num_turns": 1})
        result = self.provider.parse_result(0, raw, "", self.data.name, "opus")
        self.assertTrue(result.ok)
        self.assertEqual(result.model_final, "claude-opus-4-1")
        evidence.record("claude_cli", ok=True, actual_model=result.model_final)
        shown = evidence.decorate_status(
            BrainStatus("claude_cli", STATE_READY, checked_at=time.time()).to_dict(public=True))
        self.assertEqual(shown["auth_state"], "authenticated")
        self.assertEqual(shown["access_state"], "allowed")
        self.assertEqual(shown["last_test_state"], "passed")

    def test_no_secret_output_enters_auth_diagnostics(self):
        state, detail, extra = self.provider.parse_detect(
            1, '{"loggedIn":false,"message":"OAuth token expired secret-value-should-not-leak"}', "")
        self.assertEqual(state, STATE_AUTH_EXPIRED)
        self.assertNotIn("secret-value", detail)
        self.assertNotIn("secret-value", str(extra))


if __name__ == "__main__":
    unittest.main()
