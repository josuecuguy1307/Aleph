"""Cooldown semantics for real Claude CLI outcomes; no provider process is run."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_ASSEMBLER = _HERE.parent
for _path in (str(_ASSEMBLER), str(_ASSEMBLER.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cli_brain import evidence
from cli_brain.slots import EN_PAUSA, SinSlot, Slots, causa_de


class CooldownStateTests(unittest.TestCase):
    def setUp(self):
        self.slots = Slots(limite=1)

    def test_provider_rate_limit_creates_a_local_cooldown(self):
        event = self.slots.registrar_rate_limit(
            "claude_cli", retry_after_s=120, reset_hint="2 min", ahora=1000)

        self.assertEqual(event["state"], "provider_rate_limited")
        self.assertEqual(event["origin"], "provider")
        self.assertEqual(event["reset_hint"], "2 min")
        self.assertTrue(self.slots.estado_provider("claude_cli", ahora=1001)
                        ["local_cooldown"]["active"])

    def test_local_request_is_blocked_and_says_cooldown_not_live_quota(self):
        self.slots.registrar_rate_limit(
            "claude_cli", retry_after_s=120, reset_hint="2 min", ahora=1000)

        with self.assertRaises(SinSlot) as raised:
            self.slots.pedir("claude_cli", ahora=1001)

        self.assertEqual(raised.exception.motivo, EN_PAUSA)
        cause = causa_de(raised.exception, nombre_cli="Claude Code")
        self.assertEqual(cause["runtime_state"], "local_cooldown_from_previous_limit")
        self.assertEqual(cause["quota_availability"], "unknown")
        self.assertIn("anteriormente", cause["detalle"])
        self.assertIn("no puede confirmar la cuota disponible", cause["detalle"])
        provider_event = cause["evidencia"]["provider_event"]
        self.assertEqual(provider_event["origin"], "provider")
        self.assertEqual(provider_event["reset_hint"], "2 min")

    def test_later_real_success_clears_cooldown_and_keeps_limit_history(self):
        self.slots.registrar_rate_limit(
            "claude_cli", retry_after_s=120, reset_hint="2 min", ahora=1000)

        success = self.slots.registrar_ejecucion_exitosa(
            "claude_cli", actual_model="claude-sonnet", ahora=1010)
        status = self.slots.estado_provider("claude_cli", authenticated_ready=True,
                                            ahora=1011)

        self.assertEqual(success["state"], "execution_verified_after_limit")
        self.assertFalse(status["local_cooldown"]["active"])
        self.assertEqual(status["last_execution_state"], "execution_verified_after_limit")
        self.assertEqual(status["last_provider_event"]["reset_hint"], "2 min")
        self.slots.pedir("claude_cli", ahora=1011)
        self.slots.soltar("claude_cli")

    def test_stale_limit_callback_cannot_override_newer_success(self):
        self.slots.registrar_rate_limit(
            "claude_cli", retry_after_s=120, reset_hint="2 min", ahora=1000)
        self.slots.registrar_ejecucion_exitosa("claude_cli", ahora=1010)

        delayed = self.slots.registrar_rate_limit(
            "claude_cli", retry_after_s=3600, reset_hint="stale", ahora=1005)
        status = self.slots.estado_provider("claude_cli", ahora=1011)

        self.assertTrue(delayed["superseded"])
        self.assertEqual(delayed["superseded_by_execution_at"], 1010)
        self.assertFalse(status["local_cooldown"]["active"])
        self.assertEqual(status["last_execution_state"], "execution_verified_after_limit")
        self.assertEqual(status["last_provider_event"]["reset_hint"], "2 min")

    def test_authenticated_ready_does_not_claim_quota_available(self):
        self.slots.registrar_rate_limit(
            "claude_cli", retry_after_s=120, ahora=1000)

        status = self.slots.estado_provider("claude_cli", authenticated_ready=True,
                                            ahora=1001)

        self.assertTrue(status["authenticated_ready"])
        self.assertEqual(status["quota_availability"], "unknown")
        self.assertEqual(status["local_cooldown"]["state"],
                         "local_cooldown_from_previous_limit")

    def test_persisted_stale_limit_cannot_replace_newer_success(self):
        with tempfile.TemporaryDirectory(prefix="aleph-cooldown-state-") as tmp:
            path = Path(tmp) / "cli-provider-evidence.json"
            with patch("cli_brain.evidence._path", return_value=path):
                evidence.record_provider_rate_limit(
                    "claude_cli", retry_after_s=90, reset_hint="90 sec",
                    occurred_at=1000)
                success = evidence.record(
                    "claude_cli", ok=True, actual_model="claude-sonnet",
                    occurred_at=1010)
                stale = evidence.record_provider_rate_limit(
                    "claude_cli", retry_after_s=3600, reset_hint="stale",
                    occurred_at=1005)

                persisted = evidence.get("claude_cli")

        self.assertEqual(success["last_execution_state"],
                         "execution_verified_after_limit")
        self.assertEqual(stale["reset_hint"], "90 sec")
        self.assertEqual(persisted["last_execution_state"],
                         "execution_verified_after_limit")
        self.assertEqual(persisted["last_provider_rate_limit"]["reset_hint"], "90 sec")
        self.assertEqual(persisted["quota_availability"], "unknown")


if __name__ == "__main__":
    unittest.main()
