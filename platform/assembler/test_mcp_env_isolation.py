"""Cada MCP recibe sólo baseline, runtime y su contrato env declarado."""

import unittest
import os
from unittest.mock import patch

from assembler import MCPServer
from recipe_assembler import _expand_server_cfg
from inspection.transporte_sdk import entorno_hijo


class McpEnvIsolationTest(unittest.TestCase):
    def test_default_sdk_and_legacy_do_not_inherit_host_sentinels(self):
        sentinels = {name: "synthetic-" + name for name in (
            "FAKE_DB_SECRET", "FAKE_JWT_SECRET", "FAKE_STRIPE_SECRET",
            "FAKE_OTHER_PROVIDER_SECRET")}
        with patch.dict(os.environ, sentinels):
            sdk_env = entorno_hijo(None)
            old_env = MCPServer("synthetic", "/usr/bin/false", [])._env
            for name in sentinels:
                self.assertNotIn(name, sdk_env)
                self.assertNotIn(name, old_env)
            self.assertIn("aleph-mcp-runtime-", sdk_env["HOME"])
            self.assertIn("aleph-mcp-runtime-", old_env["HOME"])
            self.assertNotEqual(old_env["HOME"], sdk_env["HOME"])

    def test_unrelated_secrets_do_not_cross_server_boundary(self):
        base = {
            "PATH": "/bin", "HOME": "/home/test", "PUPPET_WORKDIR": "/tmp/run",
            "SUPABASE_JWT_SECRET": "jwt-secret", "DATABASE_URL": "postgres://secret",
            "STRIPE_SECRET_KEY": "stripe-secret", "OPENAI_API_KEY": "openai-secret",
            "ANTHROPIC_API_KEY": "anthropic-secret", "PUPPET_DB_ENC_KEY": "db-master",
        }
        cfg = {"command": "tool", "args": ["${OPENAI_API_KEY}", "${PUPPET_WORKDIR}"],
               "env": {"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"}}
        command, args, child = _expand_server_cfg(cfg, base)
        self.assertEqual(command, "tool")
        self.assertEqual(args, ["${OPENAI_API_KEY}", "/tmp/run"])
        self.assertEqual(child["ANTHROPIC_API_KEY"], "anthropic-secret")
        self.assertEqual(child["HOME"], "/tmp/run")
        self.assertEqual(child["TMPDIR"], "/tmp/run")
        sdk_child = entorno_hijo(child)
        self.assertEqual(sdk_child["HOME"], "/tmp/run")
        self.assertEqual(sdk_child["TMPDIR"], "/tmp/run")
        for name in ("SUPABASE_JWT_SECRET", "DATABASE_URL", "STRIPE_SECRET_KEY",
                     "OPENAI_API_KEY"):
            self.assertNotIn(name, child)
        self.assertNotIn("PUPPET_DB_ENC_KEY", child)


if __name__ == "__main__":
    unittest.main()
