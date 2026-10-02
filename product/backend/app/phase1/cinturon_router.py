"""
cinturon_router.py — el disparo del calentado (CONTRACT-CONEXION-v1 §6).

`calentar_cinturon.calentar()` ya existía, probado, y no lo llamaba nadie. Esto es su
única ruta: la Sala la pega al ABRIR un agente y las cards se pintan solas leyendo el
registro. Cero lógica de medición acá — se llama, no se decide.

⚠️ UN CALENTADO POR AGENTE A LA VEZ. Abrir dos veces rápido el mismo agente (doble clic,
volver atrás y entrar de nuevo, dos pestañas) dispararía dos calentados en paralelo sobre
las MISMAS piezas: el doble de procesos MCP spawneados a la vez, el doble de rate limit
gastado, y dos escrituras compitiendo por la misma fila. El guard es en memoria y por
`puppet_id`: el segundo llamado no espera ni falla — devuelve `en_curso` y listo, porque
el primero ya está haciendo exactamente lo que el segundo pediría.

Vive en memoria a propósito: es estado de ESTE proceso, no del usuario. Si el sidecar
reinicia, no hay nada que recordar — no quedó ningún calentado a medias que reanudar, y
persistirlo sería guardar un proceso, que es justo lo que el §0 prohíbe.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from fastapi import APIRouter, Body, Header, HTTPException

logger = logging.getLogger("aleph.cinturon")

#: `puppet_id` de los calentados en curso EN ESTE proceso. Se limpia siempre en `finally`:
#: un set que se ensucia dejaría al agente sin poder calentarse nunca más.
_EN_CURSO: set = set()
_LOCK = threading.Lock()


def build_cinturon_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/cinturon", tags=["cinturon"])

    def _owner(authorization: Optional[str]) -> Optional[str]:
        from app.phase1 import motor_verdad as MV
        return MV._owner_from_session(authorization)

    @router.post("/calentar")
    def http_calentar(body: dict = Body(...),
                      authorization: Optional[str] = Header(default=None)):
        """Levanta, verifica y persiste las piezas HABILITADAS del agente. Body: {puppet_id}.

        Devuelve el resumen que `calentar` ya produce —por pieza: estado, causa, era, tool—
        más `apagadas` (la lápida), `sin_registro` y `sin_medir` (lo que quedó sobre el tope).
        """
        owner = _owner(authorization)
        if not owner or get_conn is None:
            raise HTTPException(status_code=401, detail="sin sesión")
        puppet_id = str((body or {}).get("puppet_id") or "").strip()
        if not puppet_id:
            raise HTTPException(status_code=422, detail="falta puppet_id")

        with _LOCK:
            if puppet_id in _EN_CURSO:
                # No es un error ni una espera: el primero está haciendo exactamente esto.
                return {"ok": True, "en_curso": True, "puppet_id": puppet_id}
            _EN_CURSO.add(puppet_id)
        try:
            from app.phase1 import calentar_cinturon as CAL
            resumen = CAL.calentar(puppet_id, owner=owner, get_conn=get_conn)
        except Exception as e:                     # noqa: BLE001 — frontera de la ruta
            # FALLO VISIBLE, JAMÁS MUDO: la Sala muestra el aviso con esta causa. Abrir el
            # agente NO se bloquea — el calentado es una mejora, no un requisito.
            logger.exception("calentar cinturón de %s", puppet_id)
            raise HTTPException(status_code=500,
                                detail=f"no pude calentar el cinturón: {type(e).__name__}")
        finally:
            with _LOCK:
                _EN_CURSO.discard(puppet_id)
        return {"ok": True, "en_curso": False, "puppet_id": puppet_id, **resumen}

    return router


__all__ = ["build_cinturon_router"]
