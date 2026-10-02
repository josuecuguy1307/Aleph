"""Regresiones estáticas del canal OAuth desktop event-only."""

import ast
import unittest
from pathlib import Path


PRODUCT = Path(__file__).resolve().parents[2]


class OAuthDiagnosticRedactionTest(unittest.TestCase):
    def test_frontend_never_passes_sensitive_values_to_diag(self):
        source = (PRODUCT / "app" / "design" / "supabase-auth.js").read_text(encoding="utf-8")
        block = source[source.index("function _diag("):source.index("async function entrarCon")]
        self.assertIn("function _diag(paso)", block)
        self.assertNotIn("extra", block)
        self.assertNotIn("_diag('poll:inicio',", block)
        self.assertNotIn("_diag('inicio',", block)

    def test_backend_log_is_allowlisted_and_callback_payload_is_event_only(self):
        path = PRODUCT / "backend" / "app" / "main.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        callback = source[source.index("def _desktop_oauth_callback"):source.index("def _desktop_oauth_deposit")]
        log = source[source.index("async def _desktop_oauth_log"):source.index("class _FrontendStatic")]
        self.assertIn("JSON.stringify({paso:'callback-recibido'})", callback)
        self.assertNotIn("extra:{nonce", callback)
        self.assertNotIn("access_token=h.get", callback)
        self.assertNotIn("refresh_token=h.get", callback)
        self.assertIn("if paso not in allowed", log)
        self.assertNotIn("{body}", log)
        self.assertIn("0o600", log)


if __name__ == "__main__":
    unittest.main()
