"""test_config_lock_sqlite.py — [Casa 2 · 2.4] equip/unequip/PUT-config en SQLite.

Los tres endpoints que serializan el read-modify-write del config de un puppet usaban
`pg_advisory_xact_lock`, que en SQLite NO existe (el traductor no lo caza → revienta en
ejecución). Dos crasheaban (equip_method, unequip_method); el tercero
(update_puppet_config) lo TRAGABA en un `except: pass` → el PUT quedaba sin serializar,
que es justo el clobber que el lock existe para evitar.

El fix ramifica por rol: control sigue con el advisory lock (byte-idéntico), cliente toma
el write lock con BEGIN IMMEDIATE (ver methods_router._lock_config). Se prueba el EFECTO
—los endpoints responden 201/200 contra un SQLite real, vía el router REAL + TestClient
(cero mocks de lógica)— y que el config editado persiste. El rojo sin fix está en
`test_*_sin_fix_*` más abajo, forzando el path de control en cliente.

Contra un SQLite real. El proceso queda en rol cliente por el fixture.
"""
from __future__ import annotations

import os
import threading

import pytest

_RECIPE = {
    "schema_version": "v1",
    "meta": {"name": "agente-lock-test", "nicho": "general"},
    "model": {"primary": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1",
              "temperature": 0, "max_tokens": 1024, "max_turns": 6},
    "belt": {"belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"],
             "tool_filters": {"calc": ["add"]}},
    "framing": {"inline": "agente de prueba"},
    "rag": {"enabled": False},
    "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
}

_METHOD = {"name": "Earnings", "phases": ["Investigar"],
           "steps": [{"text": "Bajar el 10-Q", "phase": "Investigar"}]}


def _reset_dbmod():
    from app.phase1 import repo
    repo._db = None


