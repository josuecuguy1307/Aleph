"""Slice E regressions for Brandface resources and desktop icon cache behavior."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.phase1 import connectors_router, icons_router


ROOT = Path(__file__).resolve().parents[3]
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(icons_router.build_icons_router())
    app.include_router(connectors_router.build_connectors_router())
    return TestClient(app)


def _expected_known() -> list[str]:
    data = json.loads((ROOT / "catalog" / "brand_domains.json").read_text(encoding="utf-8"))
    out: list[str] = []
    for slug, entry in (data.get("domains") or {}).items():
        if entry.get("blocked"):
            continue
        out.append(slug)
        out.extend(entry.get("aliases") or [])
    return sorted(out)


def test_source_manifest_and_connector_catalog_align() -> None:
    client = _app()
    icons = client.get("/v1/icons")
    assert icons.status_code == 200, icons.text
    assert icons.json()["known"] == _expected_known()
    assert "xero" in icons.json()["known"]

    connectors = client.get("/v1/connectors")
    assert connectors.status_code == 200, connectors.text
    names = sorted(c["connector"] for c in connectors.json()["connectors"])
    assert connectors.json()["total"] == len(names) == len(list((ROOT / "catalog/connectors/onboarding").glob("*.json")))
    assert "xero" in names
    known = set(icons.json()["known"])
    assert [name for name in names if name not in known] == []


def test_bundled_icon_wins_over_runtime_cache_and_miss(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALEPH_ROLE", "client")
    monkeypatch.setenv("ALEPH_DATA_DIR", str(tmp_path / "aleph-data"))
    cache = icons_router._cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "xero.png").write_bytes(PNG)
    (cache / "xero.miss").touch()

    def fetch_should_not_run(domain: str, dest: Path) -> bool:
        raise AssertionError("bundled icon should win over runtime miss/fetch")

    monkeypatch.setattr(icons_router, "_fetch_favicon", fetch_should_not_run)
    client = _app()
    icon = client.get("/v1/icons/xero")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/png")
    assert icon.headers.get("x-aleph-icon-source") == "bundled"
    assert icon.content != PNG
    assert (cache / "xero.png").read_bytes() == PNG


def test_source_icon_cache_hit_miss_persistence_and_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALEPH_ROLE", "client")
    monkeypatch.setenv("ALEPH_DATA_DIR", str(tmp_path / "aleph-data"))
    monkeypatch.setattr(icons_router, "_BUNDLED_DIR", tmp_path / "no-bundled-icons")
    calls: list[tuple[str, Path]] = []

    def fetch_ok(domain: str, dest: Path) -> bool:
        calls.append((domain, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(PNG)
        return True

    monkeypatch.setattr(icons_router, "_fetch_favicon", fetch_ok)
    client = _app()
    first = client.get("/v1/icons/github")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("image/png")
    cache = icons_router._cache_dir().resolve()
    assert cache == (tmp_path / "aleph-data" / "brand_icons").resolve()
    assert ROOT.resolve() != cache and ROOT.resolve() not in cache.parents
    assert (cache / "github.png").read_bytes() == PNG
    assert len(calls) == 1

    def fetch_should_not_run(domain: str, dest: Path) -> bool:
        raise AssertionError("cache hit should survive router rebuilds")

    monkeypatch.setattr(icons_router, "_fetch_favicon", fetch_should_not_run)
    restarted = _app()
    second = restarted.get("/v1/icons/github")
    assert second.status_code == 200
    assert second.content == PNG

    failed_calls: list[str] = []

    def fetch_fail(domain: str, dest: Path) -> bool:
        failed_calls.append(domain)
        return False

    monkeypatch.setattr(icons_router, "_fetch_favicon", fetch_fail)
    miss = restarted.get("/v1/icons/xero")
    assert miss.status_code == 404
    assert miss.content == b""
    assert (cache / "xero.miss").exists()
    assert str(Path.home()) not in miss.text
    assert "SECRET" not in miss.text

    miss_again = restarted.get("/v1/icons/xero")
    assert miss_again.status_code == 404
    assert failed_calls == ["www.xero.com"]


def test_frozen_manifest_catalog_and_cache_live_outside_meipass(tmp_path: Path) -> None:
    probe = r"""
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["ALEPH_TEST_ROOT"]).resolve()
data = Path(os.environ["ALEPH_DATA_DIR"]).resolve()
sys.frozen = True
sys._MEIPASS = str(root)
sys.path.insert(0, str(root / "product" / "backend"))
sys.path.insert(0, str(root / "platform"))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.phase1 import connectors_router, icons_router

PNG = b"brandface-png"
def fake_fetch(domain, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(PNG)
    return True

icons_router._fetch_favicon = fake_fetch
app = FastAPI()
app.include_router(icons_router.build_icons_router())
app.include_router(connectors_router.build_connectors_router())
client = TestClient(app)

icons = client.get("/v1/icons")
assert icons.status_code == 200, icons.text
assert "xero" in icons.json()["known"]
connectors = client.get("/v1/connectors")
assert connectors.status_code == 200, connectors.text
assert any(c.get("connector") == "xero" for c in connectors.json()["connectors"])

icon = client.get("/v1/icons/xero")
assert icon.status_code == 200, icon.text
assert icon.headers.get("x-aleph-icon-source") == "bundled"
cache = icons_router._cache_dir().resolve()
assert cache == data / "brand_icons"
assert root != cache and root not in cache.parents

icons_router._BUNDLED_DIR = root / "catalog" / "brand_icons-not-present"
icon = client.get("/v1/icons/xero")
assert icon.status_code == 200, icon.text
assert icon.headers.get("x-aleph-icon-source") == "cache"
assert (cache / "xero.png").read_bytes() == PNG

bad = client.get("/v1/icons/unknown-brandface-service")
assert bad.status_code == 404
assert str(root) not in bad.text
assert str(data) not in bad.text
print(json.dumps({"known": len(icons.json()["known"]), "connectors": connectors.json()["total"], "cache": str(cache)}))
"""
    env = os.environ.copy()
    env.update({
        "ALEPH_TEST_ROOT": str(ROOT),
        "ALEPH_ROLE": "client",
        "ALEPH_DATA_DIR": str(tmp_path / "aleph-data"),
    })
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert '"connectors": 28' in proc.stdout
