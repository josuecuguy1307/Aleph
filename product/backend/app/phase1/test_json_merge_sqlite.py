"""test_json_merge_sqlite.py — [Casa 2 · Fase 2 · 2.4] los merges JSONB en SQLite.

Tres sitios del árbol usan operadores JSONB de Postgres que el traductor DEJA PASAR pero
que en SQLite significan otra cosa (fallo callado, la clase que la migración existe para
matar). No los caza `DialectoNoSoportado`; los caza correr la función real y mirar el dato:

  1. methods_repo.update_method_run — `control = COALESCE(control,'{}') || patch - key`.
     En SQLite `||` concatena strings (JSON inválido) y `- key` resta (da 0). El fix
     computa el merge en Python. Se prueba el caso que DIVERGE de json_patch: un `remedy`
     anidado que se REEMPLAZA entero (shallow), no se fusiona.
  2. instructions_repo.update_instruction — `meta = COALESCE(meta,'{}') || patch`. Idem.
  3. instructions_repo.add_proposal — `pg_advisory_xact_lock`, que en SQLite no existe y
     revienta. El fix usa BEGIN IMMEDIATE; se prueba que el cap anti-spam aguanta la
     carrera TOCTOU (8 hilos, cap 3).

Todo contra un SQLite real, sin mocks. El proceso queda en rol cliente por el fixture.
"""
from __future__ import annotations

import os
import threading
from collections import Counter

import pytest


def _reset_dbmod():
    from app.phase1 import repo
    repo._db = None


@pytest.fixture
def cliente(tmp_path):
    previo = {k: os.environ.get(k) for k in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH")}
    ruta = str(tmp_path / "merge.db")
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


def _seed_method_run(conn, repo, mr, run_id, control0=None):
    u = repo.register_user(conn, f"merge-{run_id}@test.local", "pw-merge-1234")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (id, user_id, intent) VALUES (%s,%s,%s)",
                    (run_id, str(u["id"]), "test"))
    conn.commit()
    mr.create_method_run(conn, run_id=run_id, method_id=None, user_id=str(u["id"]),
                         puppet_id=None, space_id=None, state={"current": "s1"})
    if control0 is not None:
        mr.update_method_run(conn, run_id, control_merge=control0)
    return str(u["id"])


def test_control_merge_es_shallow_y_clear_borra(cliente):
    """El `||`/`- key` de PG en el cliente. El caso clave: un `remedy` anidado ya presente
    se REEMPLAZA entero por el nuevo (shallow, como PG), NO se fusiona (como haría
    json_patch). Y control_clear borra la clave."""
    from app.phase1 import repo
    from app.phase1 import methods_repo as mr

    conn = repo.get_conn(cliente)
    # arranca con un remedy viejo con sub-claves
    _seed_method_run(conn, repo, mr, "run-merge",
                     control0={"remedy": {"action": "retry", "step_id": "viejo"}, "pause": True})

    # merge de un remedy NUEVO: en shallow-merge reemplaza el objeto entero
    ok = mr.update_method_run(conn, "run-merge",
                              control_merge={"remedy": {"action": "skip"}})
    assert ok
    ctl = mr.read_control(conn, "run-merge")
    assert ctl["remedy"] == {"action": "skip"}, \
        f"el remedy debía reemplazarse entero (shallow), no fusionarse: {ctl['remedy']}"
    assert ctl["pause"] is True, "las otras claves se conservan"

    # control_clear borra la clave (el `- key` de PG)
    ok = mr.update_method_run(conn, "run-merge", control_clear=["remedy"])
    assert ok
    ctl = mr.read_control(conn, "run-merge")
    assert "remedy" not in ctl, f"control_clear no borró: {ctl}"
    assert ctl["pause"] is True

    # y el JSON quedó VÁLIDO (no concatenado): vuelve como dict
    assert isinstance(ctl, dict)
    conn.close()


def test_control_merge_y_clear_juntos_en_una_llamada(cliente):
    """merge + clear en la misma llamada (Postgres los mete en una expresión; el cliente
    los aplica en orden). Se agrega uno y se borra otro a la vez."""
    from app.phase1 import repo
    from app.phase1 import methods_repo as mr

    conn = repo.get_conn(cliente)
    _seed_method_run(conn, repo, mr, "run-both", control0={"a": 1, "b": 2})
    ok = mr.update_method_run(conn, "run-both",
                              control_merge={"c": 3}, control_clear=["a"])
    assert ok
    ctl = mr.read_control(conn, "run-both")
    assert ctl == {"b": 2, "c": 3}, f"merge+clear juntos: {ctl}"
    conn.close()


