#!/usr/bin/env python3
"""verify_multiagente_saltos.py — LA MIGRACIÓN, CORRIDA EN LOS DOS DIALECTOS.

Spec: docs/multiagente.md §4.1. No mide "el archivo .sql dice X": crea bases DE VERDAD,
corre la migración, mira las columnas que quedaron y escribe un padre con sus saltos.

  POSTGRES  — base DESECHABLE (`puppet_ai_verify_ma_f1`), migrada con el runner real
              (`migrate.py`) desde cero, y DROPEADA al final.
              ⚠️ JAMÁS toca `puppet_ai` (la base real de persona usuaria). Hay un guard duro que
              aborta si el nombre de la base de prueba coincide con la real: una vara que
              escribe en producción es peor que una vara que no corre.
  SQLITE    — los TRES caminos que tienen que dar la MISMA tabla:
                (a) DB VIRGEN     → `schema_sqlite.sql` completo,
                (b) DB DESPLEGADA → v1 real + `_MIGRACIONES_CLIENTE[2]` (el ALTER),
                (c) RE-CORRIDA    → idempotente (SQLite no tiene ADD COLUMN IF NOT EXISTS).

Correr:  python platform/db/verify_multiagente_saltos.py
Salida:  cada assert por línea + veredicto. Exit 0 = verde.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parent))

#: Las cuatro columnas del enlace + su tipo esperado POR DIALECTO.
COLUMNAS_PG = {"parent_run_id": "uuid", "hop_index": "integer",
               "hop_latency_ms": "bigint", "modo": "text"}
COLUMNAS_SQLITE = {"parent_run_id": "TEXT", "hop_index": "INTEGER",
                   "hop_latency_ms": "INTEGER", "modo": "TEXT"}

#: La base DESECHABLE de la prueba. Si esto llegara a valer 'puppet_ai', el guard aborta.
DB_PRUEBA = os.environ.get("MA_VERIFY_DB", "puppet_ai_verify_ma_f1")

_fallos: list[str] = []


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    _fallos.append(msg)
    print(f"  ✗ {msg}")


def _chk(cond: bool, msg: str) -> bool:
    (_ok if cond else _fail)(msg)
    return bool(cond)


# ── POSTGRES ────────────────────────────────────────────────────────────────────

def verificar_postgres() -> None:
    print("\n── POSTGRES · base desechable, runner real ──")
    # El default del árbol es ALEPH_ROLE=client (fail-closed) y con ese rol `db.get_conn`
    # devuelve SQLite: sin esto la mitad "Postgres" de esta vara mediría SQLite otra vez,
    # y daría VERDE sin haber tocado Postgres. Se fija ANTES del import de `db`, que lo lee
    # al cargarse. Postgres ES el plano de control: el rol correcto acá es 'control'.
    os.environ["ALEPH_ROLE"] = "control"
    import db as _db
    import init_db as _init
    import migrate as _migrate

    real = _db.DEFAULT_DB
    if DB_PRUEBA == real:
        raise SystemExit(f"✗✗ ABORTO: la base de prueba ('{DB_PRUEBA}') es la REAL. "
                         f"Esta vara no escribe en producción.")

    _drop_pg(real)
    _init.DEFAULT_DB = DB_PRUEBA   # type: ignore[attr-defined]
    _db.DEFAULT_DB = DB_PRUEBA     # type: ignore[attr-defined]
    try:
        aplicadas = _migrate.migrate(DB_PRUEBA)
        _chk("0019_multiagente_saltos.sql" in aplicadas,
             f"el runner aplicó 0019 desde cero ({len(aplicadas)} migraciones)")

        conn = _db.get_conn(DB_PRUEBA)
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT column_name, data_type, is_nullable
                               FROM information_schema.columns
                               WHERE table_name = 'runs'""")
                cols = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
                for nombre, tipo in COLUMNAS_PG.items():
                    if _chk(nombre in cols, f"runs.{nombre} existe"):
                        _chk(cols[nombre][0] == tipo,
                             f"runs.{nombre} es {tipo} (recibido {cols[nombre][0]})")
                        _chk(cols[nombre][1] == "YES",
                             f"runs.{nombre} es NULABLE (NULL = run normal)")

                cur.execute("SELECT indexname FROM pg_indexes WHERE tablename='runs'")
                idx = {r[0] for r in cur.fetchall()}
                _chk("idx_runs_parent" in idx, "índice idx_runs_parent creado")

                # EFECTO REAL: un padre + 3 saltos enlazados, leídos de vuelta EN ORDEN.
                cur.execute("INSERT INTO runs (intent, modo) VALUES ('padre','cadena') "
                            "RETURNING id")
                padre = cur.fetchone()[0]
                for i, lat in enumerate((1240, 980, 1510)):
                    cur.execute(
                        "INSERT INTO runs (intent, parent_run_id, hop_index, hop_latency_ms) "
                        "VALUES (%s, %s, %s, %s)", (f"salto {i}", padre, i, lat))
                conn.commit()
                cur.execute("SELECT hop_index, hop_latency_ms FROM runs "
                            "WHERE parent_run_id = %s ORDER BY hop_index", (padre,))
                filas = cur.fetchall()
            _chk([f[0] for f in filas] == [0, 1, 2], "los 3 saltos vuelven EN ORDEN")
            _chk([f[1] for f in filas] == [1240, 980, 1510], "la latencia por salto persiste")

            # un run NORMAL (sin enlace) sigue existiendo con todo en NULL
            with conn.cursor() as cur:
                cur.execute("INSERT INTO runs (intent) VALUES ('normal') RETURNING "
                            "parent_run_id, hop_index, hop_latency_ms, modo")
                _chk(all(v is None for v in cur.fetchone()),
                     "un run NORMAL nace con las 4 columnas en NULL (cero regresión)")
                conn.commit()
        finally:
            conn.close()
    finally:
        _db.DEFAULT_DB = real      # type: ignore[attr-defined]
        _init.DEFAULT_DB = real    # type: ignore[attr-defined]
        _drop_pg(real)


