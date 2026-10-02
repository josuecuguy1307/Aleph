"""busqueda_router.py — buscar en lo propio. [Convergencia · Superficie 5]

  GET /v1/busqueda?q=…&space_id=…     hilos + mensajes + artefactos del dueño, en UNA
  POST /v1/busqueda/reindexar          rehace el índice de quien pide

AUTHZ: mismo patrón que `chats_router` — todo endpoint exige sesión y el scope es SIEMPRE
el dueño de la sesión, jamás un id que mande el cliente. Acá hay una vuelta de tuerca:
el dueño no es un filtro que este archivo agrega, es un **token del MATCH** que
`busqueda.indice` exige para construir la consulta. Si esta capa se olvidara de pasarlo,
la búsqueda **levanta**; no devuelve de más. Ver el encabezado de `platform/busqueda/indice.py`.

Por qué eso importa acá y no es paranoia: la búsqueda de esta casa la va a llamar también
el agente (en Finanzas ya es una tool `repeatable=True` que el modelo invoca solo), así
que el scope no puede vivir en la pantalla.

**Ningún workspace pierde su búsqueda.** Legal sigue buscando en su matter, Ciencia en su
proyecto, Educación en su conocimiento. Esto se suma encima.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query

_MIN_Q = 2      # el mismo mínimo que la paleta de OpenScience (`CommandPalette.tsx:99`)


def build_busqueda_router(*, get_conn: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/busqueda", tags=["busqueda"])

    def _owner_or_401(authorization: Optional[str]) -> str:
        """Estaba escrito acá adentro, con su propio parseo del Bearer. Ahora llama al
        único —`authz_http.owner_or_401`—; el copy sigue siendo el de esta superficie."""
        from app.phase1.authz_http import owner_or_401
        return owner_or_401(authorization,
                            detail="Inicia sesión para buscar en lo tuyo.",
                            copy="Inicia sesión para buscar.")

    @router.get("")
    def buscar(q: str = Query(..., min_length=_MIN_Q, max_length=200),
               space_id: Optional[str] = Query(default=None),
               limite: int = Query(default=20, ge=1, le=100),
               authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        from busqueda import indice
        try:
            return indice.buscar(owner, q, space_id=space_id, limite=limite)
        except ValueError as e:
            # El índice rechazó el scope. Es fail-closed funcionando, no un 500: la sesión
            # resolvió a algo que no sirve como dueño. Causa tipada y copy, porque ninguna
            # causa llega a una superficie sin copy.
            raise HTTPException(status_code=400, detail={
                "error": "scope_invalido", "detail": str(e),
                "copy": "No pudimos determinar de quién es esta búsqueda."})

    @router.post("/reindexar")
    def reindexar(authorization: Optional[str] = Header(default=None)):
        """Rehace el índice DE QUIEN PIDE. No hay forma de reindexar a otro.

        Se reconstruye entero y no se mantiene con triggers: el mensaje del agente se
        reescribe cuando un turno se re-emite (`chats_repo.py:132`) y el artefacto se
        reescribe al editarlo, así que un índice incremental sin huella por documento
        quedaría mintiendo — que es exactamente el defecto medido en el de Finanzas, al
        que le falta el trigger de UPDATE.
        """
        owner = _owner_or_401(authorization)
        from busqueda import indice
        conn = get_conn()
        try:
            return {"ok": True, "indexado": indice.reconstruir(conn, owner)}
        finally:
            conn.close()

    return router
