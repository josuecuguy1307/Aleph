"""
db_boot.py — bootstrap del schema del CLIENTE en el arranque + estado FALLO VISIBLE.

[GAP-DEV-DESKTOP §2.1] La .app instalada corría con una DB de CERO tablas: nadie
ejecutaba el schema en el boot del cliente y el server SERVÍA IGUAL, con cada
"no such table" mudo por stderr. Este módulo es lo que faltaba: el lifespan llama
`asegurar()` ANTES de arrancar lo que escribe (workers → job_queue, purga → users).

REGLA (nueva, de este fix): **FALLO VISIBLE, JAMÁS MUDO.** Si la DB no se puede
abrir o el schema queda incompleto, el error queda registrado acá (`boot_error()`),
main.py lo convierte en 503 claro en TODA la superficie (y /health lo reporta), y
workers/purga NO arrancan. Servir "como si nada" fue exactamente el bug.

Guardas (mismo criterio que bootstrap.py):
  - rol control            → no-op (Postgres migra con migrate.py, plano de control).
  - pytest                 → no-op salvo PUPPET_DB_BOOTSTRAP=1 explícito: la suite no
                             debe tocar la DB real del dev por instanciar la app; el
                             test del boot SÍ lo fuerza contra un ALEPH_DATA_DIR tmp.
  - PUPPET_DB_BOOTSTRAP=0  → apagado explícito (ops).
"""

from __future__ import annotations

import os
import sys
from typing import Optional

_error: Optional[str] = None


def boot_error() -> Optional[str]:
    """El error de bootstrap de DB de ESTE proceso, o None si la DB está sana
    (o el bootstrap no aplicaba: control / pytest / apagado explícito)."""
    return _error


def limpiar() -> None:
    """Borra el estado de error (shutdown del lifespan — el proceso ya no sirve).
    En prod da igual (el proceso muere); en tests evita que un boot roto de un
    TestClient contamine al siguiente."""
    global _error
    _error = None


def _habilitado() -> bool:
    flag = (os.environ.get("PUPPET_DB_BOOTSTRAP") or "").strip()
    if flag == "0":
        return False
    if flag == "1":
        return True
    return "pytest" not in sys.modules


def asegurar() -> bool:
    """Corre el bootstrap si corresponde. True = se puede servir con DB; False = DB
    ROTA — el motivo ya quedó en `boot_error()` y el caller NO debe arrancar
    workers/purga ni servir como si nada."""
    global _error
    _error = None
    if not _habilitado():
        return True
    try:
        from app.phase1 import repo
        resumen = repo.asegurar_schema_cliente()
        if resumen is not None:
            print(f"[db] schema cliente v{resumen['version']} OK — "
                  f"{resumen['tablas']} tablas en {resumen['path']}", flush=True)
        return True
    except Exception as exc:
        _error = f"{type(exc).__name__}: {exc}"
        print(f"[db] 🔴 BOOTSTRAP DE SCHEMA FALLÓ — la superficie pasa a 503 visible "
              f"y workers/purga NO arrancan: {_error}", flush=True)
        return False
