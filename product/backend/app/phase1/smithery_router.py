"""
smithery_router.py — BLOCK D · FASE 2 · endpoints HTTP de conexiones por-usuario a Smithery.

Capa fina sobre `platform/connectors/smithery/connections.py` (la lógica REST ya verificada
en vivo). La Sala llama estos endpoints para: arrancar/consultar la conexión de un usuario a
un server MCP de Smithery y obtener el `setup_url` (authURL) que el usuario visita para
autorizar el servicio. Smithery brokea el OAuth y refresca; Aleph nunca ve la cred del servicio.

Auth: anti-IDOR por sesión (repo.session_owner del Bearer) == el user_id reclamado, idéntico a
/v1/keys. La GATEWAY key sale del broker BYOK del owner de plataforma (NO del end-user, NO hardcode).

NO expone tools al agente (eso es FASE 3) ni toca el send-gate (FASE 4).
Registrar en main.py con:  app.include_router(build_smithery_router(get_conn=_phase1_get_conn))
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CONNECTIONS_PY = _REPO_ROOT / "platform" / "connectors" / "smithery" / "connections.py"


def _load_connections():
    import aleph_paths
    return aleph_paths.load_module_by_path("puppet_smithery_connections", _CONNECTIONS_PY)


class ConnectRequest(BaseModel):
    user_id: str
    server: str                       # qualifiedName de Smithery (ej. "github", "@owner/name")
    display_name: Optional[str] = None


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    return authorization.split(" ", 1)[1] if " " in authorization else authorization


def build_smithery_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter()
    C = _load_connections()

    def _conn():
        from app.phase1 import repo
        return (get_conn or repo.get_conn)()

    def _authorize(claimed_user_id: str, authorization: Optional[str]) -> str:
        from app.phase1 import repo
        owner = repo.session_owner(_bearer(authorization))
        if owner is None:
            raise HTTPException(status_code=401,
                detail={"error": "no_session", "detail": "Inicia sesión para continuar."})
        if str(owner) != str(claimed_user_id):
            raise HTTPException(status_code=403,
                detail={"error": "forbidden", "detail": "Esa cuenta no es la tuya."})
        return owner

    def _require(authorization: Optional[str]) -> str:
        """[hallazgo #1] identidad de la SESIÓN, sin un user_id declarado. 401 si falta."""
        from app.phase1 import repo
        owner = repo.session_owner(_bearer(authorization))
        if owner is None:
            raise HTTPException(status_code=401,
                detail={"error": "no_session", "detail": "Inicia sesión para continuar."})
        return owner

    def _resolver():
        from app.phase1 import repo
        return C.make_resolver(get_conn or repo.get_conn)

    def _guard():
        """Sin gateway key configurada → 503 honesto (fail-closed), no 500 opaco."""
        try:
            C._gateway_key(_resolver())
        except C.SmitheryError as e:
            raise HTTPException(status_code=503,
                detail={"error": "smithery_gateway_missing", "detail": str(e)})

    # ── POST: arrancar/refrescar la conexión por-usuario → {state, setup_url} ──────────
    @router.post("/v1/smithery/connections", status_code=200)
    def ensure(body: ConnectRequest, authorization: Optional[str] = Header(default=None)):
        _authorize(body.user_id, authorization)
        _guard()
        try:
            return C.ensure_connection(body.user_id, body.server, _resolver(),
                                       display_name=body.display_name)
        except C.SmitheryError as e:
            raise HTTPException(status_code=502,
                detail={"error": "smithery_error", "detail": str(e)})

    # ── GET: estado actual (autoritativo en Smithery) ─────────────────────────────────
    @router.get("/v1/smithery/connections/{server:path}")
    def status(server: str, authorization: Optional[str] = Header(default=None)):
        # [hallazgo #1] user_id sale de la SESIÓN, no del query.
        user_id = _require(authorization)
        _guard()
        try:
            return C.get_status(user_id, server, _resolver())
        except C.SmitheryError as e:
            raise HTTPException(status_code=502, detail={"error": "smithery_error", "detail": str(e)})

    # ── DELETE: desconectar ───────────────────────────────────────────────────────────
    @router.delete("/v1/smithery/connections/{server:path}", status_code=200)
    def disconnect(server: str, authorization: Optional[str] = Header(default=None)):
        user_id = _require(authorization)  # [hallazgo #1] identidad de la sesión
        _guard()
        try:
            return {"deleted": C.delete_connection(user_id, server, _resolver())}
        except C.SmitheryError as e:
            raise HTTPException(status_code=502, detail={"error": "smithery_error", "detail": str(e)})

    return router


__all__ = ["build_smithery_router"]
