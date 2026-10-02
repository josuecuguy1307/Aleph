"""
test_boot_cliente_sqlite.py — el boot del CLIENTE deja la DB usable, o falla VISIBLE.
[GAP-DEV-DESKTOP §2.1/§2.2 — la .app corría con una DB de CERO tablas y servía igual]

Verde = efecto real sobre un datadir VIRGEN (tmp_path): se arranca la app con el
lifespan DE VERDAD (rol client + SQLite, `with TestClient` entra al lifespan) y se
mira el ARCHIVO que quedó — nunca narración:

  1. datadir virgen → boot → aleph.db existe con TODAS las tablas de la frontera
     (`role.tablas_del_cliente()`) y `user_version` estampado.
  2. re-boot sobre la misma DB → idempotente: no rompe, no pisa datos ya guardados.
  3. guardar y leer un agente (repo.get_or_create_user/create_puppet/get_puppet)
     FUNCIONA post-boot, y la fila queda en el .db DEL DATADIR — una sola ruta.
  4. ruta_db() respeta ALEPH_DATA_DIR (la mina §2.2: dos resoluciones divergentes —
     la enc.key caía en el datadir aislado y el .db se iba a ~/Library).
  5. DB imposible (aleph.db corrupto) → FALLO VISIBLE, JAMÁS MUDO: /health
     status=error con el motivo, la API responde 503 claro y un browser recibe una
     página legible. Nada de servir "como si nada".

Red-proof (contra el código viejo): (1) dejaba 0 tablas — nadie llamaba crear_schema
en el boot; (3) moría con "no such table: puppets"; (4) devolvía ~/Library ignorando
ALEPH_DATA_DIR; (5) servía 200 normal con la DB rota.

La guarda de pytest de db_boot se levanta EXPLÍCITA acá (PUPPET_DB_BOOTSTRAP=1)
apuntando a un ALEPH_DATA_DIR temporal: la suite jamás toca la DB real del dev.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]  # tests/ -> backend/ -> product/ -> raíz
_PLATFORM = REPO_ROOT / "platform"
if str(_PLATFORM) not in sys.path:  # main.py hace lo mismo; acá es sólo por orden de import
    sys.path.insert(0, str(_PLATFORM))

import role  # noqa: E402 — la frontera ejecutable (fuente de las tablas esperadas)


def _sqlite_db_mod():
    """Carga platform/db/sqlite_db.py por RUTA (patrón de conftest.tmp_vault): no se
    mete platform/db en sys.path — ahí viven nombres genéricos (db, pool, dialect)."""
    p = _PLATFORM / "db" / "sqlite_db.py"
    spec = importlib.util.spec_from_file_location("sqlite_db_boot_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _entorno_cliente(monkeypatch, datadir: Path) -> None:
    monkeypatch.setenv("ALEPH_ROLE", "client")
    monkeypatch.setenv("ALEPH_DATA_DIR", str(datadir))
    monkeypatch.setenv("PUPPET_DB_BOOTSTRAP", "1")   # levanta la guarda pytest, EXPLÍCITO
    monkeypatch.setenv("PUPPET_WORKERS", "0")        # modo solo-API (bootstrap.py)
    monkeypatch.delenv("PUPPET_SQLITE_PATH", raising=False)


def _tablas_y_version(db_file: Path) -> tuple[set, int]:
    raw = sqlite3.connect(db_file)
    try:
        tablas = {r[0] for r in raw.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        version = raw.execute("PRAGMA user_version").fetchone()[0]
    finally:
        raw.close()
    return tablas, version


def test_datadir_virgen_boot_crea_tablas(monkeypatch, tmp_path):
    _entorno_cliente(monkeypatch, tmp_path)
    from app.main import app
    with TestClient(app) as c:
        salud = c.get("/health").json()
        assert salud["status"] == "ok", f"/health debe estar sano tras el boot: {salud}"
    db_file = tmp_path / "aleph.db"
    assert db_file.exists(), "el boot debe crear el .db en ALEPH_DATA_DIR"
    tablas, version = _tablas_y_version(db_file)
    faltan = role.tablas_del_cliente() - tablas
    assert not faltan, f"tablas de la frontera ausentes tras el boot: {sorted(faltan)}"
    esperado = _sqlite_db_mod().VERSION_SCHEMA_CLIENTE
    assert version == esperado, f"user_version {version} != {esperado} (sin estampar)"


def test_reboot_idempotente_no_pisa_datos(monkeypatch, tmp_path):
    _entorno_cliente(monkeypatch, tmp_path)
    from app.main import app
    from app.phase1 import repo

    with TestClient(app):
        conn = repo.get_conn()
        try:
            usuario = repo.get_or_create_user(conn, "boot@aleph.local")
        finally:
            conn.close()
    tablas_1, version_1 = _tablas_y_version(tmp_path / "aleph.db")

    # Segundo arranque sobre la MISMA DB: ni rompe, ni duplica, ni pisa lo guardado.
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
        conn = repo.get_conn()
        try:
            de_nuevo = repo.get_or_create_user(conn, "boot@aleph.local")
        finally:
            conn.close()
    assert de_nuevo["id"] == usuario["id"], "re-boot NO debe pisar los datos existentes"
    tablas_2, version_2 = _tablas_y_version(tmp_path / "aleph.db")
    assert tablas_2 == tablas_1 and version_2 == version_1


def test_guardar_y_leer_agente_post_boot(monkeypatch, tmp_path):
    _entorno_cliente(monkeypatch, tmp_path)
    from app.main import app
    from app.phase1 import repo

    config = {"meta": {"nombre": "agente-boot"}, "belt_refs": []}
    with TestClient(app):
        conn = repo.get_conn()
        try:
            usuario = repo.get_or_create_user(conn, "agente@aleph.local")
            creado = repo.create_puppet(conn, owner_id=usuario["id"], name="agente-boot",
                                        nicho="finanzas", config=config)
            leido = repo.get_puppet(conn, creado["id"])
        finally:
            conn.close()

    assert leido is not None, "get_puppet debe encontrar lo que create_puppet guardó"
    assert leido["name"] == "agente-boot" and leido["config"] == config

    # Efecto real EN EL ARCHIVO del datadir — la fila vive donde dice ruta_db(), no
    # en otra resolución de ruta (la divergencia §2.2 era exactamente esto).
    raw = sqlite3.connect(tmp_path / "aleph.db")
    try:
        filas = raw.execute("SELECT name, owner_id FROM puppets").fetchall()
    finally:
        raw.close()
    assert filas == [("agente-boot", usuario["id"])]


def test_ruta_db_respeta_aleph_data_dir(monkeypatch, tmp_path):
    sdb = _sqlite_db_mod()
    monkeypatch.setenv("ALEPH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PUPPET_SQLITE_PATH", raising=False)
    assert sdb.ruta_db() == str(tmp_path / "aleph.db"), \
        "ruta_db debe resolver por aleph_paths (ALEPH_DATA_DIR incluido)"
    # El override explícito de archivo sigue GANANDO (contrato de tests/ops intacto).
    monkeypatch.setenv("PUPPET_SQLITE_PATH", str(tmp_path / "otro.db"))
    assert sdb.ruta_db() == str(tmp_path / "otro.db")


def test_schema_incompleto_se_detecta(tmp_path):
    """La verificación contra role.tablas_del_cliente() es portante: una DB ya
    estampada (user_version=1) a la que le falta una tabla de la frontera NO pasa
    el bootstrap en silencio — levanta SchemaClienteIncompleto con la lista."""
    sdb = _sqlite_db_mod()
    db_file = tmp_path / "aleph.db"
    sdb.asegurar_schema(str(db_file))                 # bootstrap sano y estampado
    raw = sqlite3.connect(db_file)
    raw.execute("DROP TABLE puppets")                 # FK off en conexión pelada: drop libre
    raw.commit()
    raw.close()
    with pytest.raises(sdb.SchemaClienteIncompleto, match="puppets"):
        sdb.asegurar_schema(str(db_file))             # v=1 → no re-aplica el .sql → DETECTA


def test_db_imposible_falla_visible(monkeypatch, tmp_path):
    """aleph.db CORRUPTO (bytes basura donde va la DB) → el boot lo detecta y NO
    sirve como si nada. Es el escenario que llega al lifespan en el proceso real;
    un datadir bloqueado del todo muere antes, en el import (data_root() a nivel
    módulo en phase1/router.py) — ruidoso también, pero por otra vía."""
    (tmp_path / "aleph.db").write_bytes(b"esto no es una base sqlite\x00\xff" * 8)
    _entorno_cliente(monkeypatch, tmp_path)
    from app.main import app
    with TestClient(app) as c:
        salud = c.get("/health").json()
        assert salud["status"] == "error", "con DB rota /health NO puede decir ok"
        assert salud.get("db"), "/health debe traer el motivo del fallo"

        api = c.get("/catalog/finanzas")
        assert api.status_code == 503, "la API no debe servir como si nada"
        cuerpo = api.json()
        assert cuerpo["error"] == "db_unavailable" and cuerpo["detail"]

        pagina = c.get("/", headers={"accept": "text/html"})
        assert pagina.status_code == 503
        assert "no puede acceder a tus datos" in pagina.text, \
            "un browser (la .app) debe recibir el error LEGIBLE, no un webview mudo"
