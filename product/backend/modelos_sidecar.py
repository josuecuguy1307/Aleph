"""modelos_sidecar — el runner del CENTRO DE MODELOS (gemelo de conexiones_sidecar).

Monta SÓLO lo que la pantalla de Modelos necesita, sin stubs: el Motor de Verdad (T1,
para el semáforo de los hosteados) + el centro de modelos (FIX-P8) + /health.

Sirve para dos cosas, las mismas que su gemelo:

  1. el verify (`verify_modelos.mjs`) contra un backend REAL de ESTE worktree;
  2. correr el carril nuevo AL LADO del sidecar FROZEN instalado — el .app se congeló
     antes de que /v1/modelos existiera, así que el frozen NO puede servirlo. El verify
     proxea /v1/modelos/* acá y todo lo demás al frozen; comparten ALEPH_DATA_DIR, así
     que ven la MISMA SQLite y la MISMA carpeta de modelos descargados.

Levantar:
  ALEPH_ROLE=client ALEPH_DATA_DIR=/tmp/xxx PYTHONPATH=product/backend:platform \\
    python -m uvicorn modelos_sidecar:app --port 8279
"""
from typing import Any

from fastapi import FastAPI

from app.phase1.centro_modelos import build_modelos_router
from app.phase1.icons_router import build_icons_router
from app.phase1.motor_verdad import build_motor_router


def _get_conn() -> Any:
    """Conexión al store del cliente (SQLite vía la capa canónica de repo)."""
    from app.phase1 import repo
    return repo.get_conn()


app = FastAPI(title="modelos-sidecar")
app.include_router(build_motor_router(get_conn=_get_conn))
app.include_router(build_modelos_router(get_conn=_get_conn))
# /v1/icons DESDE FUENTE, por la misma razón que en conexiones_sidecar: el mapa curado de
# marcas es un recurso del artefacto y el frozen sirve el que tenía al congelarse. Medir
# los logos contra él sería medir el árbol equivocado.
app.include_router(build_icons_router())


@app.get("/health")
def health():
    return {"ok": True, "service": "modelos-sidecar"}
