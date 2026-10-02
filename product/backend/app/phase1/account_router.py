"""
account_router.py — MEMORIA DE CUENTA (Sistema 2). GATE de PROPUESTA (orden 5, WRITE) + panel
VER/PODAR (orden 6, READ/DELETE).

  Orden 5 (WRITE-path · el gate):
  GET    /v1/account/proposals            propuestas PENDIENTES del dueño (source='agent',
                                          pinned=FALSE) — el "¿querés que tu equipo recuerde esto?".
  POST   /v1/account/proposals/{id}/confirm   EL GATE: el humano confirma → el hecho pasa a
                                          ACTIVO (pinned=TRUE) y recién ahí lo leen sus agentes.
  DELETE /v1/account/proposals/{id}       rechaza (borra) una propuesta pendiente.

  Orden 6 (panel VER + PODAR):
  GET    /v1/account/memories             hechos ACTIVOS (pinned=TRUE) que TODOS los agentes del
                                          dueño leen — con source/meta para el badge kind/prov.
  DELETE /v1/account/memories/{id}        PODAR un hecho activo (borrado atómico scopeado por dueño).

AUTHZ: sesión SIEMPRE (la cuenta tiene dueño); anti-IDOR ESTRICTO por owner_id = users.id (la
memoria/propuesta de OTRO usuario == inexistente, 404 indistinguible). No hay auto-write: una
propuesta sólo se vuelve activa por confirm explícito (la captura del run la deja INERTE). La CUENTA
jamás cruza de usuario (invariante #4): cada operación filtra por el owner de la sesión.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    a = authorization.strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else (a or None)


def _owner_or_401(authorization: Optional[str]) -> str:
    from app.phase1 import repo
    owner = repo.session_owner(_bearer(authorization))
    if owner is None:
        raise HTTPException(status_code=401,
            detail={"error": "no_session", "detail": "Inicia sesión para ver tu memoria de cuenta."})
    return str(owner)


def build_account_router(*, get_conn: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/account", tags=["account"])

    @router.get("/proposals")
    def list_proposals(authorization: Optional[str] = Header(default=None)):
        """Propuestas pendientes (inertes) de hechos de cuenta para confirmar/rechazar."""
        from app.phase1 import repo
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            rows = repo.list_account_proposals(conn, owner)
            return {"total": len(rows), "proposals": rows}
        finally:
            conn.close()

    @router.post("/proposals/{memory_id}/confirm")
    def confirm_proposal(memory_id: str, authorization: Optional[str] = Header(default=None)):
        """EL GATE: el humano confirma un hecho propuesto → pinned=TRUE (recién ahí sus agentes lo
        leen). Sólo una propuesta PENDIENTE y PROPIA (anti-IDOR); ajena/ya-confirmada → 404."""
        from app.phase1 import repo
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            row = repo.confirm_account_proposal(conn, memory_id, owner)
            if row is None:
                raise HTTPException(status_code=404,
                    detail={"error": "not_found",
                            "detail": "Esa propuesta no existe, ya la confirmaste, o no es tuya."})
            return {"ok": True, "confirmed": row}
        finally:
            conn.close()

    @router.delete("/proposals/{memory_id}")
    def reject_proposal(memory_id: str, authorization: Optional[str] = Header(default=None)):
        """Rechaza (borra) una propuesta pendiente propia. Un hecho ya confirmado NO se toca acá
        (podarlo es del panel, orden 6)."""
        from app.phase1 import repo
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            if not repo.reject_account_proposal(conn, memory_id, owner):
                raise HTTPException(status_code=404,
                    detail={"error": "not_found",
                            "detail": "Esa propuesta no existe, ya no está pendiente, o no es tuya."})
            return {"ok": True, "id": memory_id}
        finally:
            conn.close()

    # ── Orden 6 · panel VER + PODAR (la cara de la memoria de cuenta) ──
    @router.get("/memories")
    def list_memories(authorization: Optional[str] = Header(default=None)):
        """Los hechos de cuenta ACTIVOS (pinned=TRUE) del dueño — lo que TODOS sus agentes leen.
        Devuelve `source` y `meta` para que el panel pinte el badge kind/prov (quién lo trajo:
        el usuario directamente vs un agente propuso→confirmaste). Sólo del owner de la sesión."""
        from app.phase1 import repo
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            rows = repo.list_account_memories(conn, owner, pinned_only=True)
            usage = repo.account_memory_usage(conn, owner)
            return {"total": len(rows), "memories": rows, "usage": usage}
        finally:
            conn.close()

    @router.delete("/memories/{memory_id}")
    def prune_memory(memory_id: str, authorization: Optional[str] = Header(default=None)):
        """PODAR: borra un hecho de cuenta PROPIO (activo o no). Borrado ATÓMICO scopeado por dueño
        (anti-IDOR sin TOCTOU): el hecho de OTRO usuario == inexistente → 404 indistinguible, sin
        oráculo. UUID malformado → 404 (jamás 500)."""
        from app.phase1 import repo
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            if not repo.delete_account_memory(conn, memory_id, owner_id=owner):
                raise HTTPException(status_code=404,
                    detail={"error": "not_found",
                            "detail": "Ese recuerdo no existe o no es tuyo."})
            return {"ok": True, "id": memory_id}
        finally:
            conn.close()

    # ── Borrado de cuenta (ticket 2 · sprint pre-launch) ──
    @router.delete("")
    def delete_account(authorization: Optional[str] = Header(default=None)):
        """Pide el borrado de LA PROPIA cuenta (la de la sesión): el acceso muere YA
        (middleware), los datos quedan congelados 30 días (re-login = reactivar), y las
        conexiones OAuth se REVOCAN AL INSTANTE — irreversible aun si vuelve. Responde el
        copy honesto con la fecha EXACTA de la purga (la misma del mail en el outbox).
        Idempotente: repetir el pedido conserva las fechas del primero."""
        from app.phase1 import account_deletion
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            out = account_deletion.delete_account(conn, owner)
            if out is None:
                raise HTTPException(status_code=404,
                    detail={"error": "not_found", "detail": "No encontré la cuenta."})
            return out
        finally:
            conn.close()

    @router.get("/deletion")
    def deletion_status(authorization: Optional[str] = Header(default=None)):
        """Estado del borrado de la cuenta de la sesión. Nota: con la cuenta YA en
        soft-delete el middleware corta antes de llegar acá (401 account_deleted con el
        purge_at) — este GET sirve para el estado 'activa' y para tests in-process."""
        from app.phase1 import repo
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            state = repo.user_deleted_state(conn, owner) or {}
            return {"deleted": bool(state.get("deleted_at")),
                    "deleted_at": state.get("deleted_at"),
                    "purge_at": state.get("purge_after")}
        finally:
            conn.close()

    return router
