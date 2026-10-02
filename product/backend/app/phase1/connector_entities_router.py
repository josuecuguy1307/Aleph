"""HTTP read-model de la entidad Conector."""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header

from app.phase1 import connector_entities
from app.phase1.atoms_router import _connected_for, _owner_from_session, collect_atoms


def build_connector_entities_router(
    *, get_conn: Optional[Callable[[], Any]] = None
) -> APIRouter:
    router = APIRouter(prefix="/v1/connector-entities", tags=["connector-entities"])

    def _read(authorization: Optional[str]) -> dict:
        owner = _owner_from_session(authorization)
        connected, partial = _connected_for(owner, get_conn)
        key_rows = []
        if owner and get_conn is not None:
            try:
                from app.phase1 import repo
                conn = get_conn()
                try:
                    key_rows = [
                        row for row in repo.list_keys(conn, owner)
                        if not repo.is_companion_provider(row.get("provider", ""))
                    ]
                finally:
                    conn.close()
            except Exception:
                key_rows = []
        atoms = collect_atoms(connected, partial, owner=owner)
        return connector_entities.build_entities(atoms, key_rows=key_rows, owner=owner)

    @router.get("")
    def list_entities(authorization: Optional[str] = Header(default=None)):
        return _read(authorization)

    @router.get("/migration")
    def migration_report():
        # SIN SESIÓN A PROPÓSITO: es un reporte de migración del catálogo de la caja. Antes
        # servía además el `synth_belts` de TODAS las cuentas a quien pidiera, sin autenticar.
        return connector_entities.build_entities(collect_atoms()).get("migration", {})

    return router


__all__ = ["build_connector_entities_router"]