def _drop_pg(real_db: str) -> None:
    """Dropea la base desechable. Con guard: nunca la real."""
    if DB_PRUEBA == real_db:
        return
    import psycopg2
    from psycopg2 import sql as _sql
    import db as _db
    c = psycopg2.connect(**_db.conn_params(dbname="postgres"))
    c.autocommit = True
    try:
        with c.cursor() as cur:
            cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()", (DB_PRUEBA,))
            cur.execute(_sql.SQL("DROP DATABASE IF EXISTS {}").format(
                _sql.Identifier(DB_PRUEBA)))
    finally:
        c.close()


# ── SQLITE ──────────────────────────────────────────────────────────────────────

def _cols_sqlite(conn) -> dict:
    return {r[1]: r[2] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}


def verificar_sqlite() -> None:
    print("\n── SQLITE · los tres caminos a la misma tabla ──")
    import sqlite_db as sq

    # (a) DB VIRGEN — el .sql completo
    virgen = sqlite3.connect(":memory:")
    virgen.executescript(_AQUI.joinpath("schema_sqlite.sql").read_text(encoding="utf-8"))
    cols = _cols_sqlite(virgen)
    for nombre, tipo in COLUMNAS_SQLITE.items():
        if _chk(nombre in cols, f"[virgen] runs.{nombre} existe"):
            _chk(cols[nombre] == tipo,
                 f"[virgen] runs.{nombre} es {tipo} (recibido {cols[nombre]})")
    idx = {r[0] for r in virgen.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    _chk("idx_runs_parent" in idx, "[virgen] índice idx_runs_parent creado")
    virgen.close()

    # (b) DB YA DESPLEGADA — v1 REAL (el schema tal como estaba antes de esta migración)
    #     + el ALTER de _MIGRACIONES_CLIENTE[2] por el camino REAL (asegurar_schema).
    tmp = Path(tempfile.mkdtemp(prefix="ma-sqlite-")) / "aleph.db"
    _sembrar_v1(tmp)
    antes = sqlite3.connect(tmp)
    _chk(not (set(COLUMNAS_SQLITE) & set(_cols_sqlite(antes))),
         "[desplegada] la DB v1 NO tenía las columnas (la prueba prueba algo)")
    antes.close()

    info = sq.asegurar_schema(str(tmp))
    _chk(info["version"] == sq.VERSION_SCHEMA_CLIENTE,
         f"[desplegada] user_version subió a {sq.VERSION_SCHEMA_CLIENTE}")
    despues = sqlite3.connect(tmp)
    cols = _cols_sqlite(despues)
    for nombre, tipo in COLUMNAS_SQLITE.items():
        if _chk(nombre in cols, f"[desplegada] runs.{nombre} apareció"):
            _chk(cols[nombre] == tipo, f"[desplegada] runs.{nombre} es {tipo}")
    idx = {r[0] for r in despues.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    _chk("idx_runs_parent" in idx, "[desplegada] índice idx_runs_parent creado")

    # EFECTO REAL sobre la DB migrada: padre + saltos, con FK encendidos.
    despues.execute("PRAGMA foreign_keys = ON")
    despues.execute("INSERT INTO users (email) VALUES ('ma@verify.local')")
    padre = despues.execute(
        "INSERT INTO runs (intent, modo) VALUES ('padre','cadena') RETURNING id"
    ).fetchone()[0]
    for i, lat in enumerate((1240, 980, 1510)):
        despues.execute("INSERT INTO runs (intent, parent_run_id, hop_index, hop_latency_ms) "
                        "VALUES (?,?,?,?)", (f"salto {i}", padre, i, lat))
    despues.commit()
    filas = despues.execute("SELECT hop_index, hop_latency_ms FROM runs "
                            "WHERE parent_run_id = ? ORDER BY hop_index", (padre,)).fetchall()
    _chk([f[0] for f in filas] == [0, 1, 2], "[desplegada] los 3 saltos vuelven EN ORDEN")
    _chk([f[1] for f in filas] == [1240, 980, 1510], "[desplegada] la latencia por salto persiste")
    # el FK es REAL, no decorativo: un parent_run_id inventado tiene que rebotar
    try:
        despues.execute("INSERT INTO runs (intent, parent_run_id) VALUES ('huerfano','no-existe')")
        despues.commit()
        _fail("[desplegada] el FK parent_run_id NO se hace cumplir (aceptó un padre inexistente)")
    except sqlite3.IntegrityError:
        _ok("[desplegada] el FK parent_run_id se hace cumplir (FOREIGN KEY constraint)")
    despues.close()

    # (c) RE-CORRIDA — idempotente. SQLite no tiene ADD COLUMN IF NOT EXISTS: sin el guard
    #     de _aplicar_migracion esto sería 'duplicate column name' y abortaría el bootstrap.
    try:
        sq.asegurar_schema(str(tmp))
        _ok("[re-corrida] asegurar_schema es idempotente sobre una DB ya migrada")
    except Exception as exc:  # noqa: BLE001
        _fail(f"[re-corrida] asegurar_schema explotó: {type(exc).__name__}: {exc}")

    # (c2) EL CASO FEO: una DB estampada en v1 pero que YA tiene las columnas (dos
    #      sidecars sobre el mismo datadir). El guard de duplicate-column tiene que sanarla.
    sqlite3.connect(tmp).execute("PRAGMA user_version = 1").connection.commit()
    try:
        sq.asegurar_schema(str(tmp))
        _ok("[re-corrida] una DB v1 con las columnas YA puestas se sana sin abortar")
    except Exception as exc:  # noqa: BLE001
        _fail(f"[re-corrida] el guard de duplicate-column no cubrió el caso: {exc}")


def _sembrar_v1(path: Path) -> None:
    """Escribe una DB del cliente en el estado v1 REAL: `schema_sqlite.sql` de HEAD menos
    lo que agregó esta migración — o sea, la DB que un usuario YA TIENE en su máquina.

    Se recorta del texto real en vez de escribir una tabla `runs` a mano: una copia a mano
    envejece y termina probando una DB que nadie tiene. El corte va del `finished_at` (la
    última columna de v1) al cierre del CREATE de `runs`, más su índice nuevo.
    """
    import re
    texto = _AQUI.joinpath("schema_sqlite.sql").read_text(encoding="utf-8")
    v1, n = re.subn(r"(  finished_at TEXT),\n.*?\n\);",
                    r"\1\n);", texto, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("✗✗ no se pudo recortar el bloque `runs` de schema_sqlite.sql: "
                         "cambió su forma y esta siembra estaría probando otra cosa.")
    v1 = "\n".join(ln for ln in v1.splitlines() if "idx_runs_parent" not in ln)
    if any(c in v1 for c in COLUMNAS_SQLITE):
        raise SystemExit("✗✗ el recorte v1 todavía menciona las columnas nuevas.")
    conn = sqlite3.connect(path)
    conn.executescript(v1)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def main() -> int:
    print("═══ MIGRACIÓN MULTIAGENTE · LOS DOS DIALECTOS ═══")
    verificar_sqlite()
    if os.environ.get("MA_VERIFY_SKIP_PG"):
        print("\n── POSTGRES · SALTEADO por MA_VERIFY_SKIP_PG ──")
        _fail("postgres salteado: la migración NO se verificó en los DOS dialectos")
    else:
        verificar_postgres()
    print(f"\n{'✓ VERDE — la migración corre en los dos dialectos' if not _fallos else ''}"
          f"{chr(10).join('✗ ' + f for f in _fallos) if _fallos else ''}")
    return 1 if _fallos else 0


if __name__ == "__main__":
    sys.exit(main())
