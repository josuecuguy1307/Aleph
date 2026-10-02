#!/usr/bin/env python3
"""
test_reclassify_kind.py — RECLASIFICAR (op 3 del MD de memoria): PATCH meta.kind
skill↔episodica en la memoria de AGENTE (A3), con la matriz ANTI-IDOR completa.

Qué prueba (contra la app real + DB real vía TestClient; usuarios/puppet efímeros
creados por repo y borrados al final):
  1. owner reclasifica episodica→skill: 200, meta.kind cambia, content/prov INTACTOS;
  2. el GET del panel refleja el kind nuevo (lo que se ve = lo que hay);
  3. vuelta skill→episodica: 200 (la frontera se corrige las veces que haga falta);
  4. kind inválido → 422 (invalid_kind) y NO muta;
  5. body vacío {} → 422 (nada que cambiar);
  6. content + kind JUNTOS → ambos aplican en un solo PATCH;
  7. ANTI-IDOR: sin sesión → 401 · sesión de OTRO usuario → 403 · memoria bajo el
     puppet equivocado → 404 · id inexistente → 404 (ajeno == inexistente, sin oráculo);
     y tras cada intento hostil el kind NO cambió.

    cd product/backend && ./.venv/bin/python -m pytest app/phase1/test_reclassify_kind.py -q
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.phase1 import repo

client = TestClient(app)


@pytest.fixture(scope="module")
def world():
    """Dos usuarios reales + un puppet de A con UNA memoria etiquetada episodica."""
    conn = repo.get_conn()
    tag = uuid.uuid4().hex[:8]
    ua = repo.register_user(conn, f"reclass-a-{tag}@test.local", "pw-reclass-123")
    ub = repo.register_user(conn, f"reclass-b-{tag}@test.local", "pw-reclass-123")
    pup = repo.create_puppet(conn, owner_id=str(ua["id"]), name=f"reclass-{tag}",
                             nicho="test", config={})
    mem = repo.add_memory(conn, puppet_id=str(pup["id"]), content="aprendió a usar la API X",
                          source="agent", meta={"kind": "episodica", "provenance": "hecho"})
    w = {"conn": conn, "ua": ua, "ub": ub, "pup": pup, "mem": mem,
         "tok_a": repo.mint_session(str(ua["id"])), "tok_b": repo.mint_session(str(ub["id"]))}
    yield w
    # limpieza: la memoria, el puppet y los dos usuarios efímeros (cero basura en la DB)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM agent_memories WHERE puppet_id = %s", (str(pup["id"]),))
        cur.execute("DELETE FROM puppets WHERE id = %s", (str(pup["id"]),))
        cur.execute("DELETE FROM users WHERE id IN (%s, %s)", (str(ua["id"]), str(ub["id"])))
    conn.commit()
    conn.close()


def _url(w, mid=None):
    pid = w["pup"]["id"]
    return f"/v1/puppets/{pid}/memories" + (f"/{mid or w['mem']['id']}" if mid is not False else "")


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _kind(w):
    m = repo.get_memory(w["conn"], str(w["mem"]["id"]))
    return ((m or {}).get("meta") or {}).get("kind")


def test_owner_reclasifica_a_skill(world):
    r = client.patch(_url(world), json={"kind": "skill"}, headers=_hdr(world["tok_a"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d.get("meta") or {}).get("kind") == "skill"
    assert d.get("content") == "aprendió a usar la API X"          # el contenido no se toca
    assert (d.get("meta") or {}).get("provenance") == "hecho"       # la procedencia tampoco


def test_get_refleja_kind_nuevo(world):
    r = client.get(_url(world, mid=False), headers=_hdr(world["tok_a"]))
    assert r.status_code == 200
    row = [m for m in r.json()["memories"] if str(m["id"]) == str(world["mem"]["id"])][0]
    assert (row.get("meta") or {}).get("kind") == "skill"


def test_vuelta_a_episodica(world):
    r = client.patch(_url(world), json={"kind": "episodica"}, headers=_hdr(world["tok_a"]))
    assert r.status_code == 200 and (r.json().get("meta") or {}).get("kind") == "episodica"


def test_kind_invalido_422_y_no_muta(world):
    before = _kind(world)
    r = client.patch(_url(world), json={"kind": "confidencial"}, headers=_hdr(world["tok_a"]))
    assert r.status_code == 422
    assert _kind(world) == before


def test_body_vacio_422(world):
    assert client.patch(_url(world), json={}, headers=_hdr(world["tok_a"])).status_code == 422


def test_content_y_kind_juntos(world):
    r = client.patch(_url(world), json={"content": "domina la API X", "kind": "skill"},
                     headers=_hdr(world["tok_a"]))
    assert r.status_code == 200
    d = r.json()
    assert d["content"] == "domina la API X" and (d.get("meta") or {}).get("kind") == "skill"


def test_anti_idor(world):
    before = _kind(world)
    # sin sesión → 401
    assert client.patch(_url(world), json={"kind": "episodica"}).status_code == 401
    # sesión de OTRO usuario → 403 (la cuenta no es suya)
    assert client.patch(_url(world), json={"kind": "episodica"},
                        headers=_hdr(world["tok_b"])).status_code == 403
    # la memoria bajo un puppet EQUIVOCADO → 404 (ajeno == inexistente, sin oráculo)
    pid_b = repo.create_puppet(world["conn"], owner_id=str(world["ub"]["id"]),
                               name="reclass-b", nicho="test", config={})
    r = client.patch(f"/v1/puppets/{pid_b['id']}/memories/{world['mem']['id']}",
                     json={"kind": "episodica"}, headers=_hdr(world["tok_b"]))
    assert r.status_code == 404
    with world["conn"].cursor() as cur:                               # limpieza del puppet auxiliar
        cur.execute("DELETE FROM puppets WHERE id = %s", (str(pid_b["id"]),))
    world["conn"].commit()
    # id inexistente → 404
    assert client.patch(_url(world, mid=str(uuid.uuid4())), json={"kind": "episodica"},
                        headers=_hdr(world["tok_a"])).status_code == 404
    # tras TODOS los intentos hostiles, el kind sigue igual
    assert _kind(world) == before
