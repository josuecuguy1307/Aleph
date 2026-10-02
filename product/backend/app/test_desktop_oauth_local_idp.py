"""Real loopback listener + local synthetic IdP; no account or user-data access."""

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_scratch = tempfile.TemporaryDirectory(prefix="aleph-oauth-isolated-")
os.environ["ALEPH_DATA_DIR"] = _scratch.name
os.environ["ALEPH_ROLE"] = "client"
os.environ["PUPPET_WORKERS"] = "0"
os.environ["PUPPET_LITELLM"] = "0"
os.environ["ALEPH_DUENO"] = "off"

_SIDECAR_CODE = r"""
import os, socket, sys, uvicorn
from sidecar_serve import _inherited_loopback_listener
from app.launch_cap import install
install(sys.stdin.readline(256).strip())
port = int(sys.argv[2])
os.environ['ALEPH_SIDECAR_PORT'] = str(port)
sock = _inherited_loopback_listener(port, sys.argv[1])
from app.main import app
uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
    log_level='error', lifespan='off')).run(sockets=[sock])
"""


def _request(url, *, method="GET", body=None, headers=None, timeout=5):
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=payload, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


class _IdP(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    challenges = {}

    def log_message(self, *_args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/authorize":
            self.send_error(404)
            return
        q = urllib.parse.parse_qs(parsed.query)
        code = secrets.token_urlsafe(24)
        self.challenges[code] = q["code_challenge"][0]
        redirect = q["redirect_uri"][0]
        sep = "&" if "?" in redirect else "?"
        location = redirect + sep + urllib.parse.urlencode({"code": code, "state": q["state"][0]})
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path != "/token":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        expected = self.challenges.pop(body.get("code"), None)
        actual = base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        status = 200 if expected and secrets.compare_digest(expected, actual) else 403
        result = {"session": "synthetic-ok"} if status == 200 else {"error": "invalid_grant"}
        raw = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


_CALLBACK_DRIVER = r"""
const fs = require('fs'), vm = require('vm');
const html = fs.readFileSync(0, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const locationUrl = new URL(process.argv[1]);
const pending = [];
const nodes = {h: {textContent: ''}, d: {textContent: ''}};
const context = {
  URLSearchParams, location: {hash: locationUrl.hash, search: locationUrl.search},
  history: {replaceState: () => {}},
  document: {getElementById: id => nodes[id]},
  fetch: (path, options) => {
    const headers = {...(options.headers || {}), Origin: locationUrl.origin};
    const promise = fetch(new URL(path, locationUrl.origin), {...options, headers});
    pending.push(promise);
    return promise;
  }
};
vm.runInNewContext(script, context);
Promise.all(pending).then(() => setTimeout(() => {
  if (!nodes.h.textContent.includes('Listo')) {
    console.error('callback result:', nodes.h.textContent);
    process.exitCode = 2;
  }
}, 100)).catch(() => { process.exitCode = 3; });
"""


class DesktopOAuthLocalIdPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Equivalent isolated Tauri handoff: shell retains an owned listener while
        # the sidecar serves from a duplicate descriptor; no probe→bind race exists.
        cls.bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.bound.bind(("127.0.0.1", 0))
        cls.bound.listen(128)
        cls.port = cls.bound.getsockname()[1]
        cls.sidecar_socket = socket.socket(fileno=os.dup(cls.bound.fileno()))
        os.environ["ALEPH_SIDECAR_PORT"] = str(cls.port)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.cap = secrets.token_hex(32)
        cls.log = open(Path(_scratch.name) / "sidecar.log", "w+b")
        child_env = {**os.environ, "ALEPH_DATA_DIR": _scratch.name,
                     "ALEPH_ROLE": "client", "PUPPET_WORKERS": "0",
                     "PUPPET_LITELLM": "0", "ALEPH_DUENO": "off"}
        repo = Path(__file__).resolve().parents[3]
        child_env["PYTHONPATH"] = os.pathsep.join((str(repo / "product" / "backend"),
            str(repo / "platform"), str(repo / "deploy" / "fase4")))
        cls.worker = subprocess.Popen([sys.executable, "-c", _SIDECAR_CODE,
            str(cls.sidecar_socket.fileno()), str(cls.port)],
            cwd=str(Path(__file__).resolve().parents[2]), env=child_env,
            pass_fds=(cls.sidecar_socket.fileno(),), stdin=subprocess.PIPE,
            stdout=cls.log, stderr=subprocess.STDOUT)
        cls.sidecar_socket.close()
        cls.worker.stdin.write((cls.cap + "\n").encode())
        cls.worker.stdin.close()
        for _ in range(100):
            try:
                with _request(cls.base + "/health", timeout=0.2) as ready:
                    if ready.status != 200 or json.load(ready).get("service") != "puppet-ai-core":
                        raise AssertionError("wrong isolated OAuth responder")
                    break
            except OSError:
                time.sleep(0.02)
        else:
            raise AssertionError("isolated OAuth listener did not start")
        cls.idp = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _IdP)
        cls.idp_thread = threading.Thread(target=cls.idp.serve_forever, daemon=True)
        cls.idp_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.idp.shutdown()
        cls.idp.server_close()
        cls.idp_thread.join(timeout=3)
        cls.worker.terminate()
        cls.worker.wait(timeout=5)
        cls.log.flush()
        cls.log.seek(0)
        raw_log = cls.log.read().decode("utf-8", "replace")
        cls.log.close()
        if cls.cap in raw_log:
            raise AssertionError("launch capability leaked to sidecar logs")
        # Even after a sidecar crash/exit, the shell-held descriptor prevents a
        # same-user port squatter from taking the capability-bearing origin.
        with socket.socket() as squatter:
            with cls.assertRaises(cls, OSError):
                squatter.bind(("127.0.0.1", cls.port))
        cls.bound.close()
        _scratch.cleanup()

    def setUp(self):
        self.nonce = secrets.token_urlsafe(24)
        self.state = secrets.token_urlsafe(24)
        self.headers = {"X-Aleph-Launch": self.cap, "Origin": self.base}

    def test_complete_synthetic_pkce_idp_callback_and_single_claim(self):
        self.assertEqual(_request(self.base + "/auth/desktop/start", method="POST",
            body={"aleph_nonce": self.nonce, "aleph_state": self.state},
            headers=self.headers).status, 204)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        callback = self.base + "/auth/desktop/callback?" + urllib.parse.urlencode({
            "aleph_nonce": self.nonce, "aleph_state": self.state})
        state = secrets.token_urlsafe(20)
        authorize = f"http://127.0.0.1:{self.idp.server_port}/authorize?" + urllib.parse.urlencode({
            "redirect_uri": callback, "state": state, "code_challenge": challenge})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args):
                return None
        try:
            urllib.request.build_opener(NoRedirect).open(authorize, timeout=5)
            self.fail("IdP did not redirect")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 302)
            returned = exc.headers["Location"]
        parsed = urllib.parse.urlsplit(returned)
        q = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(q["state"][0], state)
        self.assertEqual(q["aleph_nonce"][0], self.nonce)
        self.assertEqual(q["aleph_state"][0], self.state)
        callback_html = _request(returned).read().decode()
        runner = subprocess.run(["node", "-e", _CALLBACK_DRIVER, returned],
            input=callback_html, text=True, capture_output=True, timeout=5)
        self.assertEqual(runner.returncode, 0, runner.stderr)
        claim = _request(self.base + "/auth/desktop/session?aleph_nonce=" + self.nonce,
                         headers=self.headers)
        self.assertEqual(claim.status, 200)
        code = json.load(claim)["code"]
        self.assertEqual(code, q["code"][0])
        self.assertEqual(_request(self.base + "/auth/desktop/session?aleph_nonce=" + self.nonce,
                                  headers=self.headers).status, 204)
        self.assertEqual(_request(f"http://127.0.0.1:{self.idp.server_port}/token",
            method="POST", body={"code": code, "code_verifier": verifier}).status, 200)
        with self.assertRaises(urllib.error.HTTPError) as replay:
            _request(f"http://127.0.0.1:{self.idp.server_port}/token",
                     method="POST", body={"code": code, "code_verifier": verifier})
        self.assertEqual(replay.exception.code, 403)
        diag = Path(_scratch.name) / "oauth-diag.log"
        if diag.exists():
            raw = diag.read_text()
            for secret in (code, verifier, self.nonce, self.state, state, self.cap):
                self.assertNotIn(secret, raw)

    def test_wrong_callback_nonce_cannot_complete_pending_login(self):
        self.assertEqual(_request(self.base + "/auth/desktop/start", method="POST",
            body={"aleph_nonce": self.nonce, "aleph_state": self.state},
            headers=self.headers).status, 204)
        wrong = secrets.token_urlsafe(24)
        callback = self.base + "/auth/desktop/callback?" + urllib.parse.urlencode({
            "aleph_nonce": wrong, "aleph_state": self.state, "code": "forged-code"})
        html = _request(callback).read().decode()
        runner = subprocess.run(["node", "-e", _CALLBACK_DRIVER, callback],
            input=html, text=True, capture_output=True, timeout=5)
        self.assertEqual(runner.returncode, 2)
        self.assertEqual(_request(self.base + "/auth/desktop/session?aleph_nonce=" + self.nonce,
                                  headers=self.headers).status, 204)

    def test_wrong_application_state_rejected_even_with_registered_nonce(self):
        self.assertEqual(_request(self.base + "/auth/desktop/start", method="POST",
            body={"aleph_nonce": self.nonce, "aleph_state": self.state},
            headers=self.headers).status, 204)
        callback = self.base + "/auth/desktop/callback?" + urllib.parse.urlencode({
            "aleph_nonce": self.nonce, "aleph_state": secrets.token_urlsafe(24),
            "code": "forged-code"})
        html = _request(callback).read().decode()
        runner = subprocess.run(["node", "-e", _CALLBACK_DRIVER, callback],
            input=html, text=True, capture_output=True, timeout=5)
        self.assertEqual(runner.returncode, 2)
        self.assertEqual(_request(self.base + "/auth/desktop/session?aleph_nonce=" + self.nonce,
                                  headers=self.headers).status, 204)


if __name__ == "__main__":
    unittest.main()
