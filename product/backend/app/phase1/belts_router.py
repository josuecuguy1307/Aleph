"""
belts_router.py — CARDS legibles de un belt (vista de USUARIO), GENÉRICO y data-driven.

  GET /v1/belts/cards?ref=<belt_ref>&user_id=<uid>

Lee el belt REAL (`_meta.cards`), valida que cada `card.backed_by` exista en
`mcpServers` (dropea cualquier card sin server real → CERO THEATER), y marca el estado
por-usuario: keyless → "Ya funciona"; token/oauth → "Conectado" si el user ya tiene la
key, si no "Conectar" (+ `connectable` = existe onboarding object para hacerlo desde la SPA).

El SPA consume esto para surfacear el belt por nicho. Lo que se muestra == lo que el belt
declara, que es lo que el agente recibe (las tools de cada card activa van a tool_filters).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query

# [audit superficie · H4] la identidad sale de la sesión — reusa el helper canónico que
# P8 dejó en atoms_router (repo.session_owner detrás de una firma limpia).
from app.phase1.atoms_router import _owner_from_session

try:
    import aleph_paths as _ap
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

_RESOURCE_ROOT = _ap.resource_root()
_BELT_ROOTS = [(_RESOURCE_ROOT / "catalog").resolve(),
               (_RESOURCE_ROOT / "platform").resolve()]
_ONB = _RESOURCE_ROOT / "catalog" / "connectors" / "onboarding"


def _safe_belt_path(ref: str) -> Path:
    """Anti-traversal: el ref es relativo al repo y DEBE caer dentro de catalog/ o platform/."""
    p = (_RESOURCE_ROOT / ref).resolve()
    if not any(root == p or root in p.parents for root in _BELT_ROOTS):
        raise HTTPException(status_code=400,
            detail={"error": "bad_ref", "detail": "belt_ref fuera de rango permitido"})
    if p.suffix != ".json" or not p.exists():
        raise HTTPException(status_code=404,
            detail={"error": "not_found", "detail": f"belt no encontrado: {ref}"})
    return p


def _onb_exists(connector: Optional[str]) -> bool:
    if not connector:
        return False
    return (_ONB / f"{connector}.json").exists()


def build_belts_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/belts", tags=["belts"])

    @router.get("/cards")
    def belt_cards(ref: str = Query(..., description="belt_ref relativo al repo"),
                   authorization: Optional[str] = Header(default=None)):
        belt = json.loads(_safe_belt_path(ref).read_text(encoding="utf-8"))
        servers = belt.get("mcpServers", {}) or {}
        decl = (belt.get("_meta") or {}).get("cards") or []

        connected: set = set()
        partial: set = set()   # STEP 2·A3 · OAuth incompleto (offline sin refresh) → caduca ~1h
        # [audit superficie · H4] QUÉ CONECTORES tiene el usuario sale de la SESIÓN, no de
        # un `?user_id=` del query. Antes tomaba el id del cliente y devolvía provider+last4
        # de ESA cuenta: iterando ids, cualquiera mapeaba las integraciones de todos. Es el
        # mismo patrón que P8 cerró en atoms_router/catalog_search/catalog_validate; este
        # endpoint quedó fuera de aquel barrido. La 5ta cara de "identidad del cliente".
        owner = _owner_from_session(authorization)
        if owner and get_conn is not None:
            try:
                from app.phase1 import repo
                conn = get_conn()
                try:
                    provs = [k.get("provider") for k in repo.list_keys(conn, owner)]
                finally:
                    conn.close()
                connected, partial = repo.classify_key_providers(provs)  # excluye companion __oauth*
            except Exception:
                pass  # sin DB → todo aparece como no-conectado (honesto, no rompe)

        cards, dropped = [], []
        for c in decl:
            backed = c.get("backed_by")
            if backed not in servers:
                dropped.append(c.get("id"))   # card sin server real → fuera (cero theater)
                continue
            auth = c.get("auth", "keyless")
            connector = c.get("credential_provider") or c.get("connector")
            card = {"id": c.get("id"), "label": c.get("label"), "sub": c.get("sub"),
                    "auth": auth, "armario": c.get("armario"), "backed_by": backed,
                    "tools": c.get("tools"), "connector": connector,
                    "origin_connector": c.get("connector"),
                    "credential_provider": connector, "service": c.get("service")}
            # ESTADO: delegado a la ÚNICA fuente de verdad (atoms_router.estado_honesto).
            # Acá vivía una SEGUNDA copia de las mismas reglas — y era la copia que importa,
            # porque El Cuarto arma sus cards con ESTE endpoint (`pickNiche` →
            # GET /v1/belts/cards), no con /v1/atoms/catalog. Al arreglar el falso verde
            # sólo en atoms_router, la pantalla real seguía diciendo "Ya funciona · sin
            # llave" sobre piezas que el server no puede lanzar: el fix no llegaba a verse.
            from app.phase1.atoms_router import estado_honesto
            card.update(estado_honesto(servers[backed], c, auth=auth,
                                       connector=connector,
                                       connected=connected, partial=partial))
            cards.append(card)

        return {"ref": ref, "slug": (belt.get("_meta") or {}).get("slug"),
                "cards": cards, "total": len(cards),
                "servers_real": sorted(servers.keys()), "dropped": dropped}

    return router


__all__ = ["build_belts_router"]
