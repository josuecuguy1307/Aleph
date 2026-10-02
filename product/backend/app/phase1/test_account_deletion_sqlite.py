"""test_account_deletion_sqlite.py — [Casa 2 · 2.4] purge_user corre en SQLite (cliente).

Defecto #3 del barrido: `SELECT ... FROM information_schema.tables` es de Postgres; en
SQLite el catálogo es `sqlite_master`. El traductor NO lo caza (no está en _NO_TRADUCIBLE):
pasaba y reventaba en EJECUCIÓN con `no such table: information_schema.tables`, abortando
el borrado de cuenta ENTERO en el cliente. El fix ramifica por rol (control sigue en
information_schema; cliente usa sqlite_master → las billing_* no existen → lista vacía →
el loop de DELETE se saltea). En rojo (sin fix): purge_user levanta OperationalError antes
de borrar nada.

Contra un SQLite real, sin mocks. El proceso queda en rol cliente por el fixture.
"""
from __future__ import annotations

import os

import pytest


def _reset_dbmod():
    from app.phase1 import repo
    repo._db = None


@pytest.fixture
def cliente(tmp_path):
    previo = {k: os.environ.get(k) for k in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH")}
    ruta = str(tmp_path / "purge.db")
    os.environ["ALEPH_ROLE"] = "client"
    os.environ["PUPPET_SQLITE_PATH"] = ruta
    _reset_dbmod()
    from app.phase1 import repo
    sq = repo._dbmod()._sqlite()
    c = sq.conectar(ruta)
    sq.crear_schema(c)
    c.commit()
    c.close()
    yield ruta
    for k, v in previo.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    _reset_dbmod()


def test_purge_user_corre_en_sqlite_sin_information_schema(cliente):
    """purge_user completa en el cliente: billing_* se detecta por sqlite_master (no
    existen → no se borran), y el resto (runs/outputs vía ANY(%s::uuid[]), users) corre
    normal. Sin el fix, la query a information_schema aborta todo con `no such table`."""
    from app.phase1 import repo
    from app.phase1 import account_deletion as ad

    conn = repo.get_conn(cliente)
    u = repo.register_user(conn, "purge-sqlite@test.local", "pw-purge-1234")
    uid = str(u["id"])
    # una run + un output → ejercita el ANY(%s::uuid[]) del purge con lista NO vacía
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (id, user_id, intent) VALUES (%s,%s,%s)",
                    ("run-purge", uid, "test"))
        cur.execute("INSERT INTO outputs (run_id, kind, uri) VALUES (%s,%s,%s)",
                    ("run-purge", "file", "data/run_outputs/run-purge/x.txt"))
    conn.commit()

    # force=True saltea el guard de soft-delete (no hay deleted_at)
    res = ad.purge_user(conn, uid, force=True)
    assert res["purged"] is True, f"purge no completó (¿information_schema?): {res}"
    assert res["counts"].get("runs", 0) >= 1, f"no borró la run: {res['counts']}"

    # el usuario y su run ya no están
    assert repo.user_deleted_state(conn, uid) is None, "el usuario sigue existiendo"
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM runs WHERE id = %s", ("run-purge",))
        assert cur.fetchone()[0] == 0, "la run no se borró"
        cur.execute("SELECT COUNT(*) FROM outputs WHERE run_id = %s", ("run-purge",))
        assert cur.fetchone()[0] == 0, "el output no cascadeó"
        cur.execute("SELECT COUNT(*) FROM users WHERE id = %s", (uid,))
        assert cur.fetchone()[0] == 0, "el user no se borró"
    conn.close()
