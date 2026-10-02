"""authz_http.py — la mitad HTTP de `authz`. El 401, en un solo lugar.

POR QUÉ EXISTE ESTE ARCHIVO Y NO UNA FUNCIÓN MÁS EN `authz.py`: porque `authz` declara
en su propio encabezado que **es puro y no importa FastAPI**, para que los tests lo
ejerciten sin levantar el server. Esa decisión se respeta. Lo que faltaba era el otro
lado: el que traduce «no hay dueño» a una respuesta HTTP.

QUÉ RESOLVÍA CADA ROUTER POR SU CUENTA. `_owner_or_401` estaba escrito **tres veces**
—`chats_router`, `instructions_router` y `busqueda_router`, ésta última enterrada
adentro de `build_busqueda_router`— y `_bearer` **seis**. Las seis copias de `_bearer`
además NO eran equivalentes al canónico: para un header `"Bearer "` pelado devuelven
`""` donde `authz.parse_bearer` devuelve `None`.

EL COPY VIAJA CON LA CAUSA. Cada superficie pasa el suyo (`Inicia sesión para ver tus
chats.` no sirve en búsqueda), pero la FORMA del error es una sola: `error:"no_session"`
+ `detail` + `copy`. Regla sellada: ninguna causa llega a una superficie sin copy.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from app.phase1 import authz

#: Lo que se dice cuando la superficie no trae su propio copy.
_COPY_DEFECTO = "Inicia sesión para continuar."


def owner_or_401(authorization: Optional[str], *,
                 detail: str = "Inicia sesión para continuar.",
                 copy: Optional[str] = None,
                 query_token: Optional[str] = None) -> str:
    """El dueño de la sesión, o 401. **La identidad sale del token, nunca del body.**

    `query_token` existe sólo para el camino SSE (un `EventSource` no manda headers);
    los routers normales no lo pasan. Ver `authz.pick_token`.
    """
    owner = authz.require_actor(authorization, query_token)
    if owner is None:
        raise HTTPException(status_code=401, detail={
            "error": "no_session",
            "detail": detail,
            "copy": copy or _COPY_DEFECTO})
    return str(owner)


__all__ = ["owner_or_401"]
