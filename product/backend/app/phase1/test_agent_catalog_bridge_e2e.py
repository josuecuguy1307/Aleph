#!/usr/bin/env python3
"""test_agent_catalog_bridge_e2e.py — D3 · el PUENTE end-to-end (§9·E merge-blocker).

Cierra el hueco que el review adversarial marcó: NINGÚN test alimentaba la salida del exporter
por `belt_resolver.resolve_agent_ref`. Los slugs concuerdan HOY byte-a-byte, pero un drift
silencioso (exporter cambia el slug, o el resolver cambia el orden de candidatos) daría un
`AgentResolutionError` que NINGÚN test veía — el D3 bridge (todo su punto) sin cobertura e2e.

Este test construye un puppet row con la MISMA forma que `repo.create_puppet` devuelve
(`{id: <uuid>, config: {...}, ...}` — RETURNING *; JSONB vuelve como dict), corre el exporter
REAL a un `repo_root` TEMPORAL (jamás el catalog/agents real), y RESUELVE el archivo escrito por
`belt_resolver.resolve_agent_ref` — probando que el archivo exportado carga como receta hija v1
con su belt intacto. Además asserta la igualdad de slug exporter↔resolver (la biyección que NO
debe driftear).

    cd ${ALEPH_REPO_ROOT:?set repository root} && \
      python -m pytest product/backend/app/phase1/test_agent_catalog_bridge_e2e.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

# 'app.phase1...' (backend) + 'belt_resolver' (platform/assembler) en el path, tanto bajo pytest
# (desde el repo root) como en ejecución directa.
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]          # product/backend (paquete app)
_REPO = _HERE.parents[4]             # raíz del repo (pa-step3-fractal)
_ASSEMBLER = _REPO / "platform" / "assembler"
for p in (str(_BACKEND), str(_ASSEMBLER)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.phase1 import agent_catalog  # noqa: E402
import belt_resolver  # noqa: E402

_UUID = "33333333-3333-4333-8333-333333333333"


def _create_puppet_row(uuid: str = _UUID) -> dict:
    """La forma REAL que devuelve repo.create_puppet (RETURNING *): id server-minted + config como
    dict (psycopg2 deserializa el JSONB) + las columnas hermanas. schema_version 'v0' a propósito
    (default de la columna) para que el exporter lo tenga que normalizar a 'v1'."""
    return {
        "id": uuid,
        "owner_id": "44444444-4444-4444-8444-444444444444",
        "name": "Sub investigador",
        "nicho": "research",
        "version": 1,
        "recipe_schema_version": "v1",
        "status": "draft",
        "config": {
            "schema_version": "v0",  # ← default de la columna; el exporter DEBE normalizarlo
            "meta": {"name": "Sub investigador", "nicho": "research", "descripcion": "hijo delegable"},
            "model": {"primary": "openai/gpt-oss-120b", "temperature": 0, "max_tokens": 1024, "max_turns": 6},
            "belt": {"belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"],
                     "tool_filters": {"calc": ["add"]}},
            "framing": {"inline": "investigá y devolvé el dato"},
            "gates": {"send": "needs_ok"},
            # canvas = presentación pura; el exporter DEBE dropearla (no engorda la receta hija)
            "canvas": {"version": "v1", "blocks": [{"id": "t1", "atom": "tool", "gridX": 4, "gridY": 3}]},
        },
    }


def test_export_then_resolve_loads_child_recipe(tmp_path):
    """router→exporter→resolver end-to-end: el archivo que escribe el exporter RESUELVE por el
    candidato #3 del resolver (catalog/agents/<slug>.config.json) y carga como receta hija v1."""
    row = _create_puppet_row()

    # 1) EXPORT (lo que hace el side-effect del router tras create_puppet) → a un repo_root TEMPORAL
    dest = agent_catalog.export_agent(row, tmp_path)
    assert dest.exists() and dest.is_file()

    # 2) RESOLVE (lo que hace el runtime al entrar/delegar) — el MISMO agent_ref que el padre coloca
    agent_ref = agent_catalog.agent_ref_for(_UUID)
    assert agent_ref == "catalog/agents/agent-" + _UUID + ".config.json"
    resolved = belt_resolver.resolve_agent_ref(agent_ref, tmp_path)

    # 3) el archivo exportado carga como receta hija v1 con su belt intacto (la transform aplicada)
    assert resolved.slug == "agent-" + _UUID
    assert resolved.recipe_path == dest.resolve()
    assert resolved.recipe["schema_version"] == "v1"          # normalizado de v0 (killer #2)
    assert "canvas" not in resolved.recipe                    # presentación dropeada
    assert resolved.recipe["belt"]["belt_refs"] == ["platform/assembler/fixtures/belt-calc.mcp.json"]
    assert resolved.recipe["meta"]["name"] == "Sub investigador"


def test_slug_agreement_exporter_vs_resolver():
    """La biyección slug↔UUID↔path: el slug que produce el exporter (agent_catalog.slug_from_uuid)
    DEBE ser byte-idéntico al que deriva el resolver (belt_resolver._slug_from_agent_ref) del
    agent_ref. Si driftean, el runtime resolvería un archivo distinto (o ninguno) → asesino
    silencioso. Este assert falla el día que uno de los dos cambie sin el otro."""
    ref = agent_catalog.agent_ref_for(_UUID)
    assert agent_catalog.slug_from_uuid(_UUID) == belt_resolver._slug_from_agent_ref(ref)
    assert agent_catalog.slug_from_uuid(_UUID) == "agent-" + _UUID


def test_config_as_json_string_still_resolves(tmp_path):
    """robustez: si la capa DB entregara `config` como string JSON (no dict), el bridge e2e sigue
    resolviendo (el exporter parsea; el resolver carga)."""
    import json

    row = _create_puppet_row()
    row["config"] = json.dumps(row["config"])
    agent_catalog.export_agent(row, tmp_path)
    resolved = belt_resolver.resolve_agent_ref(agent_catalog.agent_ref_for(_UUID), tmp_path)
    assert resolved.recipe["schema_version"] == "v1"
    assert resolved.recipe["belt"]["belt_refs"] == ["platform/assembler/fixtures/belt-calc.mcp.json"]


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
