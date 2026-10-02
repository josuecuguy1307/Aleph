"""Synthetic regressions for the desktop OAuth PKCE mailbox boundary."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import time
import unittest
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("PUPPET_WORKERS", "0")
os.environ["ALEPH_SIDECAR_PORT"] = "80"
_oauth_test_data = tempfile.TemporaryDirectory(prefix="aleph-oauth-boundary-")
os.environ["ALEPH_DATA_DIR"] = _oauth_test_data.name
os.environ["ALEPH_ROLE"] = "client"

from app import main as app_main  # noqa: E402
from app.launch_cap import install as install_launch_cap  # noqa: E402


class DesktopOAuthBoundaryTest(unittest.TestCase):
    def setUp(self):
        os.environ["ALEPH_SIDECAR_PORT"] = "80"
        install_launch_cap("oauth-test-launch-capability")
        app_main._desktop_oauth_box.clear()
        self.client = TestClient(app_main.app, base_url="http://127.0.0.1")
        self.client.headers.update({"Origin": "http://127.0.0.1"})
        self.cap = {"X-Aleph-Launch": "oauth-test-launch-capability"}
        self.nonce = "oauth-test-nonce-0123456789"
        self.state = "oauth-test-state-0123456789"

    def test_claim_requires_launch_capability_and_does_not_consume_on_denial(self):
        self.assertEqual(
            self.client.post("/auth/desktop/start", headers=self.cap,
                             json={"aleph_nonce": self.nonce, "aleph_state": self.state}).status_code,
            204,
        )
        self.assertEqual(
            self.client.post("/auth/desktop/session",
                             json={"aleph_nonce": self.nonce, "aleph_state": self.state,
                                   "code": "synthetic-code"}).status_code,
            204,
        )
        self.assertEqual(
            self.client.get("/auth/desktop/session", params={"aleph_nonce": self.nonce}).status_code,
            403,
        )
        self.assertIn(self.nonce, app_main._desktop_oauth_box)
        response = self.client.get("/auth/desktop/session", headers=self.cap,
                                   params={"aleph_nonce": self.nonce})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"code": "synthetic-code"})
        self.assertEqual(
            self.client.get("/auth/desktop/session", headers=self.cap,
                            params={"aleph_nonce": self.nonce}).status_code,
            204,
        )

    def test_token_payloads_unknown_nonces_and_overwrites_are_rejected(self):
        self.assertEqual(self.client.post("/auth/desktop/start", headers=self.cap,
                                          json=[]).status_code, 400)
        self.assertEqual(
            self.client.post("/auth/desktop/session",
                             json={"aleph_nonce": self.nonce, "aleph_state": self.state,
                                   "code": "x"}).status_code,
            404,
        )
        self.assertEqual(
            self.client.post("/auth/desktop/start", headers=self.cap,
                             json={"aleph_nonce": self.nonce, "aleph_state": self.state}).status_code,
            204,
        )
        token_payload = {
            "aleph_nonce": self.nonce,
            "aleph_state": self.state,
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
        }
        self.assertEqual(self.client.post("/auth/desktop/session", json=token_payload).status_code, 400)
        self.assertEqual(app_main._desktop_oauth_box[self.nonce][0], None)
        self.assertEqual(
            self.client.post("/auth/desktop/session",
                             json={"aleph_nonce": self.nonce, "aleph_state": self.state,
                                   "code": "first"}).status_code,
            204,
        )
        self.assertEqual(
            self.client.post("/auth/desktop/session",
                             json={"aleph_nonce": self.nonce, "aleph_state": self.state,
                                   "code": "second"}).status_code,
            409,
        )

    def test_expired_nonce_cannot_receive_or_release_code(self):
        self.assertEqual(self.client.post("/auth/desktop/start", headers=self.cap,
                                          json={"aleph_nonce": self.nonce,
                                                "aleph_state": self.state}).status_code, 204)
        app_main._desktop_oauth_box[self.nonce] = (
            None, time.monotonic() - app_main._DESKTOP_OAUTH_TTL - 1, self.state,
        )
        self.assertEqual(self.client.post("/auth/desktop/session", json={
            "aleph_nonce": self.nonce, "aleph_state": self.state, "code": "expired-code",
        }).status_code, 404)
        self.assertEqual(self.client.get("/auth/desktop/session", headers=self.cap,
                                         params={"aleph_nonce": self.nonce}).status_code, 204)

    def test_claim_rejects_wrong_origin_and_port_without_consuming(self):
        self.assertEqual(self.client.post("/auth/desktop/start", headers=self.cap,
                                          json={"aleph_nonce": self.nonce,
                                                "aleph_state": self.state}).status_code, 204)
        self.assertEqual(self.client.post("/auth/desktop/session", json={
            "aleph_nonce": self.nonce, "aleph_state": self.state, "code": "synthetic-code",
        }).status_code, 204)
        for extra in ({"Origin": "https://attacker.example"},
                      {"Host": "127.0.0.1:9999"}):
            response = self.client.get("/auth/desktop/session", params={"aleph_nonce": self.nonce},
                                       headers={**self.cap, **extra})
            self.assertEqual(response.status_code, 403)
            self.assertIn(self.nonce, app_main._desktop_oauth_box)
        response = self.client.get("/auth/desktop/session", headers=self.cap,
                                   params={"aleph_nonce": self.nonce})
        self.assertEqual(response.json(), {"code": "synthetic-code"})

    def test_deposit_and_callback_reject_wrong_origin_or_port(self):
        self.assertEqual(self.client.post("/auth/desktop/start", headers=self.cap,
                                          json={"aleph_nonce": self.nonce,
                                                "aleph_state": self.state}).status_code, 204)
        for extra in ({"Origin": "https://attacker.example"},
                      {"Origin": "http://127.0.0.1:9999"},
                      {"Host": "127.0.0.1:9999"},
                      {"Host": "127.0.0.1.attacker.example"},
                      {"Origin": ""}):
            self.assertEqual(self.client.post("/auth/desktop/session", headers=extra,
                json={"aleph_nonce": self.nonce, "aleph_state": self.state,
                      "code": "forged"}).status_code, 403)
            self.assertIsNone(app_main._desktop_oauth_box[self.nonce][0])
        self.assertEqual(self.client.get("/auth/desktop/callback",
                                         headers={"Host": "127.0.0.1:9999"}).status_code, 403)
        self.assertEqual(self.client.get("/auth/desktop/callback").status_code, 200)

    def test_concurrent_callbacks_do_not_overwrite_first_code(self):
        self.assertEqual(self.client.post("/auth/desktop/start", headers=self.cap,
                                          json={"aleph_nonce": self.nonce,
                                                "aleph_state": self.state}).status_code, 204)
        def deposit(i):
            return self.client.post("/auth/desktop/session", json={
                "aleph_nonce": self.nonce, "aleph_state": self.state,
                "code": f"code-{i}",
            }).status_code
        with ThreadPoolExecutor(max_workers=12) as pool:
            statuses = list(pool.map(deposit, range(24)))
        self.assertEqual(statuses.count(204), 1)
        self.assertEqual(statuses.count(409), 23)
        claim = self.client.get("/auth/desktop/session", headers=self.cap,
                                params={"aleph_nonce": self.nonce})
        self.assertEqual(claim.status_code, 200)
        self.assertRegex(claim.json()["code"], r"^code-\d+$")

    def test_concurrent_claim_is_exactly_once_and_nonce_cannot_restart(self):
        self.assertEqual(self.client.post("/auth/desktop/start", headers=self.cap,
                                          json={"aleph_nonce": self.nonce,
                                                "aleph_state": self.state}).status_code, 204)
        self.assertEqual(self.client.post("/auth/desktop/session", json={
            "aleph_nonce": self.nonce, "aleph_state": self.state,
            "code": "one-shot-code",
        }).status_code, 204)
        def claim(_):
            return self.client.get("/auth/desktop/session", headers=self.cap,
                                   params={"aleph_nonce": self.nonce}).status_code
        with ThreadPoolExecutor(max_workers=16) as pool:
            statuses = list(pool.map(claim, range(32)))
        self.assertEqual(statuses.count(200), 1)
        self.assertEqual(statuses.count(204), 31)
        self.assertEqual(self.client.post("/auth/desktop/start", headers=self.cap,
                                          json={"aleph_nonce": self.nonce,
                                                "aleph_state": self.state}).status_code, 409)

    def test_frontend_uses_pkce_code_exchange_and_never_sets_mailbox_tokens(self):
        source = (Path(__file__).resolve().parents[2] / "app" / "design" / "supabase-auth.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("flowType: 'pkce'", source)
        self.assertIn("exchangeCodeForSession(tok.code)", source)
        desktop = source[source.index("async function _entrarDesktop"):source.index("async function entrarCon")]
        self.assertNotIn("setSession(", desktop)

    def test_launch_capability_is_not_in_sidecar_argv_or_pack_child_env(self):
        product = Path(__file__).resolve().parents[2]
        repo = product.parent
        shell = (repo / "deploy" / "fase4" / "aleph-shell" / "src-tauri" / "src" / "lib.rs").read_text(
            encoding="utf-8"
        )
        sidecar = (repo / "deploy" / "fase4" / "sidecar_serve.py").read_text(encoding="utf-8")
        handoff = (repo / "deploy" / "fase4" / "listener_handoff.py").read_text(encoding="utf-8")
        packs = (repo / "platform" / "workspaces" / "pack.py").read_text(encoding="utf-8")
        spawn = shell[shell.index("fn spawn_sidecar"):shell.index("pub fn run()")]
        self.assertNotIn('.arg("--launch-cap").arg(launch_cap)', spawn)
        self.assertIn('arg("--launch-cap-stdin=1")', spawn)
        self.assertIn('arg("--listen-fd").arg(listen_fd.to_string())', spawn)
        self.assertIn('let port_guard = bound_socket.clone()', shell)
        self.assertIn('GET /health HTTP/1.1', shell)
        self.assertIn("location.hostname==='127.0.0.1'", shell)
        self.assertNotIn("['127.0.0.1','localhost','::1','[::1]'].includes(location.hostname)", shell)
        self.assertNotIn('if TcpStream::connect(("127.0.0.1", port)).is_ok()', shell)
        self.assertIn("sys.stdin.readline(256)", sidecar)
        self.assertIn('server.run(sockets=[inherited_socket] if inherited_socket is not None else None)', sidecar)
        self.assertIn('inherited_loopback_listener as _inherited_loopback_listener', sidecar)
        self.assertIn('inherited.set_inheritable(False)', handoff)
        self.assertIn('os.environ.pop("ALEPH_LAUNCH_CAP", None)', sidecar)
        self.assertIn("install_launch_cap(launch_cap)", sidecar)
        self.assertNotIn('os.environ["ALEPH_LAUNCH_CAP"] = launch_cap', sidecar)
        self.assertIn('k != "ALEPH_LAUNCH_CAP"', packs)
        self.assertIn("if(own)Object.defineProperty", shell)

    def test_shell_capability_script_only_trusts_exact_ipv4_sidecar_host(self):
        repo = Path(__file__).resolve().parents[3]
        shell = (repo / "deploy" / "fase4" / "aleph-shell" / "src-tauri" / "src" / "lib.rs").read_text()
        match = re.search(r'format!\("(\(\(\)=>\{\{const own=.*?)"\)', shell)
        self.assertIsNotNone(match)
        script = match.group(1)
        for key, value in {"{sidecar_port}": "8330", "{cap}": '"synthetic-cap"',
                           "{lang}": "es", "{title}": "inicio", "{detail}": "espera"}.items():
            script = script.replace(key, value)
        script = script.replace("{{", "{").replace("}}", "}")
        driver = (
            "const vm=require('vm'),assert=require('assert/strict');"
            "for(const host of ['127.0.0.1','localhost','::1','[::1]','127.0.0.1.attacker']){"
            "const w={},c={window:w,location:{protocol:'http:',hostname:host,port:'8330'},"
            "document:{readyState:'complete'}};vm.runInNewContext(process.argv[1],c);"
            "assert.equal(w.__ALEPH_LAUNCH_CAP__,host==='127.0.0.1'?'synthetic-cap':undefined);"
            "}"
        )
        result = subprocess.run(["node", "-e", driver, script], capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_sidecar_listener_adoption_is_exact_and_not_inheritable(self):
        import importlib.util
        repo = Path(__file__).resolve().parents[3]
        path = repo / "deploy" / "fase4" / "listener_handoff.py"
        spec = importlib.util.spec_from_file_location("aleph_sidecar_oauth_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(2)
            port = listener.getsockname()[1]
            fd = os.dup(listener.fileno())
            os.set_inheritable(fd, True)
            inherited = module.inherited_loopback_listener(port, str(fd))
            try:
                self.assertEqual(inherited.getsockname(), ("127.0.0.1", port))
                self.assertFalse(inherited.get_inheritable())
            finally:
                inherited.close()
            wrong_fd = os.dup(listener.fileno())
            with self.assertRaisesRegex(RuntimeError, "exact loopback"):
                module.inherited_loopback_listener(port + 1, str(wrong_fd))

    def test_frozen_component_rejects_wrong_port_and_bad_capability(self):
        probe = os.environ.get("ALEPH_OAUTH_FROZEN_PROBE")
        if not probe:
            self.skipTest("isolated PyInstaller component not supplied")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(2)
            port = listener.getsockname()[1]
            wrong = port - 1 if port == 65535 else port + 1
            env = {"HOME": os.environ["HOME"], "TMPDIR": os.environ["TMPDIR"],
                   "PATH": "/usr/bin:/bin"}
            bad_port = subprocess.run(
                [probe, "--port", str(wrong), "--listen-fd", str(listener.fileno())],
                input="a" * 64 + "\n", text=True, capture_output=True,
                pass_fds=(listener.fileno(),), env=env, timeout=15,
            )
            self.assertNotEqual(bad_port.returncode, 0)
            self.assertIn("exact loopback sidecar port", bad_port.stderr)
            bad_cap = subprocess.run(
                [probe, "--port", str(port), "--listen-fd", str(listener.fileno())],
                input="not-a-capability\n", text=True, capture_output=True,
                pass_fds=(listener.fileno(),), env=env, timeout=15,
            )
            self.assertNotEqual(bad_cap.returncode, 0)
            self.assertIn("invalid private capability", bad_cap.stderr)


if __name__ == "__main__":
    unittest.main()


def tearDownModule():
    _oauth_test_data.cleanup()
