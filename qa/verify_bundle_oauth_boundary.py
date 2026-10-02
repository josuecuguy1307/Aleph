"""Exercise the frozen sidecar's reserved loopback listener and OAuth mailbox.

Uses only synthetic capability/code and a temporary HOME; no provider account.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def request(port: int, path: str, *, method: str = "GET", body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}",
                 **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    binary = args.app / "Contents/MacOS/aleph_sidecar"
    assert binary.is_file()
    capability = secrets.token_hex(32)
    nonce = "synthetic-nonce-0123456789"
    state = "synthetic-state-0123456789"
    code = "synthetic-code-not-a-token"
    with tempfile.TemporaryDirectory(prefix="aleph-bundle-oauth-") as scratch:
        root = Path(scratch)
        for name in ("home", "tmp", "data"):
            (root / name).mkdir()
        env = {"PATH": "/usr/bin:/bin", "HOME": str(root / "home"),
               "TMPDIR": str(root / "tmp"), "ALEPH_DATA_DIR": str(root / "data"),
               "ALEPH_ROLE": "client", "PUPPET_WORKERS": "0", "PUPPET_LITELLM": "0",
               "ALEPH_DUENO": "off"}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(8)
            port = listener.getsockname()[1]
            proc = subprocess.Popen(
                [str(binary), "--port", str(port), "--listen-fd", str(listener.fileno()),
                 "--launch-cap-stdin=1"], env=env, pass_fds=(listener.fileno(),),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                proc.stdin.write((capability + "\n").encode())
                proc.stdin.flush()
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise AssertionError(f"frozen sidecar exited: {proc.returncode}")
                    try:
                        status, body = request(port, "/health")
                        if status == 200 and json.loads(body).get("status") == "ok":
                            break
                    except Exception:
                        time.sleep(0.2)
                else:
                    raise AssertionError("frozen listener health timeout")
                auth = {"X-Aleph-Launch": capability}
                mailbox = {"aleph_nonce": nonce, "aleph_state": state}
                assert request(port, "/auth/desktop/start", method="POST", body=mailbox,
                               headers=auth)[0] == 204
                assert request(port, "/auth/desktop/session", method="POST",
                               body={**mailbox, "code": code, "access_token": "fake"})[0] == 400
                assert request(port, "/auth/desktop/session", method="POST",
                               body={**mailbox, "aleph_state": "wrong-state", "code": code})[0] == 403
                assert request(port, "/auth/desktop/session", method="POST",
                               body={**mailbox, "code": code})[0] == 204
                assert request(port, f"/auth/desktop/session?aleph_nonce={nonce}")[0] == 403
                assert request(port, f"/auth/desktop/session?aleph_nonce={nonce}",
                               headers={**auth, "Origin": "https://attacker.example"})[0] == 403
                assert request(port, f"/auth/desktop/session?aleph_nonce={nonce}",
                               headers={**auth, "Host": "127.0.0.1:1"})[0] == 403
                status, body = request(port, f"/auth/desktop/session?aleph_nonce={nonce}", headers=auth)
                assert status == 200 and json.loads(body) == {"code": code}
                assert request(port, f"/auth/desktop/session?aleph_nonce={nonce}", headers=auth)[0] == 204
            finally:
                proc.terminate()
                try:
                    stdout, stderr = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate(timeout=5)
                assert capability.encode() not in stdout + stderr
                assert code.encode() not in stdout + stderr
        print("PASS frozen OAuth listener, state, capability, origin/port, single claim, log redaction")


if __name__ == "__main__":
    main()
