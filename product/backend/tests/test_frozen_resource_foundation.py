"""Regresión de la fundación frozen que consumen las superficies de Caso 3.

La sonda corre en un subproceso para que `sys.frozen`/`sys._MEIPASS` y los caches de
módulo no contaminen el resto de pytest. No usa red ni una DB: valida que el bundle
encuentre sus recursos inmutables y que sus escrituras apunten al datadir persistente.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

_PROBE = r"""
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
from app.phase1 import belts_router, connectors_router, icons_router, router

app = FastAPI()
app.include_router(icons_router.build_icons_router())
app.include_router(connectors_router.build_connectors_router())
app.include_router(belts_router.build_belts_router())
app.include_router(router.build_phase1_router(
    get_conn=lambda: (_ for _ in ()).throw(RuntimeError("DB no disponible en sonda")),
    events_dir=lambda: data / "espacios",
))
client = TestClient(app)

expected_map = json.loads((root / "catalog" / "brand_domains.json").read_text())
expected_known = []
for slug, entry in (expected_map.get("domains") or {}).items():
    if not entry.get("blocked"):
        expected_known.append(slug)
        expected_known.extend(entry.get("aliases") or [])
icons = client.get("/v1/icons")
assert icons.status_code == 200, icons.text
assert icons.json()["known"] == sorted(expected_known)

connectors = client.get("/v1/connectors")
expected_connectors = len(list((root / "catalog/connectors/onboarding").glob("*.json")))
assert connectors.status_code == 200, connectors.text
assert connectors.json()["total"] == expected_connectors
assert expected_connectors > 0

belt = client.get("/v1/belts/cards", params={
    "ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json"
})
assert belt.status_code == 200, belt.text
assert belt.json()["total"] == 3
assert belt.json()["dropped"] == []

brains = client.get("/v1/brains/status")
assert brains.status_code == 200, brains.text
assert "error" not in brains.json(), brains.json()
_prov = set(brains.json()["providers"])
_cat = {c["provider_id"] for c in (brains.json().get("catalog") or [])}
assert "included" in _prov
assert _prov - {"included"} == _cat
assert brains.json()["providers"]["included"]["state"] in {"ready", "not_configured", "unknown"}
assert brains.json()["service"]["state"] in {"ready", "unavailable"}
assert brains.json()["service"]["mode"] in {"managed", "shared", "not_started", "failed", "stopped"}

cache = icons_router._cache_dir().resolve()
assert cache == data / "brand_icons"
assert root != cache and root not in cache.parents

from app.phase1 import executor, stream_chat
assert stream_chat._REPO == root
assert stream_chat._ASM_DIR == root / "platform" / "assembler"
assert callable(stream_chat._asm().assemble_and_run)
assert executor._RESOURCE_ROOT == root
assert executor._RUN_OUTPUTS_ROOT.resolve() == data / "run_outputs"
assert callable(executor._asm().assemble_and_run)
print(json.dumps({
    "icons": len(icons.json()["known"]),
    "connectors": connectors.json()["total"],
    "belt_cards": belt.json()["total"],
    "brains": sorted(brains.json()["providers"]),
    "cache": str(cache),
}))
"""

_DIRECT_ASSEMBLER_PROBE = r"""
import os
import sys
from pathlib import Path

root = Path(os.environ["ALEPH_TEST_ROOT"]).resolve()
sys.frozen = True
sys._MEIPASS = str(root)
sys.path.insert(0, str(root / "platform" / "assembler"))
sys.path.insert(0, str(root / "product" / "backend"))

import recipe_assembler

assert callable(recipe_assembler.assemble_and_run)
"""


def test_frozen_resources_and_writable_data_are_separated(tmp_path: Path) -> None:
    data = tmp_path / "aleph-data"
    env = os.environ.copy()
    env.update({
        "ALEPH_TEST_ROOT": str(ROOT),
        "ALEPH_ROLE": "client",
        "ALEPH_DATA_DIR": str(data),
        # La sonda prueba import/ejecución del detector, no espera 20 s por cada CLI.
        "PUPPET_CLI_BRAIN_DETECT_TIMEOUT": "2",
        "PUPPET_CLI_BRAIN_DETECT_TTL": "0",
    })
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert '"connectors": 28' in proc.stdout


def test_recipe_assembler_direct_import_finds_frozen_path_helper(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update({
        "ALEPH_TEST_ROOT": str(ROOT),
        "ALEPH_ROLE": "client",
        "ALEPH_DATA_DIR": str(tmp_path / "aleph-data"),
    })
    proc = subprocess.run(
        [sys.executable, "-c", _DIRECT_ASSEMBLER_PROBE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
