"""test_consolidate_sqlite.py — [Casa 2 · Fase 2 · 2.4] memory_consolidate en SQLite.

`memory_consolidate.consolidate_agent` es uno de los dos sitios donde el árbol usaba
`jsonb_set` (el otro es `repo.reclassify_memory`, cubierto por `test_reclassify_kind`).
El dialecto RECHAZA `jsonb_set` —en SQLite devuelve JSONB binario, no texto—, así que el
paso 2.4 lo bifurca por rol a `json_set`. Sin ese arreglo, la rama de degradación-a-meta
moría con `DialectoNoSoportado` la primera vez que consolidaba en el cliente.

Este test corre la función REAL contra un SQLite real (sin mocks) y verifica el EFECTO de
las dos ramas: que funde los near-dups (DELETE ... ANY) y que etiqueta kind='meta' en la
columna JSON (json_set) — y que ese tag vuelve como dict, no como str, o sea que el
roundtrip de la columna JSON también quedó bien.

Correr:  ALEPH_ROLE=client PUPPET_SQLITE_PATH=... pytest app/phase1/test_consolidate_sqlite.py
o vía la suite normal, que ya deja el proceso en rol cliente por el conftest de abajo.
"""
from __future__ import annotations

import os

import pytest


def _reset_dbmod():
    """Fuerza a repo a reconstruir su capa DB cacheada tras cambiar ALEPH_ROLE."""
    from app.phase1 import repo
    repo._db = None                # el cache perezoso de _dbmod() (repo.py)


@pytest.fixture
def cliente(tmp_path):
    """Proceso en rol cliente, .db limpio con el schema real. Restaura el entorno.

    Va por `repo._dbmod()` —que carga la capa DB por ruta— en vez de importar `sqlite_db`
    directo: bajo la colección de pytest los `sys.path.insert` del import-time no siempre
    quedan. Es además el camino REAL por el que el backend resuelve el rol."""
    previo = {k: os.environ.get(k) for k in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH")}
    ruta = str(tmp_path / "consolidate.db")
    os.environ["ALEPH_ROLE"] = "client"
    os.environ["PUPPET_SQLITE_PATH"] = ruta
    _reset_dbmod()

    from app.phase1 import repo
    sqlite_db = repo._dbmod()._sqlite()
    c = sqlite_db.conectar(ruta)
    sqlite_db.crear_schema(c)
    c.commit()
    c.close()
    yield ruta

    for k, v in previo.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    _reset_dbmod()


def _puppet(conn, repo):
    u = repo.register_user(conn, "consol@test.local", "pw-consolidate-123")
    p = repo.create_puppet(conn, owner_id=str(u["id"]), name="consol",
                           nicho="finanzas", config={"meta": {"nicho": "finanzas"}})
    return str(p["id"])


def test_consolidate_funde_dups_y_degrada_meta_en_sqlite(cliente):
    """Las DOS ramas que tocan agent_memories: DELETE ... ANY (fusión) y json_set
    (degradar a meta). Sin el 2.4, la segunda moría con DialectoNoSoportado."""
    from app.phase1 import repo
    from app.phase1 import memory_consolidate as mc

    conn = repo.get_conn(cliente)
    pid = _puppet(conn, repo)

    # (a) dos near-dups: mismo hecho de dominio, casi las mismas palabras salientes → uno
    #     se funde (se borra el más viejo).
    repo.add_memory(conn, puppet_id=pid,
                    content="la API de Stripe usa la clave secreta en el header Authorization")
    repo.add_memory(conn, puppet_id=pid,
                    content="la API de Stripe usa la clave secreta en el header Authorization Bearer")
    # (b) una meta REAL (≥2 marcadores: 'prefiere', 'honesto', 'directo') → se etiqueta meta.
    m_meta = repo.add_memory(conn, puppet_id=pid,
                             content="el usuario prefiere un tono honesto y directo, sin inventar")
    # (c) un hecho de dominio suelto que NO se toca.
    repo.add_memory(conn, puppet_id=pid,
                    content="el cierre contable del cliente es el día 5 de cada mes")

    antes = repo.list_memories(conn, pid)
    assert len(antes) == 4

    stats = mc.consolidate_agent(conn, pid)

    assert stats["fused"] >= 1, f"no fundió near-dups: {stats}"
    assert stats["meta_degraded"] >= 1, f"no degradó la meta: {stats}"

    # EL EFECTO de json_set: la meta quedó tagueada kind='meta', y vuelve como DICT.
    m = repo.get_memory(conn, str(m_meta["id"]))
    assert m is not None, "la meta no debería haberse borrado"
    assert isinstance(m["meta"], dict), f"meta volvió {type(m['meta']).__name__}, no dict"
    assert m["meta"].get("kind") == "meta", f"json_set no fijó kind: {m['meta']}"

    # idempotente: correrlo de nuevo no vuelve a fundir ni a degradar.
    stats2 = mc.consolidate_agent(conn, pid)
    assert stats2["fused"] == 0 and stats2["meta_degraded"] == 0, \
        f"no es idempotente: {stats2}"

    conn.close()


def test_consolidate_dry_run_no_escribe(cliente):
    """dry_run no debe tocar la base — ni siquiera abrir la rama de json_set."""
    from app.phase1 import repo
    from app.phase1 import memory_consolidate as mc

    conn = repo.get_conn(cliente)
    pid = _puppet(conn, repo)
    repo.add_memory(conn, puppet_id=pid,
                    content="el usuario prefiere un tono honesto y directo, sin inventar")

    stats = mc.consolidate_agent(conn, pid, dry_run=True)
    assert stats["meta_degraded"] >= 1     # lo CALCULA…

    m = repo.list_memories(conn, pid)[0]   # …pero NO lo escribió
    assert (m.get("meta") or {}).get("kind") != "meta", "dry_run escribió igual"
    conn.close()
