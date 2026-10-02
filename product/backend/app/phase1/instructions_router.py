"""
instructions_router.py — CRUD de las INSTRUCCIONES PERSISTENTES (Ola UX · B5).

  GET    /v1/instructions?puppet_id=…    lista del scope (cuenta si se omite; composición
                                         con puppet_id — owner-gated). Incluye propuestas
                                         del agente (enabled=false) para el panel.
  POST   /v1/instructions                {content, puppet_id?} → 201 (source='user')
  PATCH  /v1/instructions/{id}           {content?|enabled?} — ACTIVAR una propuesta del
                                         agente es EL gate de escritura-por-agente: sólo
                                         el humano la enciende (queda approved_at en meta)
  DELETE /v1/instructions/{id}

AUTHZ: sesión SIEMPRE (una instrucción tiene dueño); scope por owner de la sesión;
puppet ajeno → 404 (patrón _mem_gate). CAPS por tier (memory_caps_for_tier): al exceder
se RECHAZA con error honesto — las instrucciones no se desalojan solas.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.phase1 import instructions_repo as irepo


class InstructionCreate(BaseModel):
    content: str
    puppet_id: Optional[str] = None


class InstructionPatch(BaseModel):
    content: Optional[str] = None
    enabled: Optional[bool] = None


def _owner_or_401(authorization: Optional[str]) -> str:
    """Ver `authz_http`: una sola copia del 401, y el copy lo pone cada superficie."""
    from app.phase1.authz_http import owner_or_401
    return owner_or_401(authorization,
                        detail="Inicia sesión para ver tus instrucciones.",
                        copy="Inicia sesión para ver tus instrucciones.")


def build_instructions_router(*, get_conn: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/instructions", tags=["instructions"])

    def _puppet_gate(conn, puppet_id: Optional[str], owner: str) -> Optional[str]:
        """Composición del DUEÑO o 404 (ajena == inexistente). None = scope cuenta."""
        if not puppet_id:
            return None
        from app.phase1 import repo
        p_owner = repo.puppet_owner(conn, puppet_id)
        if p_owner is None or str(p_owner) != owner:
            raise HTTPException(status_code=404,
                detail={"error": "puppet_not_found",
                        "detail": "Esa composición no existe (o no es tuya)."})
        return puppet_id

    def _caps(conn, owner: str) -> dict:
        from app.phase1 import repo
        try:
            import sys
            from pathlib import Path
            _plat = str(Path(__file__).resolve().parents[4] / "platform")
            if _plat not in sys.path:
                sys.path.insert(0, _plat)
            from gates.recipe_enforcer import memory_caps_for_tier
            user = repo.get_user(conn, owner) or {}
            return memory_caps_for_tier(user.get("tier") or "free")
        except Exception:
            return {"max_entries": 20, "max_bytes": 8192}

    @router.get("")
    def list_instructions(puppet_id: Optional[str] = Query(default=None),
                          authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            pid = _puppet_gate(conn, puppet_id, owner)
            rows = irepo.list_instructions(conn, owner, puppet_id=pid)
            # [H2] el usage mostrado = lo FACTURABLE (excluye propuestas pendientes del
            # agente), para que el panel coincida con lo que el cap del POST realmente mide.
            return {"total": len(rows),
                    "usage": irepo.scope_usage(conn, owner, pid, billable_only=True),
                    "caps": _caps(conn, owner), "instructions": rows}
        finally:
            conn.close()

    @router.post("", status_code=201)
    def create_instruction(body: InstructionCreate,
                           authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        content = (body.content or "").strip()
        if not content:
            raise HTTPException(status_code=422,
                detail={"error": "empty_content", "detail": "La instrucción no puede estar vacía."})
        conn = get_conn()
        try:
            pid = _puppet_gate(conn, body.puppet_id, owner)
            caps = _caps(conn, owner)
            # [H2] mide el cap contra lo FACTURABLE: las propuestas pendientes del agente
            # (inertes, que el usuario no escribió) NO consumen su cuota ni le rebotan el POST.
            usage = irepo.scope_usage(conn, owner, pid, billable_only=True)
            nbytes = len(content.encode("utf-8"))
            if usage["entries"] + 1 > caps.get("max_entries", 20) or \
                    usage["bytes"] + nbytes > caps.get("max_bytes", 8192):
                raise HTTPException(status_code=422,
                    detail={"error": "over_cap", "usage": usage, "caps": caps,
                            "detail": "Llegaste al tope de instrucciones de tu plan — borra alguna o acórtala."})
            return irepo.add_instruction(conn, user_id=owner, puppet_id=pid, content=content)
        finally:
            conn.close()

    @router.patch("/{instr_id}")
    def patch_instruction(instr_id: str, body: InstructionPatch,
                          authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            row = irepo.get_instruction_owned(conn, instr_id, owner)
            if row is None:
                raise HTTPException(status_code=404,
                    detail={"error": "not_found", "detail": "Esa instrucción no existe."})
            content = (body.content or "").strip() if body.content is not None else None
            if body.content is not None and not content:
                raise HTTPException(status_code=422,
                    detail={"error": "empty_content", "detail": "La instrucción no puede quedar vacía."})
            # [H4] el PATCH TAMBIÉN respeta el cap de bytes del tier — si no, una instrucción
            # de 5 bytes se infla a MB por edición y burla el tope del plan. Proyectamos el uso
            # facturable del scope tras el cambio y rechazamos honesto (como el POST, no truncamos).
            if content is not None:
                caps = _caps(conn, owner)
                max_bytes = caps.get("max_bytes", 8192)
                nbytes = len(content.encode("utf-8"))
                pid = row.get("puppet_id")
                usage = irepo.scope_usage(conn, owner, pid, billable_only=True)
                row_billable_now = (row.get("source") == "user") or bool(row.get("enabled"))
                new_enabled = body.enabled if body.enabled is not None else bool(row.get("enabled"))
                row_billable_new = (row.get("source") == "user") or bool(new_enabled)
                projected = usage["bytes"] - (row.get("bytes", 0) if row_billable_now else 0) \
                    + (nbytes if row_billable_new else 0)
                if nbytes > max_bytes or projected > max_bytes:
                    raise HTTPException(status_code=422,
                        detail={"error": "over_cap", "usage": usage, "caps": caps,
                                "detail": "Esa edición pasa el tope de tu plan — acórtala."})
            meta_merge = None
            # [B5·gate] ACTIVAR una propuesta del agente = el OK explícito del humano.
            # Queda marcada: source sigue 'agent' (proveniencia) + approved en meta.
            if body.enabled is True and row.get("source") == "agent" and not row.get("enabled"):
                meta_merge = {"approved": True}
            ok = irepo.update_instruction(conn, instr_id, owner, content=content,
                                          enabled=body.enabled, meta_merge=meta_merge)
            if not ok:
                raise HTTPException(status_code=422,
                    detail={"error": "nothing_to_update", "detail": "Nada que actualizar."})
            return irepo.get_instruction_owned(conn, instr_id, owner)
        finally:
            conn.close()

    @router.delete("/{instr_id}")
    def delete_instruction(instr_id: str,
                           authorization: Optional[str] = Header(default=None)):
        owner = _owner_or_401(authorization)
        conn = get_conn()
        try:
            if not irepo.delete_instruction(conn, instr_id, owner):
                raise HTTPException(status_code=404,
                    detail={"error": "not_found", "detail": "Esa instrucción no existe."})
            return {"ok": True, "id": instr_id}
        finally:
            conn.close()

    return router
