#!/usr/bin/env python3
"""First-run source check with only a caller-supplied synthetic data root.

Run in an env -i shell with isolated HOME, XDG_*, TMPDIR and ALEPH_DATA_DIR.
This probe never starts a workspace pack or reads a real browser/keychain profile.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "product" / "backend"))

EXPECTED_WORKSPACES = {"legal", "educacion", "ciencia", "diseno", "finanzas", "oficina"}


def main() -> int:
    issues: list[str] = []
    data = Path(os.environ["ALEPH_DATA_DIR"]).resolve()
    home = Path(os.environ["HOME"]).resolve()
    scratch = Path(os.environ["ALEPH_CLEAN_ROOT"]).resolve()
    assert scratch.name.startswith("aleph-clean-user.") and scratch.parent == Path("/tmp").resolve()
    assert data != home and data.is_relative_to(scratch) and home.is_relative_to(scratch)
    assert os.environ["ALEPH_ROLE"] == "client"
    for name in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "TMPDIR"):
        assert Path(os.environ[name]).resolve().is_relative_to(scratch)

    from app.main import app
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200 and health.json()["status"] == "ok", health.text[:300]
        for page in ("/Onboarding.dc.html", "/Cuarto.dc.html"):
            response = client.get(page)
            assert response.status_code == 200 and "text/html" in response.headers["content-type"], page
        workspaces = client.get("/v1/workspaces")
        assert workspaces.status_code == 200, workspaces.text[:300]
        ids = {item["id"] for item in workspaces.json()["workspaces"]}
        if ids != EXPECTED_WORKSPACES:
            issues.append(f"workspace rows missing: {sorted(EXPECTED_WORKSPACES - ids)}")

    database = data / "aleph.db"
    assert database.is_file()
    with sqlite3.connect(database) as conn:
        for table in ("users", "chats", "chat_messages", "keys", "conexiones", "modelos_estado", "puppets"):
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            assert count == 0, (table, count)

    forbidden_names = ("cookie", "profile", "session", "recent", "backup", "dump", "chat")
    for file in data.rglob("*"):
        if not file.is_file():
            continue
        assert not any(word in file.name.lower() for word in forbidden_names), file.name
        if file.suffix.lower() in (".json", ".txt", ".log", ".html", ".yaml", ".toml"):
            assert b"/Users/" not in file.read_bytes(), file.name

    if issues:
        print("FAIL isolated first-run: " + "; ".join(issues))
        return 1
    print("PASS isolated first-run: health, onboarding, workshop, six workspace rows, empty user tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
