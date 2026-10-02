"""Phase B model choice, override and CLI fallback contract."""
import os
import unittest
from unittest.mock import patch

import models
import recipe_assembler as ra


class ModelIdentityTests(unittest.TestCase):
    def test_production_ignores_operator_override_of_selected_cli(self):
        with patch.dict(os.environ, {"ALEPH_ROLE": "client", "PUPPET_BRAIN": "oss"}):
            resolved = models.resolve_recipe_model({"brain_provider": "codex_cli",
                                                    "cli_model": "gpt-5.6-sol"})
        self.assertEqual(resolved["brain_provider"], "codex_cli")
        self.assertEqual(resolved["alias"], "codex_cli")
        self.assertFalse(resolved["override_used"])
        self.assertTrue(resolved["override_blocked"])
        self.assertEqual(resolved["requested_model"], "gpt-5.6-sol")

    def test_development_override_is_declared(self):
        with patch.dict(os.environ, {"ALEPH_ROLE": "dev", "PUPPET_BRAIN": "oss"}):
            resolved = models.resolve_recipe_model({"brain_provider": "codex_cli"})
        self.assertTrue(resolved["override_used"])
        self.assertEqual(resolved["override_source"], "PUPPET_BRAIN")
        self.assertIsNone(resolved["brain_provider"])
        self.assertEqual(resolved["requested_provider"], "codex_cli")

    def test_cli_has_no_cross_family_fallback(self):
        tiers = ra._tiers_de("http://127.0.0.1:8926/v1", "codex-cli", "another-model")
        self.assertEqual(tiers, [("codex-cli", "http://127.0.0.1:8926/v1", "primary")])

    def test_unknown_cli_model_is_not_wrapper_id(self):
        record = {"brain_provider": "codex_cli", "model_route": [{"ok": True, "tier": "primary"}]}
        response = {"model": "codex-cli", "aleph_cli_brain": {"actual_model": None}}
        self.assertIsNone(ra._honest_model_final(response, "codex-cli", record))

    def test_identity_keeps_requested_resolved_actual_separate(self):
        record = {"brain_provider": "codex_cli", "model_route": [{"ok": True, "tier": "primary"}],
                  "model_identity": {"requested_provider": "codex_cli",
                                     "requested_model": "gpt-5.6-sol", "override_used": False}}
        response = {"model": "gpt-5.6-sol", "aleph_cli_brain": {
            "brain_provider": "codex_cli", "resolved_model": "gpt-5.6-sol",
            "actual_model": "gpt-5.6-sol", "actual_model_source": "requested-validated"}}
        ra._update_model_identity(record, response, "codex-cli", "http://127.0.0.1:8926/v1")
        identity = record["model_identity"]
        self.assertEqual(identity["requested_model"], "gpt-5.6-sol")
        self.assertEqual(identity["resolved_model"], "gpt-5.6-sol")
        self.assertEqual(identity["actual_model"], "gpt-5.6-sol")
        self.assertEqual(identity["actual_model_source"], "requested-validated")
        self.assertFalse(identity["fallback_used"])

    def test_hosted_to_local_fallback_exposes_reason_and_target(self):
        record = {"brain_provider": None, "model_route": [{"ok": False, "tier": "primary"},
                  {"ok": True, "tier": "oss-direct", "causa_previa": {"causa": "service_unavailable"}}],
                  "model_identity": {"requested_provider": "api.example.test",
                                     "requested_model": "requested-model", "override_used": False}}
        ra._update_model_identity(record, {"model": "local-reported-model"},
                                  "local-requested-model", "http://127.0.0.1:11434/v1")
        identity = record["model_identity"]
        self.assertTrue(identity["fallback_used"])
        self.assertEqual(identity["fallback_reason"], "service_unavailable")
        self.assertEqual(identity["resolved_provider"], "local")
        self.assertEqual(identity["resolved_model"], "local-requested-model")
        self.assertIsNone(identity["actual_provider"])
        self.assertEqual(identity["actual_model"], "local-reported-model")


if __name__ == "__main__":
    unittest.main()
