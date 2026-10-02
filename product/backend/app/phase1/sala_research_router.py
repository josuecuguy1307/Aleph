"""sala_research_router.py — el puente de la Sala al modo largo. [Gate 4 · F6 · §6.f]

    POST /v1/sala/investigar         NDJSON: las etapas, el informe y sus fuentes
    POST /v1/sala/investigar/parar   la cancelación en vuelo

ES EL GEMELO DE `sala_busqueda_router.py`, Y ESO ES DELIBERADO. Su sesión ya resolvió el
problema de fondo y las decisiones valen igual acá:

  · **Puente y no `fetch` directo.** El pack corre en su propio puerto de loopback,
    elegido en cada arranque (`platform/workspaces/pack.py`), y la Sala vive en el del
    sidecar: un `fetch` del navegador a ese otro puerto es cross-origin, y hornear el
    puerto sería exactamente lo que el `enter` existe para evitar.
  · **No se reimplanta el `enter`: se llama.** `ws_pack.levantar()` es idempotente y
    comparte por huella, así que se puede pedir en cada obra sin costo y sin que la Sala
    tenga que acordarse de entrar primero.
  · **El NDJSON del pack pasa tal cual.** `platform/sala/research/etapas.py` ya produjo
    los sobres que la Sala pinta; re-mapearlos acá sería un TERCER lugar donde vive el
    mismo contrato.

**Sólo LA SALA.** `sala_research` es `oculto` en el registro y no se ofrece a los seis
workspaces: §6.f lo sella —«a los VERTICALES no llega por default»—, y la línea que lo hace
cumplir es esa, no una condición acá.

──────────────────────────────────────────────────────────────────────────────────────
LO QUE ESTE PUENTE TIENE Y EL DE BÚSQUEDA NO: **PARAR**

Una búsqueda web tarda segundos; un deep research corre **minutos**. Sin poder pararlo es
inusable, y un botón que no para es peor que no tenerlo. El servidor del pack ya implementa
la cancelación cooperativa —medida: corta en 31 ms— pero es un `POST` a SU puerto, o sea
que sin este segundo endpoint la Sala no tendría cómo pedirla.

**EL `obra_id` LO PONE LA SALA, NO ESTE ROUTER, Y ES LA DECISIÓN QUE HACE QUE ESTO
FUNCIONE.** El servidor del pack lo publica en su primera línea NDJSON (`{"tipo":"abre"}`),
que viaja al navegador antes que ninguna otra: para cuando el usuario puede apretar parar,
la Sala ya lo tiene. La alternativa —que el backend recordara «la obra viva de este
usuario»— sería estado de sesión en un proceso que no lo tiene, y se rompería con dos
pestañas abiertas. Acá el router es sin memoria: recibe el id y lo reenvía.

**Y `levantar()` SE VUELVE A LLAMAR PARA PARAR.** No hace falta guardar la URL del pack:
la misma idempotencia que deja pedirlo en cada obra deja recuperarlo acá. Guardar la URL
sería una copia del estado del pack que puede quedar vieja justo cuando más importa (el
pack se reinició y la obra que se quiere parar ya no existe) — y en ese caso lo honesto
es lo que contesta el propio servidor: `encontrada: false`.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_WS = "sala_research"

#: Regla sellada: ninguna causa llega a una superficie sin copy.
#:
#: ⚠️ ESTAS COPIAS NO ALCANZAN SOLAS, y es la lección que su hermano pagó en pantalla: el
#: router manda su `copy`, pero **la Sala resuelve por `causas-catalogo.js`**, y una causa
#: que esa tabla no conoce se pinta «… · sin copy propia todavía» aunque acá esté escrita.
#: Las de este modo están declaradas allá también. La vara no ve esto: sólo se ve mirando.
_COPY = {
    "consulta_vacia": "Hace falta una consulta para investigar.",
    "pack_no_arranco": "El modo de investigación no llegó a levantarse.",
    "pack_no_instalado": "La investigación a fondo no viajó con esta instalación.",
    "motor_no_responde": "El motor de investigación no contestó.",
}

#: Cuánto se le espera al pack. Un deep research corre minutos —el propio LDR documenta
#: «1-5 minutes» para una obra corta (`mcp/server.py:367-368`)— y las estrategias largas
#: con varias iteraciones pasan de ahí. 15 minutos es el mismo techo que su hermano usa
#: para una búsqueda, y acá es el número CHICO de los dos: quien corta antes es el usuario
#: con el botón de parar, que existe justo para eso.
_TECHO_S = 900


class InvestigarRequest(BaseModel):
    query: str
    #: `resumen` (rápido) o `informe` (el largo, `detailed_research`). El default es el
    #: barato: pedir el caro sin haberlo pedido sería gastar minutos del usuario por un
    #: default.
    modo: Optional[str] = None
    estrategia: Optional[str] = None
    iteraciones: Optional[int] = None
    user_id: Optional[str] = None
    puppet_id: Optional[str] = None
    chat_id: Optional[str] = None
    space_id: Optional[str] = None


class PararRequest(BaseModel):
    obra_id: str
    user_id: Optional[str] = None


def build_sala_research_router(*, get_conn: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/sala", tags=["sala"])

    def _pack_vivo(request: Request, dueno: str, authorization: Optional[str],
                   cuerpo: Any) -> dict:
        """Levanta (o reusa) el pack y devuelve lo que `levantar()` contesta.

        Es el trozo que los dos endpoints comparten. Se extrae acá y no se copia dos veces
        porque la segunda copia es donde empiezan a divergir.
        """
        from workspaces import pack as ws_pack
        # El registro se lee del módulo, NO por `_meta_ws`: esa función vive ANIDADA dentro
        # de `build_phase1_router` y no es importable. Un `from … import _meta_ws` levanta
        # en el arranque del backend, no acá. (Lo aprendió el router de búsqueda.)
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
            return ws_pack.levantar(
                _WS, meta, base_aleph=base, user_id=dueno, token=token,
                puppet_id=getattr(cuerpo, "puppet_id", None),
                chat_id=getattr(cuerpo, "chat_id", None),
                space_id=getattr(cuerpo, "space_id", None))
        except ws_pack.PackError as exc:
            raise HTTPException(status_code=503, detail={
                "error": exc.causa, "detail": exc.detalle,
                "copy": _COPY.get(exc.causa, exc.causa)})

    @router.post("/investigar")
    def investigar(body: InvestigarRequest, request: Request,
                   authorization: Optional[str] = Header(default=None)):
        from app.phase1.authz_http import owner_or_401
        dueno = owner_or_401(authorization,
                             detail="Inicia sesión para investigar en la web.",
                             copy="Inicia sesión para investigar.")
        consulta = (body.query or "").strip()
        if not consulta:
            raise HTTPException(status_code=400, detail={
                "error": "consulta_vacia", "copy": _COPY["consulta_vacia"]})

        vivo = _pack_vivo(request, dueno, authorization, body)
        from workspaces import pack as ws_pack
        from app.phase1.router import _WORKSPACE_STACKS
        internal_cap = ws_pack.capacidad_interna(_WS, _WORKSPACE_STACKS[_WS], user_id=dueno)

        def cable():
            """El NDJSON del pack, tal cual, sin re-traducir.

            El servidor del pack ya emite los sobres que la Sala pinta (`etapas.py` los
            produjo, con las 38 fases del motor mapeadas a las 6 etapas gruesas). Re-mapear
            acá sería un TERCER lugar donde vive el mismo contrato —ya son dos, declarados—
            y cada copia es una oportunidad de que diverjan.
            """
            import urllib.error
            import urllib.request
            pedido = urllib.request.Request(
                vivo["url"].rstrip("/") + "/research",
                data=json.dumps({
                    "query": consulta,
                    "modo": (body.modo or "resumen"),
                    "estrategia": body.estrategia,
                    "iteraciones": body.iteraciones,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + internal_cap})
            try:
                respuesta = urllib.request.urlopen(pedido, timeout=_TECHO_S)
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

    @router.post("/investigar/parar")
    def parar(body: PararRequest, request: Request,
              authorization: Optional[str] = Header(default=None)):
        """Para una obra en vuelo. Idempotente, y honesto sobre si había algo que parar.

        **Nunca es un error.** Pedir parar algo que ya terminó es lo NORMAL —el usuario
        aprieta justo cuando llegaba el informe— y contestar 4xx ahí convertiría un final
        feliz en un cartel rojo. Es la decisión #1 de `turnos_http.py`, y se respeta acá:
        200 con `encontrada: false`.
        """
        from app.phase1.authz_http import owner_or_401
        dueno = owner_or_401(authorization,
                             detail="Inicia sesión para parar la investigación.",
                             copy="Inicia sesión para parar la investigación.")
        obra_id = (body.obra_id or "").strip()
        if not obra_id:
            raise HTTPException(status_code=400, detail={
                "error": "obra_desconocida",
                "copy": "No sé qué investigación parar."})

        vivo = _pack_vivo(request, dueno, authorization, body)
        from workspaces import pack as ws_pack
        from app.phase1.router import _WORKSPACE_STACKS
        internal_cap = ws_pack.capacidad_interna(_WS, _WORKSPACE_STACKS[_WS], user_id=dueno)

        import urllib.error
        import urllib.request
        pedido = urllib.request.Request(
            vivo["url"].rstrip("/") + "/cancelar",
            data=json.dumps({"obra_id": obra_id}).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json",
                                    "Authorization": "Bearer " + internal_cap})
        try:
            # RELOJ CORTO A PROPÓSITO. Parar es una escritura en un dict bajo un lock; si
            # tardara más de unos segundos, el pack está en un estado en el que la respuesta
            # ya no le sirve a nadie. Medido: el servidor corta en 31 ms.
            with urllib.request.urlopen(pedido, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as e:
            raise HTTPException(status_code=503, detail={
                "error": "motor_no_responde", "copy": _COPY["motor_no_responde"],
                "detail": type(e).__name__})

    return router
