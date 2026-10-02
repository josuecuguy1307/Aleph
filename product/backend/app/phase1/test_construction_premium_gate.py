#!/usr/bin/env python3
"""test_construction_premium_gate.py — MURALLA PREMIUM · el MOAT: construir un MCP NUEVO es Premium.

Prueba el gate REAL de construcción (Motor B) por el camino auténtico auth→sesión→users.tier→
require_feature, contra Postgres real (no un mock del tier). El gate cae SOLO sobre la construcción
de software nuevo; conectar/usar/equipar los que YA existen NO llama acá (no se testea rechazo ahí,
porque no debe haberlo).

Enforcement STAGED (decisión persona usuaria): con PUPPET_ENFORCE_MCP_CONSTRUCTION apagado el gate es no-op
(la base free de demo/e2e sigue construyendo); prendido, free/anónimo/desconocido → RECHAZO
(fail-closed), premium (basico/tecnico) → pasa.

Corre:  PYTHONPATH=<wt>/product/backend:<wt>/platform python3 -m pytest .../test_construction_premium_gate.py
Requisitos: Postgres puppet_ai vivo.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[4]
for _p in (str(_REPO / "product" / "backend"), str(_REPO / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.phase1 import repo
from app.phase1.forge_router import enforce_construction_premium

ENV = "PUPPET_ENFORCE_MCP_CONSTRUCTION"


def _mk_user(tier: str) -> str:
    conn = repo.get_conn()
    try:
        u = repo.get_or_create_user(conn, email=f"muro-mcp-{uuid.uuid4().hex[:10]}@test.local", tier=tier)
        conn.commit()
        return u["id"]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _auth(user_id: str) -> str:
    return "Bearer " + repo.mint_session(user_id)


def _restore(old):
    if old is None:
        os.environ.pop(ENV, None)
    else:
        os.environ[ENV] = old


# ── ENFORCEMENT OFF (default) → no-op: la base free sigue construyendo ────────────
def test_env_off_is_noop():
    old = os.environ.pop(ENV, None)
    try:
        assert enforce_construction_premium(None) is None, "anon con flag OFF NO debe ser negado"
        free = _mk_user("free")
        assert enforce_construction_premium(_auth(free)) is None, "free con flag OFF NO debe ser negado"
    finally:
        _restore(old)


# ── ENFORCEMENT ON → free logueado se RECHAZA con rechazo honesto ─────────────────
def test_env_on_free_rejected():
    old = os.environ.get(ENV)
    os.environ[ENV] = "1"
    try:
        free = _mk_user("free")
        rej = enforce_construction_premium(_auth(free))
        assert rej is not None, "SEV: un free construyó gratis con el enforcement ON (moat abierto)"
        assert rej.get("feature") == "mcp_construction" and rej.get("min_tier") == "basico"
        assert "Premium" in rej.get("error", ""), "el rechazo no es honesto (no menciona Premium)"
    finally:
        _restore(old)


# ── ENFORCEMENT ON → anónimo / token basura / vacío → RECHAZO (fail-closed) ───────
def test_env_on_anon_and_garbage_failclosed():
    old = os.environ.get(ENV)
    os.environ[ENV] = "1"
    try:
        assert enforce_construction_premium(None) is not None, "SEV: anónimo construyó gratis (sin cuenta)"
        assert enforce_construction_premium("") is not None, "SEV: authorization vacío no fue negado"
        assert enforce_construction_premium("Bearer no-es-un-token-real") is not None, (
            "SEV: un token basura (session_owner→None→tier None) desbloqueó construcción")
    finally:
        _restore(old)


# ── ENFORCEMENT ON → premium (basico/tecnico) PASA (el muro no es 'bloquear a todos') ─
def test_env_on_premium_allowed():
    old = os.environ.get(ENV)
    os.environ[ENV] = "1"
    try:
        for tier in ("basico", "tecnico"):
            u = _mk_user(tier)
            assert enforce_construction_premium(_auth(u)) is None, f"{tier} pago fue rechazado al construir"
    finally:
        _restore(old)


# ── el flag SOLO se activa con valores explícitos de verdad; basura → OFF (no rompe) ─
def test_env_flag_values():
    old = os.environ.get(ENV)
    free = _mk_user("free")
    try:
        for on in ("1", "true", "TRUE", "yes", "on", "  On  "):
            os.environ[ENV] = on
            assert enforce_construction_premium(_auth(free)) is not None, f"{on!r} debió ACTIVAR el enforcement"
        for off in ("0", "false", "no", "off", "", "banana", "2"):
            os.environ[ENV] = off
            assert enforce_construction_premium(_auth(free)) is None, f"{off!r} NO debió activar el enforcement"
    finally:
        _restore(old)


if __name__ == "__main__":
    tests = [test_env_off_is_noop, test_env_on_free_rejected, test_env_on_anon_and_garbage_failclosed,
             test_env_on_premium_allowed, test_env_flag_values]
    print("═" * 78)
    print("  MURALLA PREMIUM · gate de CONSTRUCCIÓN (el moat) — auth→tier real")
    print("═" * 78)
    ok = 0
    for fn in tests:
        try:
            fn(); print(f"  ✓ {fn.__name__}"); ok += 1
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}\n      → {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {fn.__name__}\n      → {type(e).__name__}: {e}")
    print(f"  {ok}/{len(tests)} verdes")
    raise SystemExit(0 if ok == len(tests) else 1)