def test_update_instruction_meta_merge(cliente):
    """El `meta = meta || patch` de instructions, aprobando una propuesta del agente."""
    from app.phase1 import repo
    from app.phase1 import instructions_repo as ir

    conn = repo.get_conn(cliente)
    u = repo.register_user(conn, "instr-meta@test.local", "pw-instr-1234")
    pup = repo.create_puppet(conn, owner_id=str(u["id"]), name="agente-instr",
                             nicho="finanzas", config={"meta": {"nicho": "finanzas"}})
    prop = ir.add_proposal(conn, user_id=str(u["id"]), puppet_id=str(pup["id"]),
                           content="siempre citá la fuente", run_id="r-1")
    assert prop is not None
    # aprobar: enabled=True + meta_merge={'approved': True}
    ok = ir.update_instruction(conn, str(prop["id"]), str(u["id"]),
                               enabled=True, meta_merge={"approved": True})
    assert ok
    got = ir.get_instruction_owned(conn, str(prop["id"]), str(u["id"]))
    assert isinstance(got["meta"], dict), f"meta volvió {type(got['meta']).__name__}"
    assert got["meta"].get("approved") is True, f"no mergeó approved: {got['meta']}"
    assert got["meta"].get("run_id") == "r-1", "el merge PISÓ las claves viejas de meta"
    assert got["meta"].get("proposed") is True
    conn.close()


def test_add_proposal_cap_aguanta_la_carrera(cliente):
    """El cap anti-spam (MAX=3) bajo BEGIN IMMEDIATE en vez del advisory lock. 8 hilos
    proponen a la vez sobre el MISMO scope; el cap NO se supera (TOCTOU cerrado) y ningún
    hilo revienta con `no such function`."""
    from app.phase1 import repo
    from app.phase1 import instructions_repo as ir

    conn = repo.get_conn(cliente)
    u = repo.register_user(conn, "prop-race@test.local", "pw-prop-1234")
    pup = repo.create_puppet(conn, owner_id=str(u["id"]), name="agente-prop",
                             nicho="finanzas", config={"meta": {"nicho": "finanzas"}})
    uid, pid = str(u["id"]), str(pup["id"])
    conn.close()

    creados, errores = [], []
    lock = threading.Lock()
    barrera = threading.Barrier(8)

    def worker(w):
        c = repo.get_conn(cliente)          # una conexión por hilo (sqlite no las comparte)
        mios, errs = [], []
        barrera.wait()
        for i in range(4):
            try:
                r = ir.add_proposal(c, user_id=uid, puppet_id=pid,
                                    content=f"w{w} propuesta {i}", run_id=f"r-{w}-{i}")
                if r is not None:
                    mios.append(r["id"])
            except Exception as exc:
                errs.append(f"{type(exc).__name__}: {exc}")
        c.close()
        with lock:
            creados.extend(mios)
            errores.extend(errs)

    hs = [threading.Thread(target=worker, args=(w,)) for w in range(8)]
    for h in hs:
        h.start()
    for h in hs:
        h.join(timeout=60)

    assert not errores, f"add_proposal reventó (¿pg_advisory_xact_lock?): {errores[:3]}"
    # el cap es 3 pendientes: pese a 32 intentos concurrentes, quedan EXACTAMENTE 3.
    c = repo.get_conn(cliente)
    n = ir.scope_usage(c, uid, pid)["entries"]
    c.close()
    assert n == 3, f"el cap se pasó por TOCTOU: {n} pendientes (deberían ser 3)"
    assert len(creados) == 3, f"se crearon {len(creados)}, no 3"


def test_add_account_proposal_cap_aguanta_la_carrera(cliente):
    """El gemelo de account_memories: `repo.add_account_proposal` usaba el MISMO
    `pg_advisory_xact_lock`. Mismo fix (BEGIN IMMEDIATE), misma prueba: 8 hilos, cap 3,
    sin `no such function`."""
    from app.phase1 import repo

    conn = repo.get_conn(cliente)
    u = repo.register_user(conn, "acct-race@test.local", "pw-acct-1234")
    uid = str(u["id"])
    conn.close()

    creados, errores = [], []
    lock = threading.Lock()
    barrera = threading.Barrier(8)

    def worker(w):
        c = repo.get_conn(cliente)
        mios, errs = [], []
        barrera.wait()
        for i in range(4):
            try:
                r = repo.add_account_proposal(c, owner_id=uid, content=f"w{w} hecho {i}",
                                              run_id=f"r-{w}-{i}")
                if r is not None:
                    mios.append(r["id"])
            except Exception as exc:
                errs.append(f"{type(exc).__name__}: {exc}")
        c.close()
        with lock:
            creados.extend(mios)
            errores.extend(errs)

    hs = [threading.Thread(target=worker, args=(w,)) for w in range(8)]
    for h in hs:
        h.start()
    for h in hs:
        h.join(timeout=60)

    assert not errores, f"add_account_proposal reventó: {errores[:3]}"
    c = repo.get_conn(cliente)
    pend = repo.list_account_proposals(c, uid)
    c.close()
    assert len(pend) == 3, f"el cap se pasó por TOCTOU: {len(pend)} (deberían ser 3)"
    assert len(creados) == 3, f"se crearon {len(creados)}, no 3"
