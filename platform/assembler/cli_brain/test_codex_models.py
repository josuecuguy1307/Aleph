"""Codex account model selection does not trust stale local config."""
import os
import unittest
from unittest.mock import patch

from cli_brain.codex_cli import CodexCliProvider


class CodexModelsTests(unittest.TestCase):
    def test_blank_selection_uses_account_default(self):
        provider = CodexCliProvider()
        with patch.object(provider, "binary", return_value="/test/codex"), \
             patch("cli_brain.codex_models.catalog", return_value=(("available",), "available")), \
             patch.dict(os.environ, {"PUPPET_CODEX_CLI_MODEL": ""}):
            self.assertEqual(provider.default_model(), "available")

    def test_catalog_failure_does_not_guess_model(self):
        provider = CodexCliProvider()
        with patch.object(provider, "binary", return_value="/test/codex"), \
             patch("cli_brain.codex_models.catalog", return_value=((), "")), \
             patch.dict(os.environ, {"PUPPET_CODEX_CLI_MODEL": ""}):
            self.assertEqual(provider.default_model(), "")

    def test_explicit_operator_model_is_not_silently_replaced(self):
        provider = CodexCliProvider()
        with patch.dict(os.environ, {"PUPPET_CODEX_CLI_MODEL": "chosen"}):
            self.assertEqual(provider.default_model(), "chosen")

    def test_observed_unsupported_model_is_not_generic_runtime_error(self):
        provider = CodexCliProvider()
        message = "The 'gpt-5.4' model is not supported when using Codex with a ChatGPT account"
        self.assertEqual(provider.classify_error(message)[0], "model_unavailable")


if __name__ == "__main__":
    unittest.main()
