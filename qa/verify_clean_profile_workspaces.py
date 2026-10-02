"""Open all packaged workspaces twice under one synthetic, isolated profile."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


WORKSPACES = ("oficina", "educacion", "finanzas", "ciencia", "diseno", "legal")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


def launch(app: Path, root: Path, attempt: int) -> None:
    port = free_port()
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(root / "home"),
        "TMPDIR": str(root / "tmp"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_DATA_HOME": str(root / "xdg-data"),
        "XDG_STATE_HOME": str(root / "state"),
        "ALEPH_DATA_DIR": str(root / "data"),
        "PUPPET_DATA_DIR": str(root / "data"),
        "ALEPH_ROLE": "client",
        "PUPPET_PORT": str(port),
        "PORT": str(port),
    }
    for name in ("home", "tmp", "config", "cache", "xdg-data", "state", "data"):
        (root / name).mkdir(exist_ok=True)
    log_path = root / f"sidecar-{attempt}.log"
    capability = secrets.token_hex(32)
    with log_path.open("w+") as log, socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(8)
        proc = subprocess.Popen(
            [str(app / "Contents/MacOS/aleph_sidecar"), "--port", str(port),
             "--listen-fd", str(listener.fileno()), "--launch-cap-stdin=1"],
            env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            stdin=subprocess.PIPE, pass_fds=(listener.fileno(),),
        )
        assert proc.stdin is not None
        proc.stdin.write((capability + "\n").encode())
        proc.stdin.flush()
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    log.flush()
                    raise AssertionError(f"sidecar exited {proc.returncode}; log: {log_path}: {log_path.read_text()[-1200:]}")
                try:
                    if get(base + "/health")[0] == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.25)
            else:
                raise AssertionError(f"sidecar health timeout; log: {log_path}")
            for page in ("Onboarding.dc.html", "Home.dc.html", "Cuarto.dc.html", "Settings.dc.html"):
                status, _ = get(base + "/" + page)
                assert status == 200, page
            local_req = urllib.request.Request(
                base + "/v1/auth/local", data=b"{}", method="POST",
                headers={"Content-Type": "application/json", "X-Aleph-Launch": capability},
            )
            with urllib.request.urlopen(local_req, timeout=10) as response:
                local = json.load(response)
            auth = {"Authorization": "Bearer " + local["session_token"]}
            user_id = local["id"]
            status, body = get(base + "/v1/workspaces", auth)
            assert status == 200
            found = {row["id"] for row in json.loads(body)["workspaces"]}
            assert found == set(WORKSPACES), found
            for ws in WORKSPACES:
                request = urllib.request.Request(
                    base + f"/v1/workspaces/{ws}/enter",
                    data=json.dumps({"user_id": user_id}).encode(),
                    headers={"Content-Type": "application/json", **auth}, method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=180) as response:
                        result = json.load(response)
                        assert response.status == 200, (ws, response.status)
                except urllib.error.HTTPError as error:
                    raise AssertionError(f"{ws} enter HTTP {error.code}: {error.read()[:600]!r}; log: {log_path}") from error
                url = result["url"]
                health = "/health" if ws in {"oficina", "ciencia"} else "/"
                try:
                    assert get(url + health)[0] == 200, ws
                except Exception as error:
                    raise AssertionError(f"{ws} did not serve {url + health}: {error}; log: {log_path}") from error
                if ws == "oficina":
                    config = json.loads((root / "data/workspaces/oficina/config/server.json").read_text())
                    req = urllib.request.Request(url + "/workspaces", headers={
                        "Authorization": "Bearer " + config["token"]})
                    with urllib.request.urlopen(req, timeout=10) as response:
                        assert response.status == 200
                print(f"PASS launch {attempt}: {ws}", flush=True)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="aleph-workspaces-clean-", dir="/tmp") as temp:
        root = Path(temp)
        launch(args.app, root, 1)
        launch(args.app, root, 2)
    print("PASS clean-profile 6/6 workspaces, first launch and relaunch")


if __name__ == "__main__":
    main()
