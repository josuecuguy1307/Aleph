"""
migrate.py — runner de migraciones VERSIONADAS para puppet_ai (T8-infra).

Reemplaza el "aplicar schema.sql entero" de init_db.py por una cadena ordenada y
auditada de migraciones. Cada archivo migrations/NNNN_nombre.sql se aplica UNA vez,
dentro de su propia transacción, y queda registrado en `schema_migrations`. Es
idempotente: re-correr no re-aplica nada. Detecta DRIFT (si el contenido de una
migración ya aplicada cambió) y lo reporta — una baseline/migración no se edita.

Uso (desde la raíz del repo o desde platform/db):
    python platform/db/migrate.py              # aplica las pendientes
    python platform/db/migrate.py status       # muestra aplicadas vs pendientes
    python platform/db/migrate.py --db otra_db # apunta a otra base (tests)

No inventa servidor: usa la misma conexión de db.py (Postgres existente de persona usuaria).
Crea la base si no existe (reusa init_db.ensure_database).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# permitir `from db import ...` aunque se invoque desde la raíz del repo
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from db import conn_params, get_conn  # noqa: E402

MIGRATIONS_DIR = _HERE / "migrations"

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     TEXT PRIMARY KEY,         -- 'NNNN' (prefijo numérico del archivo)
  name        TEXT NOT NULL,            -- nombre completo del archivo
  checksum    TEXT NOT NULL,            -- sha256 del contenido al aplicar (drift detection)
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _discover() -> list[tuple[str, Path]]:
    """Lista [(version, path)] de migrations/*.sql ordenadas por prefijo numérico."""
    if not MIGRATIONS_DIR.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = p.name.split("_", 1)[0]
        if not version.isdigit():
            raise RuntimeError(
                f"Migración con nombre inválido: {p.name} "
                f"(debe empezar con un prefijo numérico, ej. 0003_algo.sql)"
            )
        out.append((version, p))
    versions = [v for v, _ in out]
    if len(versions) != len(set(versions)):
        raise RuntimeError(f"Versiones de migración duplicadas: {versions}")
    return out


def _ensure_db(dbname: str | None) -> None:
    """Crea la base si falta (reusa la lógica probada de init_db)."""
    import init_db
    if dbname:
        init_db.DEFAULT_DB = dbname  # type: ignore[attr-defined]
    init_db.ensure_database()


def _applied(conn) -> dict[str, str]:
    """{version: checksum} de lo ya aplicado."""
    with conn.cursor() as cur:
        cur.execute(_SCHEMA_MIGRATIONS_DDL)
        conn.commit()
        cur.execute("SELECT version, checksum FROM schema_migrations ORDER BY version;")
        return {row[0]: row[1] for row in cur.fetchall()}


def status(dbname: str | None = None) -> dict:
    """Reporte: aplicadas, pendientes, y drift detectado."""
    conn = get_conn(dbname)
    try:
        applied = _applied(conn)
    finally:
        conn.close()

    discovered = _discover()
    pending, drift = [], []
    for version, path in discovered:
        text = path.read_text(encoding="utf-8")
        if version in applied:
            if applied[version] != _checksum(text):
                drift.append(path.name)
        else:
            pending.append(path.name)
    return {
        "applied": sorted(applied.keys()),
        "pending": pending,
        "drift": drift,
        "total": len(discovered),
    }


def migrate(dbname: str | None = None) -> list[str]:
    """Aplica las migraciones pendientes en orden. Devuelve las aplicadas en esta corrida."""
    _ensure_db(dbname)
    conn = get_conn(dbname)
    just_applied: list[str] = []
    try:
        applied = _applied(conn)
        for version, path in _discover():
            text = path.read_text(encoding="utf-8")
            if version in applied:
                if applied[version] != _checksum(text):
                    print(
                        f"[migrate] ⚠ DRIFT en {path.name}: el contenido cambió tras "
                        f"aplicarse. Una migración aplicada NO se edita — crea una nueva.",
                        file=sys.stderr,
                    )
                continue
            # transacción por migración: o entra entera + se registra, o no entra nada.
            try:
                with conn.cursor() as cur:
                    cur.execute(text)
                    cur.execute(
                        "INSERT INTO schema_migrations (version, name, checksum) "
                        "VALUES (%s, %s, %s);",
                        (version, path.name, _checksum(text)),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                print(f"[migrate] ✗ FALLÓ {path.name} — rollback, se detiene la cadena.",
                      file=sys.stderr)
                raise
            print(f"[migrate] ✓ aplicada {path.name}")
            just_applied.append(path.name)
    finally:
        conn.close()
    if not just_applied:
        print("[migrate] sin pendientes — la base está al día.")
    return just_applied


def main(argv: list[str]) -> int:
    dbname = None
    if "--db" in argv:
        i = argv.index("--db")
        dbname = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]

    if argv and argv[0] == "status":
        rep = status(dbname)
        print(f"base: {conn_params(dbname)['dbname']}  ({rep['total']} migraciones en disco)")
        print(f"  aplicadas: {rep['applied'] or '—'}")
        print(f"  pendientes: {rep['pending'] or '—'}")
        if rep["drift"]:
            print(f"  ⚠ DRIFT: {rep['drift']}")
        return 0

    migrate(dbname)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
