"""zones.py — LA FRONTERA del carve de Motor B. [Casa 2 · Fase 4 · carve lógico]

Clasifica cada módulo de `platform/inspection/` en tres zonas. Es **CÓDIGO** (no un MD que se
desactualiza): la allowlist del cliente (Fase 4.2) deriva de acá, y `test_inspection_zones`
se pone ROJO si un módulo nuevo de `inspection/` queda sin clasificar — la seguridad que el
carve FÍSICO daba por estructura, acá dada por un test.

  RESOLVE → el CURADO de MCPs (buscar + equipar lo que YA existe). FREE, LOCAL. **VIAJA** al
            `.exe` del cliente (D-B).
  SHARED  → tipos/primitivas que usan los DOS lados (contracts, crypto, el SSRF guard…).
            neutro. **VIAJA**.
  FORGE   → el MOAT: forja de MCPs nuevos, loop interno, observe, mesa, captura de estrategia.
            **QUEDA** server-side (D-A), premium.

Rutas relativas a `platform/inspection/`, sin `.py`. Los 4 edges resolve→forge se rompieron
(lazy/inject) para que RESOLVE|SHARED importen SIN forge presente:
  1. dispatch/dispatcher → strategy.cascade   (lazy en _nada; honest-fail si forge ausente)
  2. dispatch/liveness   → loop.guard          (guard es SHARED → viaja, no se rompe)
  3. bridge              → observe/*, session  (lazy en run_recon_to_space; SpaceEmitter limpio)
  4. registry            → observe.emit_belt    (lazy en persist_belt; el equip no lo llama)
"""
from __future__ import annotations

# ── RESOLVE · curado (viaja, free/local) ──────────────────────────────────────────
RESOLVE = frozenset({
    "mcp_resolver", "mcp_registry", "mcp_matcher",
    "byo_mcp", "byo_mcp_server",
    "dispatch/__init__", "dispatch/classifier", "dispatch/dispatcher",
    "dispatch/liveness", "dispatch/models",
})

# ── SHARED · neutro (viaja; lo importan los dos lados) ────────────────────────────
SHARED = frozenset({
    "__init__",                      # el paquete inspection tiene que existir en el cliente
    "contracts", "models", "crypto", "mcp_http_client",
    "registry", "bridge",            # curado los usa; forja también (tras romper su edge)
    "sse_util",                      # [4.2.a] _sse/_slug: primitiva del stream; dispatch (cliente) + forge (control)
    "loop/__init__", "loop/guard",   # guard = SSRFGuard (liveness + loop); __init__ vacío
})

# ── FORGE · el moat (QUEDA server-side, premium) ──────────────────────────────────
FORGE = frozenset({
    "cli", "inspect_run", "synth_mcp_server",
    # loop/ completo MENOS __init__ y guard (que son SHARED)
    "loop/armed_executor", "loop/budget", "loop/emit", "loop/engine",
    "loop/forged_mcp_server", "loop/live_http", "loop/observer",
    "loop/run_alphavantage", "loop/run_tmdb", "loop/session",
    "loop/session_browser", "loop/session_login", "loop/synth", "loop/validator",
    "observe/__init__", "observe/correlate", "observe/emit_belt", "observe/healthcheck",
    "observe/recorder", "observe/replay", "observe/synthesize",
    "mesa/__init__", "mesa/almacen", "mesa/consola", "mesa/modelos",
    "mesa/preguntas", "mesa/proyeccion",
    "strategy/__init__", "strategy/cascade", "strategy/openapi", "strategy/rungs",
    "strategy/types",
    "library/__init__", "library/fingerprint", "library/reinject", "library/store",
    "capture/__init__", "capture/dom", "capture/events", "capture/network",
    "session/__init__", "session/base", "session/cloud",
})


def ships() -> frozenset:
    """Lo que VIAJA al `.exe` del cliente (la allowlist de 4.2 deriva de acá)."""
    return RESOLVE | SHARED


def stays() -> frozenset:
    """Lo que QUEDA server-side (el moat)."""
    return FORGE


def zone_of(module: str) -> str | None:
    """'resolve' | 'shared' | 'forge' | None (sin clasificar)."""
    if module in RESOLVE:
        return "resolve"
    if module in SHARED:
        return "shared"
    if module in FORGE:
        return "forge"
    return None


__all__ = ["RESOLVE", "SHARED", "FORGE", "ships", "stays", "zone_of"]
