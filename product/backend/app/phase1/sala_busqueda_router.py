"""sala_busqueda_router.py — el puente de la Sala a la búsqueda web. [Gate 4 · F6 · §6.a.bis]

    POST /v1/sala/buscar    NDJSON: el progreso, las fuentes y el texto

POR QUÉ HACE FALTA UN PUENTE Y NO UN `fetch` DIRECTO. El pack corre en **su propio puerto
de loopback**, elegido en cada arranque (`platform/workspaces/pack.py`), y la Sala vive en
el del sidecar: un `fetch` del navegador a ese otro puerto es cross-origin, y hornear el
puerto sería exactamente lo que el `enter` existe para evitar. Así que el que habla con el
pack es el backend, que ya es su dueño.

NO SE REIMPLANTA EL `enter`: se llama. `ws_pack.levantar()` es idempotente y comparte por
huella (entrar dos veces no levanta dos packs), así que este endpoint puede pedirlo en
cada búsqueda sin costo y sin que la Sala tenga que acordarse de entrar primero.

**Sólo LA SALA.** `sala_busqueda` es `oculto` en el registro y no se ofrece a los seis
workspaces: sus stacks traen buscadores del oficio —arXiv en Ciencia, las fuentes
financieras en Finanzas— y genérico jamás pisa específico. Este router no es un buscador
transversal; es la capacidad base de la Sala.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_WS = "sala_busqueda"

#: Regla sellada: ninguna causa llega a una superficie sin copy.
_COPY = {
    "consulta_vacia": "Escribe algo para buscar.",
    "pack_no_arranco": "El buscador no llegó a levantarse.",
    "pack_no_instalado": "La búsqueda no viajó con esta instalación.",
    "motor_no_responde": "El buscador no contestó.",
}


class BuscarRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    puppet_id: Optional[str] = None
    chat_id: Optional[str] = None
    space_id: Optional[str] = None


class SearchProviderRequest(BaseModel):
    url: str


def build_sala_busqueda_router(*, get_conn: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/sala", tags=["sala"])

    @router.get("/search-provider")
    def search_provider_status(authorization: Optional[str] = Header(default=None)):
        from app.phase1.authz_http import owner_or_401
        from app.phase1.sala_search_provider import SearchProviderError, configured_url, validate_instance
        dueno = owner_or_401(authorization)
        url = configured_url(dueno)
        available = False
        reason = None
        if url:
            try:
                validate_instance(url)
                available = True
            except SearchProviderError as exc:
                reason = exc.copy
        return {"configured": available, "provider": "searxng" if url else None,
                "url": url or None, "reason": reason}

    @router.put("/search-provider")
    def search_provider_connect(body: SearchProviderRequest,
                                authorization: Optional[str] = Header(default=None)):
        from app.phase1.authz_http import owner_or_401
        from app.phase1.sala_search_provider import SearchProviderError, validate_instance
        from workspaces import memoria as ws_memoria
        from workspaces import pack as ws_pack
        dueno = owner_or_401(authorization)
        try:
            url = validate_instance(body.url)
        except SearchProviderError as exc:
            raise HTTPException(status_code=422, detail={
                "error": exc.code, "copy": exc.copy}) from exc
        ws_memoria.recordar(dueno, "sala_busqueda", deltas={"searxng_url": url})
        for ws in ("sala_busqueda", "sala_research"):
            ws_pack.apagar(ws, user_id=dueno, motivo="search provider changed")
        return {"configured": True, "provider": "searxng", "url": url}

    @router.delete("/search-provider")
    def search_provider_disconnect(authorization: Optional[str] = Header(default=None)):
        from app.phase1.authz_http import owner_or_401
        from workspaces import memoria as ws_memoria
        from workspaces import pack as ws_pack
        dueno = owner_or_401(authorization)
        ws_memoria.recordar(dueno, "sala_busqueda", deltas={"searxng_url": ""})
        for ws in ("sala_busqueda", "sala_research"):
            ws_pack.apagar(ws, user_id=dueno, motivo="search provider disconnected")
        return {"configured": False, "provider": None, "url": None}

    @router.post("/buscar")
    def buscar(body: BuscarRequest, request: Request,
               authorization: Optional[str] = Header(default=None)):
        from app.phase1.authz_http import owner_or_401
        dueno = owner_or_401(authorization,
                             detail="Inicia sesión para buscar en la web.",
                             copy="Inicia sesión para buscar.")
        consulta = (body.query or "").strip()
        if not consulta:
            raise HTTPException(status_code=400, detail={
                "error": "consulta_vacia", "copy": _COPY["consulta_vacia"]})

        from workspaces import pack as ws_pack
        # El registro se lee del módulo, NO por `_meta_ws`: esa función vive ANIDADA
        # dentro de `build_phase1_router` (`router.py:5331`) y no es importable. Un
        # `from … import _meta_ws` levanta en el arranque del backend, no acá.
        from app.phase1.router import _WORKSPACE_STACKS
        raw_meta = _WORKSPACE_STACKS.get(_WS)
        if not raw_meta:
            raise HTTPException(status_code=404, detail={
                "error": "workspace_desconocido",
                "detail": f"«{_WS}» no es un workspace de esta instalación"})
        from app.phase1.sala_search_provider import SearchProviderError, pack_meta
        try:
            meta = pack_meta(raw_meta, dueno)
        except SearchProviderError as exc:
            raise HTTPException(status_code=428, detail={
                "error": exc.code, "copy": exc.copy}) from exc
        # El `baseURL` del cerebro sale de ESTE pedido, por lo mismo que en el `enter`: el
        # sidecar recibe su puerto del shell en cada arranque, así que la única fuente que
        # no miente es la URL por la que el navegador nos está hablando ahora.
        base = str(request.base_url).rstrip("/")
        token = (authorization or "").split(" ", 1)[-1].strip()
        try:
            vivo = ws_pack.levantar(_WS, meta, base_aleph=base, user_id=dueno,
                                    token=token, puppet_id=body.puppet_id,
                                    chat_id=body.chat_id, space_id=body.space_id)
            internal_cap = ws_pack.capacidad_interna(_WS, meta, user_id=dueno)
        except ws_pack.PackError as exc:
            raise HTTPException(status_code=503, detail={
                "error": exc.causa, "detail": exc.detalle,
                "copy": _COPY.get(exc.causa, exc.causa)})

        def cable():
            """El NDJSON del pack, tal cual, sin re-traducir.

            El servidor del pack ya emite los sobres que la Sala pinta (`etapas.py` los
            produjo). Re-mapearlos acá sería un TERCER lugar donde vive el mismo contrato
            —ya son dos, declarados— y cada uno es una oportunidad de que diverjan.
            """
            import urllib.error
            import urllib.request
            pedido = urllib.request.Request(
                vivo["url"].rstrip("/") + "/buscar",
                data=json.dumps({"query": consulta}).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + internal_cap})
            try:
                respuesta = urllib.request.urlopen(pedido, timeout=900)
            except (urllib.error.URLError, OSError) as e:
                yield (json.dumps({"tipo": "fallo", "causa": "motor_no_responde",
                                   "copy": _COPY["motor_no_responde"],
                                   "detalle": type(e).__name__}) + "\n").encode()
                return
            with respuesta:
                for linea in respuesta:
                    yield linea

        return StreamingResponse(cable(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store",
                                          "X-Accel-Buffering": "no"})

    return router
