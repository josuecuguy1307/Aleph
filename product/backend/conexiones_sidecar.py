"""conexiones_sidecar — el runner del CENTRO DE CONEXIONES (gemelo de motor_sidecar).

Monta SÓLO lo que el Centro necesita, sin stubs: el Motor de Verdad (T1) + el motor de
requisitos (centro_conexiones) + /health. Sirve para dos cosas:

  1. el verify (verify_conexiones.mjs) contra un backend REAL de este worktree;
  2. correr el carril nuevo AL LADO del sidecar FROZEN instalado — el .app se congeló
     antes de que /v1/conexiones existiera, así que el frozen no puede servirlo. El
     verify proxea /v1/conexiones/* acá y TODO lo demás al frozen; los dos comparten
     ALEPH_DATA_DIR, así que ven la MISMA SQLite del cliente (una llave guardada por
     uno la lee el otro).

Levantar:
  ALEPH_ROLE=client ALEPH_DATA_DIR=/tmp/xxx PYTHONPATH=product/backend:platform \
    python -m uvicorn conexiones_sidecar:app --port 8223
"""
from typing import Any

from fastapi import FastAPI

from app.phase1.centro_conexiones import build_conexiones_router
from app.phase1.icons_router import build_icons_router
from app.phase1.motor_verdad import build_motor_router


def _get_conn() -> Any:
    """Conexión al store del cliente (SQLite vía la capa canónica de repo)."""
    from app.phase1 import repo
    return repo.get_conn()


app = FastAPI(title="conexiones-sidecar")
app.include_router(build_motor_router(get_conn=_get_conn))
app.include_router(build_conexiones_router(get_conn=_get_conn))
# [FIX-P2] /v1/icons DESDE FUENTE. El mapa curado de marcas (catalog/brand_domains.json)
# es un recurso del artefacto: el sidecar FROZEN sirve el que tenía cuando se congeló. Si
# la vara midiera los logos contra el frozen, mediría el mapa VIEJO — verde o rojo por el
# árbol equivocado, que es la trampa de siempre. Acá se sirve el de ESTE worktree.
app.include_router(build_icons_router())


@app.get("/health")
def health():
    return {"ok": True, "service": "conexiones-sidecar"}
