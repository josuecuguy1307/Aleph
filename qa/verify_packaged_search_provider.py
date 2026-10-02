#!/usr/bin/env python3
"""Exercise the optional search-provider boundary in an isolated packaged app."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def request(base: str, path: str, *, method: str = "GET", body: dict | None = None,
            headers: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


class SearchHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/search?q=aleph-provider-check&format=json":
            self.send_error(404)
            return
        payload = b'{"query":"aleph-provider-check","results":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve()
    assert (app / "Contents/Resources/product/app/design/sala-v2/search-provider.js").is_file()
    with tempfile.TemporaryDirectory(prefix="aleph-packaged-search-", dir="/tmp") as temp:
        root = Path(temp)
        for name in ("home", "tmp", "config", "cache", "xdg-data", "state", "data"):
            (root / name).mkdir()
        with (root / "sidecar.log").open("w+") as log, \
                socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener, \
                ThreadingHTTPServer(("127.0.0.1", 0), SearchHandler) as search:
            listener.bind(("127.0.0.1", 0))
            listener.listen(8)
            port = listener.getsockname()[1]
            thread = threading.Thread(target=search.serve_forever, daemon=True)
            thread.start()
            env = {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"),
                "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_DATA_HOME": str(root / "xdg-data"), "XDG_STATE_HOME": str(root / "state"),
                "ALEPH_DATA_DIR": str(root / "data"), "PUPPET_DATA_DIR": str(root / "data"),
                "ALEPH_ROLE": "client", "PUPPET_PORT": str(port), "PORT": str(port),
            }
            capability = secrets.token_hex(32)
            proc = subprocess.Popen(
                [str(app / "Contents/MacOS/aleph_sidecar"), "--port", str(port),
                 "--listen-fd", str(listener.fileno()), "--launch-cap-stdin=1"],
                env=env, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                pass_fds=(listener.fileno(),), start_new_session=True,
            )
            assert proc.stdin is not None
            proc.stdin.write((capability + "\n").encode())
            proc.stdin.flush()
            base = f"http://127.0.0.1:{port}"
            try:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise AssertionError(f"sidecar exited {proc.returncode}; {log.name}: {log.read()[-1200:]}")
                    try:
                        with urllib.request.urlopen(base + "/health", timeout=2) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    time.sleep(0.25)
                else:
                    raise AssertionError(f"sidecar health timeout; {log.name}")
                status, local = request(base, "/v1/auth/local", method="POST", body={},
                                        headers={"X-Aleph-Launch": capability})
                assert status == 200, (status, local)
                auth = {"Authorization": "Bearer " + local["session_token"]}
                status, state = request(base, "/v1/sala/search-provider", headers=auth)
                assert status == 200 and state["configured"] is False, (status, state)
                for route in ("/v1/sala/buscar", "/v1/sala/investigar"):
                    status, response = request(base, route, method="POST", body={"query": "test"}, headers=auth)
                    assert status == 428 and response["detail"]["error"] == "search_provider_required", (route, status, response)
                    print(f"PASS {route} without provider: clean configuration response", flush=True)
                url = f"http://127.0.0.1:{search.server_port}"
                status, connected = request(base, "/v1/sala/search-provider", method="PUT",
                                            body={"url": url}, headers=auth)
                assert status == 200 and connected["configured"] is True, (status, connected)
                status, state = request(base, "/v1/sala/search-provider", headers=auth)
                assert status == 200 and state["configured"] is True and state["url"] == url, (status, state)
                print("PASS external SearXNG-compatible URL, validation and persistence", flush=True)
                status, disconnected = request(base, "/v1/sala/search-provider", method="DELETE", headers=auth)
                assert status == 200 and disconnected["configured"] is False, (status, disconnected)
                status, response = request(base, "/v1/sala/buscar", method="POST", body={"query": "test"}, headers=auth)
                assert status == 428 and response["detail"]["error"] == "search_provider_required"
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
                search.shutdown()
                thread.join(timeout=5)
    print("PASS packaged optional search-provider flow")


if __name__ == "__main__":
    main()
