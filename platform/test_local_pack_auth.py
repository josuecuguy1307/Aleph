"""Regresión stdlib para la capability de los packs HTTP locales."""

import io
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path

from local_pack_auth import guard_post


class _Handler:
    def __init__(self, headers):
        self.headers = Message()
        for key, value in headers:
            self.headers[key] = value
        self.wfile = io.BytesIO()
        self.status = None
        self.close_connection = False

    def send_response(self, status): self.status = status
    def send_header(self, *_): pass
    def end_headers(self): pass


class LocalPackAuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "cap"
        path.write_text("secret-cap\n", encoding="utf-8")
        os.chmod(path, 0o600)
        os.environ["ALEPH_PACK_INTERNAL_CAP_FILE"] = str(path)
        os.environ["ALEPH_PACK_PORT"] = "8123"

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("ALEPH_PACK_INTERNAL_CAP_FILE", None)
        os.environ.pop("ALEPH_PACK_PORT", None)

    def good(self):
        return [("Host", "127.0.0.1:8123"), ("Content-Type", "application/json"),
                ("Content-Length", "2"), ("Authorization", "Bearer secret-cap")]

    def test_accepts_parent_capability(self):
        self.assertTrue(guard_post(_Handler(self.good())))

    def test_rejects_cross_site_and_bad_cap_before_body(self):
        for extra in ([('Origin', 'https://evil.example')],
                      [('Sec-Fetch-Site', 'cross-site')],
                      [('Authorization', 'Bearer wrong')],
                      [('Host', 'evil.example')]):
            base = [(k, v) for k, v in self.good() if k != extra[0][0]] + extra
            h = _Handler(base)
            self.assertFalse(guard_post(h))
            self.assertTrue(h.close_connection)

    def test_rejects_ambiguous_or_unbounded_bodies(self):
        cases = [
            [(k, v) for k, v in self.good() if k != "Content-Length"],
            self.good() + [("Content-Length", "3")],
            [(k, "-1" if k == "Content-Length" else v) for k, v in self.good()],
            [(k, "999999" if k == "Content-Length" else v) for k, v in self.good()],
            [(k, "text/plain" if k == "Content-Type" else v) for k, v in self.good()],
            self.good() + [("Transfer-Encoding", "chunked")],
        ]
        for headers in cases:
            self.assertFalse(guard_post(_Handler(headers)))


if __name__ == "__main__":
    unittest.main()
