"""
backup.py — backups durables de puppet_ai vía pg_dump (T8-infra).

Un crash de Postgres o un DROP accidental no debe perder el trabajo. Este script
hace un dump en formato CUSTOM (-Fc, comprimido y restaurable selectivamente) a
platform/db/backups/, con rotación (conserva los últimos N) y un restore documentado
y ejecutable.

Uso:
    python platform/db/backup.py                 # crea un backup + rota
    python platform/db/backup.py --list          # lista los backups existentes
    python platform/db/backup.py --restore <f>   # restaura desde un .dump (DESTRUCTIVO)

Config (env, con defaults):
    PUPPET_DB_BACKUP_DIR   default platform/db/backups
    PUPPET_DB_BACKUP_KEEP  default 7  (cuántos backups conservar al rotar)
    PG_HOST/PG_PORT/PG_USER/PG_DB/PG_PASSWORD  (los mismos que db.py)

Requiere `pg_dump`/`pg_restore` en el PATH (vienen con el Postgres instalado).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from db import conn_params  # noqa: E402


def _backup_dir() -> Path:
    d = Path(os.environ.get("PUPPET_DB_BACKUP_DIR", str(_HERE / "backups")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _env_with_pw() -> dict:
    env = dict(os.environ)
    pw = os.environ.get("PG_PASSWORD")
    if pw:
        env["PGPASSWORD"] = pw
    return env


def _conn_flags() -> list[str]:
    p = conn_params()
    return ["-h", str(p["host"]), "-p", str(p["port"]), "-U", str(p["user"])]


def create() -> Path:
    """Crea un dump -Fc con timestamp UTC. Devuelve el path."""
    p = conn_params()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = _backup_dir() / f"{p['dbname']}_{ts}.dump"
    cmd = ["pg_dump", *_conn_flags(), "-d", str(p["dbname"]), "-Fc", "-f", str(out)]
    res = subprocess.run(cmd, env=_env_with_pw(), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"pg_dump falló (rc={res.returncode}): {res.stderr.strip()}")
    size = out.stat().st_size
    print(f"[backup] ✓ {out.name} ({size} bytes)")
    return out


def rotate(keep: int | None = None) -> list[Path]:
    """Conserva los `keep` backups más nuevos; borra el resto. Devuelve los borrados."""
    keep = keep if keep is not None else int(os.environ.get("PUPPET_DB_BACKUP_KEEP", "7"))
    dumps = sorted(_backup_dir().glob("*.dump"), key=lambda x: x.stat().st_mtime, reverse=True)
    removed = []
    for old in dumps[keep:]:
        old.unlink()
        removed.append(old)
        print(f"[backup] rotación: borrado {old.name}")
    return removed


def list_backups() -> list[Path]:
    dumps = sorted(_backup_dir().glob("*.dump"), key=lambda x: x.stat().st_mtime, reverse=True)
    for d in dumps:
        mb = d.stat().st_size / 1_048_576
        print(f"  {d.name}  ({mb:.2f} MB)")
    if not dumps:
        print("  (sin backups)")
    return dumps


def restore(dump_file: str) -> None:
    """Restaura un .dump sobre puppet_ai (DESTRUCTIVO: --clean --if-exists)."""
    p = conn_params()
    f = Path(dump_file)
    if not f.is_absolute():
        f = _backup_dir() / dump_file
    if not f.exists():
        raise FileNotFoundError(f"no existe el dump: {f}")
    cmd = ["pg_restore", *_conn_flags(), "-d", str(p["dbname"]),
           "--clean", "--if-exists", "--no-owner", str(f)]
    res = subprocess.run(cmd, env=_env_with_pw(), capture_output=True, text=True)
    # pg_restore emite warnings a stderr aun en éxito; rc!=0 es el fallo real.
    if res.returncode != 0:
        raise RuntimeError(f"pg_restore falló (rc={res.returncode}): {res.stderr.strip()}")
    print(f"[backup] ✓ restaurado desde {f.name}")


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--list":
        list_backups()
        return 0
    if argv and argv[0] == "--restore":
        if len(argv) < 2:
            print("uso: backup.py --restore <archivo.dump>", file=sys.stderr)
            return 2
        restore(argv[1])
        return 0
    create()
    rotate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
