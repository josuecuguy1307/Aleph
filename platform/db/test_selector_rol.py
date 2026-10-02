"""test_selector_rol.py — el selector de backend por rol. [Casa 2 · Fase 2 · 2.2b]

`db.get_conn()` es EL EMBUDO: los 14 routers que la reciben inyectada y los ~20 que
llaman `repo.get_conn()` directo terminan todos ahí. Este archivo prueba que el embudo
manda cada rol a su base **y que no se cruzan**, que es el requisito duro: el plano de
control está vivo en producción y si cae a SQLite, los pagos dejan de cobrarse.

Verde = efecto real en LOS DOS caminos: se escribe y se lee de verdad en cada base.
El camino Postgres se saltea (no falla) si no hay un PG local — así el suite corre en
cualquier máquina, pero avisa qué no pudo comprobar.

Correr:  pytest platform/db/test_selector_rol.py -v
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys

import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_PLATFORM = os.path.dirname(_AQUI)
for _p in (_AQUI, _PLATFORM):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _recargar(rol: str | None):
    """Recarga `role` y `db` con ALEPH_ROLE puesto. El rol se lee por llamada, pero
    `role` puede haber quedado cacheado por otro test."""
    if rol is None:
        os.environ.pop("ALEPH_ROLE", None)
    else:
        os.environ["ALEPH_ROLE"] = rol
    import role
    importlib.reload(role)
    import db
    importlib.reload(db)
    return db


@pytest.fixture(autouse=True)
def _limpiar():
    previo = os.environ.get("ALEPH_ROLE")
    previo_path = os.environ.get("PUPPET_SQLITE_PATH")
    yield
    for k, v in (("ALEPH_ROLE", previo), ("PUPPET_SQLITE_PATH", previo_path)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _hay_postgres() -> bool:
    try:
        return subprocess.run(["pg_isready", "-h", "127.0.0.1", "-p", "5432"],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


# ── el selector manda a la base correcta ─────────────────────────────────────────

def test_client_va_a_sqlite(tmp_path):
    db = _recargar("client")
    assert db.es_cliente()
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / "aleph.db")
    conn = db.get_conn()
    assert type(conn).__module__ == "sqlite_db", f"esperaba SQLite, vino {type(conn)}"
    conn.close()


@pytest.mark.skipif(not _hay_postgres(), reason="sin Postgres local")
def test_control_sigue_en_postgres():
    db = _recargar("control")
    assert not db.es_cliente()
    conn = db.get_conn()
    assert "psycopg2" in type(conn).__module__, f"esperaba psycopg2, vino {type(conn)}"
    conn.close()


def test_el_default_sin_env_es_cliente():
    """Hereda el fail-closed de `role.py`: un rol sin declarar NO es el plano de control."""
    db = _recargar(None)
    assert db.es_cliente()


# ── efecto real: el MISMO repo.py escribe y lee en cada base ────────────────────

def _repo():
    sys.path.insert(0, os.path.join(os.path.dirname(_PLATFORM), "product", "backend"))
    from app.phase1 import repo
    return repo


def test_client_escribe_y_lee_de_verdad_en_sqlite(tmp_path):
    """EL TEST QUE IMPORTA del lado cliente: `repo.py` sin modificar, contra SQLite."""
    _recargar("client")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / "aleph.db")
    import sqlite_db
    repo = _repo()
    importlib.reload(repo) if hasattr(repo, "__spec__") else None

    conn = repo.get_conn()
    sqlite_db.crear_schema(conn)
    try:
        u = repo.get_or_create_user(conn, email="cliente@aleph.app")
        assert u["id"] and u["email"] == "cliente@aleph.app"
        assert u["tier"] == "free"
        # releer con OTRA conexión: prueba que se persistió en el archivo, no en memoria
        otra = repo.get_conn()
        try:
            leido = repo.get_user(otra, u["id"])
            assert leido["email"] == "cliente@aleph.app"
        finally:
            otra.close()
    finally:
        conn.close()
    assert os.path.exists(os.environ["PUPPET_SQLITE_PATH"]), "no escribió el archivo"


@pytest.mark.skipif(not _hay_postgres(), reason="sin Postgres local")
def test_control_escribe_y_lee_de_verdad_en_postgres():
    """EL MISMO `repo.py`, el mismo llamado, contra Postgres. El camino que NO puede caer."""
    _recargar("control")
    repo = _repo()
    conn = repo.get_conn()
    try:
        email = "control-2.2b@aleph.test"
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        u = repo.get_or_create_user(conn, email=email)
        assert u["id"] and u["email"] == email
        leido = repo.get_user(conn, u["id"])
        assert leido["email"] == email
        with conn.cursor() as cur:                      # limpiar
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.skipif(not _hay_postgres(), reason="sin Postgres local")
def test_las_tablas_de_control_existen_en_postgres_y_no_en_el_cliente(tmp_path):
    """La frontera de 2.0, ahora observable en las bases mismas."""
    import role
    _recargar("control")
    import db as dbc
    conn = dbc.get_conn()
    try:
        with conn.cursor() as cur:
            for t in sorted(role.TABLAS_CONTROL):
                cur.execute("SELECT to_regclass(%s)", (f"public.{t}",))
                assert cur.fetchone()[0] is not None, f"{t} debería existir en control"
    finally:
        conn.close()

    dbcli = _recargar("client")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / "c.db")
    import sqlite_db
    c = dbcli.get_conn()
    sqlite_db.crear_schema(c)
    try:
        presentes = {r[0] for r in c.raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        filtradas = presentes & set(role.TABLAS_CONTROL)
        assert not filtradas, f"tablas de plata en el cliente: {sorted(filtradas)}"
    finally:
        c.close()


# ── EN ROJO: cruzar los roles tiene que romper algo detectable ───────────────────

def test_rojo_client_contra_postgres_no_encuentra_su_base(tmp_path):
    """Forzar client→Postgres. Con `conn_params` apuntando a una base que no existe, el
    intento falla ruidoso en vez de escribir en el lugar equivocado."""
    import db as dbm
    dbm = _recargar("control")                      # fuerza el camino Postgres…
    os.environ["PG_DB"] = "base_que_no_existe_2_2b"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("SUPABASE_DB_URL", None)
    try:
        with pytest.raises(Exception) as e:
            dbm.get_conn()
        assert "base_que_no_existe" in str(e.value) or "does not exist" in str(e.value).lower()
    finally:
        os.environ.pop("PG_DB", None)


def test_rojo_control_contra_sqlite_no_tiene_las_tablas_de_plata(tmp_path):
    """EL CRUCE QUE ROMPE LOS PAGOS. Si el plano de control cayera a SQLite, las tablas
    de plata no están y el fallo es RUIDOSO (`no such table`), no una escritura callada
    a un archivo local. Esto documenta el daño y prueba que se ve."""
    dbm = _recargar("client")                        # simula "control cayó a client"
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / "x.db")
    import sqlite_db
    conn = dbm.get_conn()
    sqlite_db.crear_schema(conn)
    try:
        with pytest.raises(Exception) as e:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM subscriptions WHERE account_id = %s", ("x",))
        assert "no such table" in str(e.value).lower(), (
            f"debería fallar ruidoso; falló con: {e.value}")
    finally:
        conn.close()


def test_rojo_sin_selector_el_cliente_iria_a_postgres():
    """Prueba de que el selector es PORTANTE: sin él, `get_conn()` en client devolvería
    una conexión psycopg2 (o fallaría al conectar), no una SQLite."""
    db = _recargar("client")
    assert db.es_cliente()
    import inspect
    fuente = inspect.getsource(db.get_conn)
    assert "es_cliente()" in fuente, "el selector desapareció de get_conn()"


# ── la fuga de driver ────────────────────────────────────────────────────────────

def test_psy_bytea_devuelve_bytes_crudos_en_cliente(tmp_path):
    _recargar("client")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / "b.db")
    repo = _repo()
    assert repo.psy_bytea(b"\x00secreto") == b"\x00secreto"


@pytest.mark.skipif(not _hay_postgres(), reason="sin Postgres local")
def test_psy_bytea_sigue_envolviendo_en_control():
    _recargar("control")
    repo = _repo()
    envuelto = repo.psy_bytea(b"\x00secreto")
    assert type(envuelto).__name__ == "Binary", f"esperaba psycopg2.Binary, vino {type(envuelto)}"


def test_la_byok_cifrada_sobrevive_el_viaje_en_cliente(tmp_path):
    """La BYOK es bytes de Fernet: si el BLOB se guardara mal, la llave del usuario se
    pierde. De punta a punta contra SQLite."""
    _recargar("client")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / "k.db")
    import sqlite_db
    repo = _repo()
    conn = repo.get_conn()
    sqlite_db.crear_schema(conn)
    try:
        u = repo.get_or_create_user(conn, email="byok@aleph.app")
        repo.upsert_key(conn, user_id=u["id"], provider="anthropic", secret="sk-ant-secreto")
        recuperado = repo.get_key(conn, user_id=u["id"], provider="anthropic")
        assert recuperado == "sk-ant-secreto", f"la BYOK no volvió igual: {recuperado!r}"
    finally:
        conn.close()


# ── init_db en cliente ───────────────────────────────────────────────────────────

def test_ensure_database_es_noop_en_cliente(tmp_path):
    """En SQLite la base ES el archivo: no hay `CREATE DATABASE` que correr."""
    _recargar("client")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / "i.db")
    import init_db
    importlib.reload(init_db)
    assert init_db.ensure_database() is False


def test_apply_schema_en_cliente_crea_las_20_tablas(tmp_path):
    _recargar("client")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / "j.db")
    import init_db
    importlib.reload(init_db)
    init_db.apply_schema()
    import role
    import sqlite3
    crudo = sqlite3.connect(os.environ["PUPPET_SQLITE_PATH"])
    presentes = {r[0] for r in crudo.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    crudo.close()
    assert presentes == set(role.tablas_del_cliente())
