"""
chats_router.py — endpoints de los CHATS persistentes de la Sala (Ola UX-UNIVERSAL · A1/A2).

  POST   /v1/chats                     crea un chat {puppet_id?} → 201 {chat}
  GET    /v1/chats?puppet_id=…&workspace=…  lista del dueño scoped a composición Y a espacio
  GET    /v1/chats/search?q=…          búsqueda de texto entre los chats del dueño (A2)
  GET    /v1/chats/{id}                el chat + sus mensajes (rehidratación del front)
  PATCH  /v1/chats/{id}                renombrar {title}
  DELETE /v1/chats/{id}                borrar (CASCADE borra los mensajes)

AUTHZ (anti-IDOR, mismo patrón §4.5/_mem_gate): TODO endpoint exige sesión (Bearer) —
un chat siempre tiene dueño. El scope es SIEMPRE el owner de la SESIÓN, jamás un id
reclamado por el cliente; un chat ajeno responde 404 (indistinguible de inexistente).

El scope por composición usa el parámetro `puppet_id`: un UUID (chats de ESE Cuarto),
"none" (chats del agente inline), u omitido (todos los del dueño). Composición B no ve
los chats de A porque el owner va en el WHERE y el puppet en el scope.

El scope por ESPACIO usa `workspace`, con la misma forma: un id (el hilo de ese
workspace), "none" (los de La Sala, o sea los que no son de ningún workspace) u omitido
(todos). Y toda fila sale con `workspace` anotado, valga o no el scope. La atribución sale
del mapa `(dueño, workspace) → chat_id` de `workspaces/memoria.py`, porque la tabla `chats`
no tiene —ni va a tener— una columna de espacio.

La ESCRITURA de turnos NO pasa por acá: la persisten los endpoints de run
(/v1/puppets/run y /run/stream, router.py) cuando el body trae chat_id — el registro
nace del turno real, no de un POST suelto del front.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.phase1 import chats_repo


class ChatCreateRequest(BaseModel):
    puppet_id: Optional[str] = None


class ChatRenameRequest(BaseModel):
    title: str


def _owner_or_401(authorization: Optional[str]) -> str:
    """El guardián vive en `authz_http`, no acá. Este archivo tenía su propia copia y su
    propio `_bearer` —que para un `"Bearer "` pelado devolvía `""` en vez de `None`—."""
    from app.phase1.authz_http import owner_or_401
    return owner_or_401(authorization,
                        detail="Inicia sesión para ver tus chats.",
                        copy="Inicia sesión para ver tus chats.")


def _puppet_scope(puppet_id: Optional[str]) -> tuple[str, Optional[str]]:
    """'none' → chats del inline; UUID → chats de esa composición; omitido → todos."""
    if puppet_id is None or puppet_id == "":
        return "all", None
    if puppet_id.lower() == "none":
        return "inline", None
    return "puppet", puppet_id


def _workspace_scope(workspace: Optional[str]) -> tuple[str, Optional[str]]:
    """'none' → los hilos de La Sala; un id → el hilo de ESE espacio; omitido → todos.

    Gemelo exacto de `_puppet_scope`, y a propósito: es la misma pregunta («¿de qué es este
    hilo?») dicha sobre el otro eje, y el front ya sabe leer esa forma.
    """
    if workspace is None or workspace == "":
        return "all", None
    if workspace.lower() == "none":
        return "casa", None
    return "ws", workspace.strip().lower()


def _ws_por_chat(owner: str) -> dict[str, str]:
    """`{chat_id: workspace}` para este dueño, del mapa que ya existe.

    LA ATRIBUCIÓN NO SE INVENTA ACÁ. `workspaces/memoria.py` guarda `(dueño, workspace) →
    chat_id` desde la obra O5 (ley técnica 4) y `todos()` devuelve el mapa entero — una
    función que hasta hoy **no tenía un solo llamador**. Se lee y se invierte; no se
    consulta la tabla `chats`, que no sabe nada de espacios.

    FAIL-OPEN: la lista de chats no se cae porque la memoria no se pueda leer. Sin mapa el
    scope 'casa' no recorta (vuelve la conducta de hoy) y el campo viaja en `None` — que es
    «no sé», no «es de La Sala». Un fail-closed acá escondería los hilos del dueño por un
    JSON ilegible, y perder la lista es peor que verla mezclada.
    """
    try:
        from workspaces import memoria as ws_memoria
        mapa = ws_memoria.todos(owner) or {}
    except Exception:                                    # noqa: BLE001
        return {}
    salida: dict[str, str] = {}
    for ws, estado in mapa.items():
        cid = (estado or {}).get("chat_id")
        if cid:
            salida[str(cid)] = str(ws)
    return salida


def build_chats_router(*, get_conn: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/chats", tags=["chats"])

    @router.post("", status_code=201)
    def create_chat(body: ChatCreateRequest,
                    authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            if body.puppet_id:
                # la composición debe existir Y ser del dueño (anti-IDOR: no se abre
                # un chat "sobre" el Cuarto de otro)
                from app.phase1 import repo
                p_owner = repo.puppet_owner(conn, body.puppet_id)
                if p_owner is None or str(p_owner) != owner:
                    raise HTTPException(status_code=404,
                        detail={"error": "puppet_not_found",
                                "detail": "Esa composición no existe (o no es tuya)."})
            nuevo = chats_repo.create_chat(conn, user_id=owner, puppet_id=body.puppet_id)
            # ── LOS MCP DEL HILO, MIENTRAS EL DUEÑO ESCRIBE ──────────────────────────
            # El hilo se crea con la PRIMERA TECLA del composer (ver `asegurarHilo` en
            # sala-v2.js), no al mandar: entre esa tecla y el envío hay segundos de sobra
            # para los ~2,3 s que tarda en arrancar las 4 piezas atadas al workdir.
            # Fire-and-forget: si falla o tarda, el turno las arranca como siempre.
            try:
                from app.phase1 import precalentar_hilo
                precalentar_hilo.precalentar(str((nuevo or {}).get("id") or ""), owner=owner)
            except Exception:                          # noqa: BLE001 — nunca tumba el chat
                pass
            return nuevo
        finally:
            conn.close()

    @router.get("")
    def list_chats(puppet_id: Optional[str] = Query(default=None),
                   workspace: Optional[str] = Query(default=None),
                   limit: int = Query(default=100, ge=1, le=500),
                   authorization: Optional[str] = Header(default=None)):
        """La lista del dueño, scope-ada por composición Y por espacio.

        EL AGUJERO QUE TAPA, MEDIDO EN LA `aleph.db` REAL ANTES DE ESCRIBIRLO. Un dueño con
        82 chats: seis de ellos son los hilos de los seis workspaces —«Ciencia» 105 msgs,
        «Diseño» 63, «Educación» 48, «Oficina» 40, «Legal» 27, «Finanzas» 18— y los otros
        76 son de La Sala. Este endpoint los devolvía **los 82 juntos**, así que la lista de
        hilos de La Sala mostraba los seis espacios, y por venir ordenados por
        `updated_at DESC` se le paraban arriba de todo.

        No es que la Sala vea todo a propósito: su propio sidebar declara que sus hilos son
        los de `GET /v1/chats` «scope-ados por (user_id, puppet_id)» (`sala-v2/ui/sidebar.js`
        §1). Cuando se escribió eso los hilos de workspace no existían en la tabla — nacieron
        después, con la obra O5, y entraron a una lista cuyo scope nadie volvió a mirar.

        `workspace` es OPCIONAL y omitirlo devuelve todo: la vista global (`Historial.dc.html`,
        con sus chips de espacio) sigue viendo los 82, que es lo que esa pantalla quiere."""
        owner = _owner_or_401(authorization)
        scope, pid = _puppet_scope(puppet_id)
        ws_scope, ws = _workspace_scope(workspace)
        conn = get_conn()
        try:
            chats = chats_repo.list_chats(conn, owner, puppet_id=pid,
                                          puppet_scope=scope, limit=limit,
                                          ws_por_chat=_ws_por_chat(owner),
                                          workspace_scope=ws_scope, workspace=ws)
            return {"total": len(chats), "chats": chats}
        finally:
            conn.close()

    # OJO: /search ANTES de /{chat_id} — FastAPI matchea en orden de registro.
    @router.get("/search")
    def search_chats(q: str = Query(..., min_length=1, max_length=200),
                     puppet_id: Optional[str] = Query(default=None),
                     chat_id: Optional[str] = Query(default=None),
                     limit: int = Query(default=50, ge=1, le=200),
                     authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        scope, pid = _puppet_scope(puppet_id)
        conn = get_conn()
        try:
            if chat_id and chats_repo.get_chat_owned(conn, chat_id, owner) is None:
                raise HTTPException(status_code=404,
                    detail={"error": "chat_not_found", "detail": "Ese chat no existe."})
            hits = chats_repo.search_messages(conn, owner, q, puppet_id=pid,
                                              puppet_scope=scope, chat_id=chat_id,
                                              limit=limit)
            return {"q": q, "total": len(hits), "hits": hits}
        finally:
            conn.close()

    @router.get("/{chat_id}")
    def get_chat(chat_id: str,
                 limit: int = Query(default=500, ge=1, le=2000),
                 authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            chat = chats_repo.get_chat_owned(conn, chat_id, owner)
            if chat is None:
                raise HTTPException(status_code=404,
                    detail={"error": "chat_not_found", "detail": "Ese chat no existe."})
            chat["messages"] = chats_repo.list_messages(conn, chat_id, limit=limit)
            return chat
        finally:
            conn.close()

    @router.patch("/{chat_id}")
    def rename_chat(chat_id: str, body: ChatRenameRequest,
                    authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        title = (body.title or "").strip()
        if not title:
            raise HTTPException(status_code=422,
                detail={"error": "empty_title", "detail": "El título no puede quedar vacío."})
        conn = get_conn()
        try:
            if not chats_repo.rename_chat(conn, chat_id, owner, title):
                raise HTTPException(status_code=404,
                    detail={"error": "chat_not_found", "detail": "Ese chat no existe."})
            return {"ok": True, "id": chat_id, "title": title[:200]}
        finally:
            conn.close()

    @router.delete("/{chat_id}")
    def delete_chat(chat_id: str,
                    authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            if not chats_repo.delete_chat(conn, chat_id, owner):
                raise HTTPException(status_code=404,
                    detail={"error": "chat_not_found", "detail": "Ese chat no existe."})
            return {"ok": True, "id": chat_id}
        finally:
            conn.close()

    return router
