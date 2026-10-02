"""test_pool_rol.py — el pool por rol. [Casa 2 · Fase 2 · 2.2b, parte b]

`pool.pooled_conn()` es el SEGUNDO punto de entrada de conexiones del árbol (el primero
es `db.get_conn()`): lo usan `worker.py:49` e `infra_router.py:35`, o sea **el camino de
la cola**. Por eso este archivo va aparte y con su propio riesgo: si el pool queda
apuntando mal, lo que se rompe es el trabajo asíncrono.

En el cliente NO hay pool a propósito (SQLite no se poolea; ver el docstring de
`_conn_cliente`), y por ahí es por donde entra el pragma de FK a la cola.

Correr:  pytest platform/db/test_pool_rol.py -v
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import threading

import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_PLATFORM = os.path.dirname(_AQUI)
for _p in (_AQUI, _PLATFORM):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _recargar(rol: str):
    os.environ["ALEPH_ROLE"] = rol
    import role
    importlib.reload(role)
    import db
    importlib.reload(db)
    import pool
    importlib.reload(pool)
    return pool


@pytest.fixture(autouse=True)
def _limpiar():
    previo = os.environ.get("ALEPH_ROLE"), os.environ.get("PUPPET_SQLITE_PATH")
    yield
    for k, v in zip(("ALEPH_ROLE", "PUPPET_SQLITE_PATH"), previo):
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _hay_postgres() -> bool:
    try:
        return subprocess.run(["pg_isready", "-h", "127.0.0.1", "-p", "5432"],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def _preparar_cliente(tmp_path, nombre="cola.db"):
    pool = _recargar("client")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / nombre)
    import sqlite_db
    c = sqlite_db.conectar(os.environ["PUPPET_SQLITE_PATH"])
    sqlite_db.crear_schema(c)
    c.commit()
    c.close()
    return pool


# ── el contrato es el mismo en los dos roles ─────────────────────────────────────

def test_pooled_conn_funciona_en_cliente(tmp_path):
    pool = _preparar_cliente(tmp_path)
    with pool.pooled_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1


@pytest.mark.skipif(not _hay_postgres(), reason="sin Postgres local")
def test_pooled_conn_sigue_pooleando_en_control():
    pool = _recargar("control")
    with pool.pooled_conn() as conn:
        assert "psycopg2" in type(conn).__module__
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
    assert pool.get_pool() is not None, "el pool de control debería existir"
    pool.close_pool()


def test_get_pool_no_aplica_en_cliente(tmp_path):
    """Pedir el pool en cliente es un error de concepto: se dice, no se simula uno."""
    pool = _preparar_cliente(tmp_path)
    with pytest.raises(RuntimeError) as e:
        pool.get_pool()
    assert "no se poolea" in str(e.value).lower()


def test_close_pool_es_noop_en_cliente(tmp_path):
    pool = _preparar_cliente(tmp_path)
    pool.close_pool()          # no debe explotar: el shutdown es igual en los dos roles


# ── EL PUNTO: el pragma entra a la cola por acá ─────────────────────────────────

def test_cada_conexion_del_pool_cliente_trae_los_pragmas(tmp_path):
    """El requisito que 2.1 arrastró, en el camino de la cola. Se comprueba en VARIAS
    conexiones seguidas: el pragma es por conexión, no por archivo."""
    pool = _preparar_cliente(tmp_path)
    for _ in range(3):
        with pool.pooled_conn() as conn:
            assert conn.raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.raw.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_el_cascade_de_job_queue_funciona_desde_el_pool(tmp_path):
    """`job_queue.run_id` referencia `runs(id)` ON DELETE SET NULL. Sin el pragma, el
    borrado dejaría el job apuntando a un run que ya no existe."""
    pool = _preparar_cliente(tmp_path)
    with pool.pooled_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (email) VALUES (%s) RETURNING id", ("q@a.b",))
            uid = cur.fetchone()[0]
            cur.execute("INSERT INTO runs (user_id) VALUES (%s) RETURNING id", (uid,))
            rid = cur.fetchone()[0]
            cur.execute("INSERT INTO job_queue (kind, run_id) VALUES ('construir',%s)", (rid,))
            cur.execute("DELETE FROM runs WHERE id = %s", (rid,))
            cur.execute("SELECT run_id FROM job_queue")
            assert cur.fetchone()[0] is None, "el SET NULL no corrió: ¿falta el pragma?"
        conn.commit()


# ── concurrencia: lo que 2.3 va a necesitar ─────────────────────────────────────

def test_varios_hilos_escriben_sin_database_is_locked(tmp_path):
    """El worker pool son 4 hilos + un heartbeat por job. Sin WAL y sin busy_timeout,
    dos escrituras simultáneas dan `database is locked`. Con conexión fresca por hilo,
    no. (El reclamo sin doble-claim es 2.3; acá sólo se prueba que se puede escribir.)"""
    pool = _preparar_cliente(tmp_path, "conc.db")
    errores, hechos = [], []
    lock = threading.Lock()

    def escribir(n):
        try:
            with pool.pooled_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO job_queue (kind, payload) VALUES (%s,%s)",
                                (f"job{n}", "{}"))
                conn.commit()
            with lock:
                hechos.append(n)
        except Exception as e:      # noqa: BLE001
            with lock:
                errores.append(f"{type(e).__name__}: {e}")

    hilos = [threading.Thread(target=escribir, args=(i,)) for i in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)

    assert not errores, f"escrituras concurrentes fallaron: {errores[:3]}"
    assert len(hechos) == 8
    with pool.pooled_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM job_queue")
            assert cur.fetchone()[0] == 8, "se perdieron escrituras"


# ── EN ROJO ──────────────────────────────────────────────────────────────────────

def test_rojo_sin_el_pragma_el_job_queda_apuntando_a_un_run_muerto(tmp_path):
    """El daño exacto que el pragma evita en la cola, con el pragma apagado a mano."""
    pool = _preparar_cliente(tmp_path, "rojo.db")
    with pool.pooled_conn() as conn:
        conn.raw.execute("PRAGMA foreign_keys = OFF")
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (email) VALUES (%s) RETURNING id", ("r@a.b",))
            uid = cur.fetchone()[0]
            cur.execute("INSERT INTO runs (user_id) VALUES (%s) RETURNING id", (uid,))
            rid = cur.fetchone()[0]
            cur.execute("INSERT INTO job_queue (kind, run_id) VALUES ('construir',%s)", (rid,))
            cur.execute("DELETE FROM runs WHERE id = %s", (rid,))
            cur.execute("SELECT run_id FROM job_queue")
            colgado = cur.fetchone()[0]
    assert colgado == rid, (
        "sin el pragma el job DEBERÍA quedar apuntando a un run borrado; "
        "si esto cambia, revisar si el default de SQLite cambió")


def test_rojo_el_selector_del_pool_no_duplica_la_logica_del_rol():
    """`pool._es_cliente()` tiene que delegar en `db.es_cliente()`. Si alguien duplicara
    la lectura de la env acá, habría DOS fuentes de verdad del rol y podrían divergir."""
    import inspect

    import pool as pmod
    fuente = inspect.getsource(pmod._es_cliente)
    assert "from db import es_cliente" in fuente, "el pool debe delegar, no releer la env"
    assert "ALEPH_ROLE" not in fuente, "el pool no debe leer la env por su cuenta"