@pytest.fixture
def app_cliente(tmp_path):
    """App REAL (methods_router + phase1_router) en rol cliente sobre SQLite."""
    previo = {k: os.environ.get(k) for k in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH")}
    ruta = str(tmp_path / "lock.db")
    os.environ["ALEPH_ROLE"] = "client"
    os.environ["PUPPET_SQLITE_PATH"] = ruta
    _reset_dbmod()

    from app.phase1 import repo
    sq = repo._dbmod()._sqlite()
    c = sq.conectar(ruta)
    sq.crear_schema(c)
    c.commit()
    c.close()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.methods_router import build_methods_router
    from app.phase1.router import build_phase1_router

    app = FastAPI()
    app.include_router(build_methods_router(get_conn=repo.get_conn,
                                            events_dir=lambda: tmp_path))
    app.include_router(build_phase1_router(get_conn=repo.get_conn,
                                           events_dir=lambda: tmp_path))
    client = TestClient(app, raise_server_exceptions=False)

    conn = repo.get_conn()
    u = repo.register_user(conn, "lock@test.local", "pw-lock-1234")
    puppet = repo.create_puppet(conn, owner_id=str(u["id"]), name="agente-lock-test",
                                nicho="general", config=_RECIPE)
    from app.phase1 import methods_repo as mr
    method = mr.create_method(conn, user_id=str(u["id"]), method=_METHOD)
    conn.close()

    ctx = {"client": client, "pid": str(puppet["id"]), "mid": str(method["id"]),
           "auth": {"Authorization": "Bearer " + repo.mint_session(str(u["id"]))},
           "ruta": ruta}
    yield ctx

    for k, v in previo.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    _reset_dbmod()


def test_equip_method_en_cliente(app_cliente):
    """POST equipar: sin el fix moría con `no such function: pg_advisory_xact_lock`."""
    c, pid, mid, auth = (app_cliente[k] for k in ("client", "pid", "mid", "auth"))
    r = c.post(f"/v1/puppets/{pid}/methods", json={"method_id": mid}, headers=auth)
    assert r.status_code == 201, f"equip devolvió {r.status_code}: {r.text}"
    assert mid in r.json().get("equipped", []), r.json()


def test_unequip_method_en_cliente(app_cliente):
    """DELETE desequipar: mismo lock, misma cura."""
    c, pid, mid, auth = (app_cliente[k] for k in ("client", "pid", "mid", "auth"))
    c.post(f"/v1/puppets/{pid}/methods", json={"method_id": mid}, headers=auth)
    r = c.delete(f"/v1/puppets/{pid}/methods/{mid}", headers=auth)
    assert r.status_code == 200, f"unequip devolvió {r.status_code}: {r.text}"
    assert mid not in r.json().get("equipped", []), r.json()


def test_put_config_en_cliente(app_cliente):
    """PUT /config: el advisory tragado dejaba el PUT sin serializar; ahora BEGIN
    IMMEDIATE. El PUT edita la receta y sube version."""
    c, pid, auth = (app_cliente[k] for k in ("client", "pid", "auth"))
    nueva = dict(_RECIPE)
    nueva["meta"] = {"name": "renombrado", "nicho": "general"}
    r = c.put(f"/v1/puppets/{pid}/config", json={"config": nueva}, headers=auth)
    assert r.status_code == 200, f"PUT config devolvió {r.status_code}: {r.text}"
    assert r.json()["config"]["meta"]["name"] == "renombrado"


def test_equip_es_referencia_no_copia_en_cliente(app_cliente):
    """El candado §9 vale también en SQLite: equipar escribe belt.method_refs[], no el
    objeto method; y persiste tras releer (roundtrip JSON de la columna config)."""
    from app.phase1 import repo
    c, pid, mid, auth = (app_cliente[k] for k in ("client", "pid", "mid", "auth"))
    c.post(f"/v1/puppets/{pid}/methods", json={"method_id": mid}, headers=auth)

    conn = repo.get_conn(app_cliente["ruta"])
    cfg = repo.get_puppet(conn, pid)["config"]
    conn.close()
    assert cfg["belt"].get("method_refs") == [mid], f"la ref no persistió: {cfg['belt']}"


# ── EL ROJO: sin el fix (path de control en cliente) los endpoints crashean ──────

def test_lock_config_crashea_sin_fix_en_cliente(app_cliente, monkeypatch):
    """Ancla el defecto: forzando el path de control (advisory lock) en cliente, equipar
    revienta con `no such function`. Es lo que pasaba antes del 2.4."""
    import app.phase1.methods_router as mrt
    # simula "no soy cliente" SOLO para el lock → toma la rama pg_advisory_xact_lock
    monkeypatch.setattr(mrt, "_es_cliente", lambda: False)
    c, pid, mid, auth = (app_cliente[k] for k in ("client", "pid", "mid", "auth"))
    r = c.post(f"/v1/puppets/{pid}/methods", json={"method_id": mid}, headers=auth)
    assert r.status_code == 500, \
        f"esperaba el crash del advisory lock, salió {r.status_code}: {r.text[:120]}"


def test_equips_concurrentes_no_se_pisan(app_cliente):
    """POR QUÉ existe el lock (no sólo que no crashee): dos equips concurrentes de
    métodos DISTINTOS sobre el MISMO puppet hacen read-modify-write del config. Sin
    serializar, el segundo write pisa la ref del primero (last-write-wins). Con BEGIN
    IMMEDIATE los dos quedan. Es el valor real del fix, sobre todo para el PUT que antes
    tragaba el lock."""
    from app.phase1 import repo
    from app.phase1 import methods_repo as mr
    c, pid, auth, ruta = (app_cliente[k] for k in ("client", "pid", "auth", "ruta"))

    # un segundo método para equipar en paralelo con el de la fixture
    conn = repo.get_conn(ruta)
    m2 = mr.create_method(conn, user_id=repo.puppet_owner(conn, pid),
                          method={"name": "Otro", "phases": ["P"],
                                  "steps": [{"text": "x", "phase": "P"}]})
    conn.close()
    ids = [app_cliente["mid"], str(m2["id"])]

    codes, lock = [], threading.Lock()
    barrera = threading.Barrier(2)

    def equipar(method_id):
        barrera.wait()
        r = c.post(f"/v1/puppets/{pid}/methods", json={"method_id": method_id}, headers=auth)
        with lock:
            codes.append(r.status_code)

    hs = [threading.Thread(target=equipar, args=(m,)) for m in ids]
    for h in hs:
        h.start()
    for h in hs:
        h.join(timeout=60)

    assert all(x == 201 for x in codes), f"algún equip falló: {codes}"
    conn = repo.get_conn(ruta)
    refs = (repo.get_puppet(conn, pid)["config"]["belt"].get("method_refs") or [])
    conn.close()
    assert set(refs) == set(ids), \
        f"CLOBBER: se perdió una ref por la carrera read-modify-write. refs={refs}, esperadas={ids}"
