#!/usr/bin/env python3
"""test_agent_catalog.py — unit del EXPORTER (D3 · el puente UUID→agent_ref).

Corre SIN DB/red: llama ``agent_catalog.export_agent(row, tmp_repo_root)`` y verifica el
ARCHIVO real en un tmp_path (JAMÁS toca el catalog/agents/ real). Cubre los asesinos
silenciosos del recon: schema_version='v1' FORZADO (killer #2), canvas DROPEADO, slug del
UUID y no del nombre (killer #3), idempotencia (killer #1), belt/meta/model VERBATIM.

    cd ${ALEPH_REPO_ROOT:?set repository root} && python -m pytest product/backend/app/phase1/test_agent_catalog.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# permitir 'app.phase1...' tanto bajo pytest (desde el repo root) como ejecución directa
_BACKEND = Path(__file__).resolve().parents[2]  # product/backend (donde vive el paquete app)
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import agent_catalog  # noqa: E402

_UUID_A = "11111111-1111-4111-8111-111111111111"
_UUID_B = "22222222-2222-4222-8222-222222222222"


def _config(name: str = "Mi agente") -> dict:
    """Config como la persiste el Cuarto: schema_version 'v0' (default de la columna, que el
    exporter DEBE normalizar) + un bloque `canvas` (presentación, que el exporter DEBE dropear)."""
    return {
        "schema_version": "v0",  # ← default de la columna; el exporter lo normaliza a 'v1'
        "meta": {"name": name, "nicho": "research", "descripcion": "sub-agente equipable"},
        "model": {"primary": "openai/gpt-oss-120b", "temperature": 0, "max_tokens": 1024, "max_turns": 6},
        "belt": {"belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"], "tool_filters": {"calc": ["add"]}},
        "framing": {"inline": "computá y devolvé el dato"},
        "rag": {"enabled": False},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
        "canvas": {"version": "v1", "blocks": [{"id": "t1", "atom": "tool", "gridX": 4, "gridY": 3}],
                   "nucleos": [{"id": "nucleo", "model": "equilibrado"}], "layout": [{"id": "t1", "gridX": 4, "gridY": 3}]},
    }


def _dest(tmp_path: Path, uuid: str) -> Path:
    return tmp_path / "catalog" / "agents" / f"agent-{uuid}.config.json"


def test_export_writes_uuid_keyed_file(tmp_path):
    row = {"id": _UUID_A, "config": _config()}
    dest = agent_catalog.export_agent(row, tmp_path)
    assert dest == _dest(tmp_path, _UUID_A)
    assert dest.exists() and dest.is_file()


def test_schema_version_forced_v1(tmp_path):
    # killer #2: v0/faltante → hijo NO-resoluble; el exporter FUERZA 'v1'
    dest = agent_catalog.export_agent({"id": _UUID_A, "config": _config()}, tmp_path)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["schema_version"] == "v1"


def test_canvas_key_absent(tmp_path):
    dest = agent_catalog.export_agent({"id": _UUID_A, "config": _config()}, tmp_path)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert "canvas" not in data


def test_belt_meta_model_preserved_verbatim(tmp_path):
    cfg = _config()
    dest = agent_catalog.export_agent({"id": _UUID_A, "config": cfg}, tmp_path)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["belt"] == cfg["belt"]
    assert data["meta"] == cfg["meta"]
    assert data["model"] == cfg["model"]
    assert data["framing"] == cfg["framing"]
    assert data["rag"] == cfg["rag"]
    assert data["gates"] == cfg["gates"]


def test_idempotent_same_file_no_error(tmp_path):
    # killer #1: re-exportar en create Y update → mismo archivo, sin error, byte-idéntico
    row = {"id": _UUID_A, "config": _config()}
    d1 = agent_catalog.export_agent(row, tmp_path)
    bytes1 = d1.read_bytes()
    d2 = agent_catalog.export_agent(row, tmp_path)  # segunda vez: no tira, mismo path
    assert d1 == d2
    assert d2.read_bytes() == bytes1


def test_slug_from_uuid_not_name(tmp_path):
    # killer #3: dos configs con el MISMO meta.name pero UUID distinto → DOS archivos distintos
    agent_catalog.export_agent({"id": _UUID_A, "config": _config("My agent")}, tmp_path)
    agent_catalog.export_agent({"id": _UUID_B, "config": _config("My agent")}, tmp_path)
    d = tmp_path / "catalog" / "agents"
    files = sorted(p.name for p in d.glob("agent-*.config.json"))
    assert files == [f"agent-{_UUID_A}.config.json", f"agent-{_UUID_B}.config.json"]
    # y NO se pisaron: cada archivo conserva su propia identidad (mismo name, distinto UUID)
    assert _dest(tmp_path, _UUID_A).exists() and _dest(tmp_path, _UUID_B).exists()


def test_config_as_json_string_is_parsed(tmp_path):
    # robustez: si la capa DB entregara `config` como string JSON, el exporter lo parsea
    row = {"id": _UUID_A, "config": json.dumps(_config())}
    dest = agent_catalog.export_agent(row, tmp_path)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["schema_version"] == "v1"
    assert "canvas" not in data
    assert data["belt"]["belt_refs"] == ["platform/assembler/fixtures/belt-calc.mcp.json"]


def test_agent_ref_matches_exported_path(tmp_path):
    # el agent_ref que el padre coloca DEBE ser el path del archivo exportado (round-trip por candidato #3)
    dest = agent_catalog.export_agent({"id": _UUID_A, "config": _config()}, tmp_path)
    ref = agent_catalog.agent_ref_for(_UUID_A)
    assert ref == "catalog/agents/agent-" + _UUID_A + ".config.json"
    assert (tmp_path / ref) == dest


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
