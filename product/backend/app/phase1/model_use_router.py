"""API de preflight para el contrato canónico de modelos.

No ejecuta modelos. Expone el mismo catálogo secretless al selector mínimo y al resolver.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException

from app.phase1.model_use_contract import AdmissionReceipt, ModelUse
from app.phase1.model_use_resolver import ResolutionFailure, public_choices, resolve_model_use


def _owner(authorization: Optional[str]) -> Optional[str]:
    from app.phase1 import repo
    token = str(authorization or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return repo.session_owner(token) if token else None


def build_model_use_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/model-use", tags=["model-use"])

    def _catalog(owner_id: str, *, all_rows: bool) -> dict[str, Any]:
        from app.phase1 import centro_modelos
        return centro_modelos.selector_modelos(
            owner=owner_id, get_conn=get_conn, contexto=None, todos=all_rows
        )

    def _require_owner(authorization: Optional[str]) -> str:
        owner_id = _owner(authorization)
        if not owner_id:
            raise HTTPException(status_code=401, detail={
                "error": "no_session",
                "detail": "Esta acción necesita tu sesión.",
            })
        return owner_id

    @router.get("/choices")
    def choices(authorization: Optional[str] = Header(default=None)):
        owner_id = _require_owner(authorization)
        catalog = _catalog(owner_id, all_rows=False)
        return {
            "schema_version": "model-use/v1",
            "default_ref": catalog.get("default_id"),
            "choices": public_choices(catalog),
            "search_threshold": 12,
        }

    @router.post("/resolve", response_model=AdmissionReceipt)
    def resolve(body: ModelUse, authorization: Optional[str] = Header(default=None)):
        owner_id = _require_owner(authorization)
        try:
            snapshot = resolve_model_use(
                body,
                owner_id=owner_id,
                read_catalog=lambda owner: _catalog(owner, all_rows=True),
            )
            return AdmissionReceipt(
                call_id=snapshot.call_id,
                selection_ref=snapshot.selection_ref,
                selection_scope=snapshot.selection_scope,
                policy_ref=snapshot.policy_ref,
                requirements_hash=snapshot.requirements_hash,
            )
        except ResolutionFailure as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc

    return router


__all__ = ["build_model_use_router"]
