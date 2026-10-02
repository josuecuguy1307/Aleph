#!/usr/bin/env python3
"""Exercise the newly built macOS sidecar with an isolated synthetic user."""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


EXPECTED = {"legal", "educacion", "ciencia", "diseno", "finanzas", "oficina"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=4) as response:
        body = response.read()
        return response.status, response.headers.get("Content-Type", ""), body


def one_launch(binary: Path, root: Path) -> None:
    port = free_port()
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
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
    proc = subprocess.Popen(
        [str(binary), "--port", str(port)], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise AssertionError(f"sidecar exited before health: {proc.returncode}")
            try:
                code, _, body = request(port, "/health")
                if code == 200 and json.loads(body).get("status") == "ok":
                    break
            except Exception:
                time.sleep(0.25)
        else:
            raise AssertionError("sidecar health timeout")
        for path in ("/Onboarding.dc.html", "/Cuarto.dc.html"):
            code, content_type, _ = request(port, path)
            assert code == 200 and "text/html" in content_type, path
        code, _, body = request(port, "/v1/workspaces")
        assert code == 200
        found = {item["id"] for item in json.loads(body)["workspaces"]}
        assert found == EXPECTED, ("workspaces", found)
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
    binary = args.app / "Contents/MacOS/aleph_sidecar"
    assert binary.is_file(), binary
    with tempfile.TemporaryDirectory(prefix="aleph-clean-user.", dir="/tmp") as tmp:
        root = Path(tmp)
        one_launch(binary, root)
        one_launch(binary, root)
        database = root / "data/aleph.db"
        assert database.is_file(), database
        with sqlite3.connect(database) as conn:
            for table in ("users", "chats", "chat_messages", "keys", "conexiones", "modelos_estado", "puppets"):
                assert conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0, table
        print("PASS clean-user bundle: two launches, health, onboarding, Workshop, 6/6 workspaces, empty user state")


if __name__ == "__main__":
    main()
