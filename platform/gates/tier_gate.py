"""tier_gate.py — MURALLA PREMIUM · gate de tier server-side + rechazo honesto (Caso 2/3).

Generaliza el patrón A2/B2 a UNA fuente: el tier se resuelve SIEMPRE desde la CUENTA del
dueño (nunca de recipe.tier ni de un flag del cliente/belt), y toda superficie premium niega
con el MISMO rechazo honesto. Regla: el frontend puede mostrar "🔒 Premium", pero el que NIEGA
es el backend; una invocación DIRECTA por API con tier free debe recibir el rechazo, no una UI
que oculta.

Dos modos de enforcement, un solo resolver de tier:
  · DENY-binario  (features premium): require_feature() → None | rechazo estructurado.
  · CLAMP-graduado (max_turns/tool_calls/parallel/memoria/rag): sigue en recipe_enforcer
    (*_caps_for_tier) — NO se convierten en deny (romperían el "free funcional").

Fuente de orden de tier: recipe_enforcer (TIER_RUNTIME_CAPS). Import UNIDIRECCIONAL
(tier_gate → recipe_enforcer); recipe_enforcer NO importa esto.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# orden canónico (free < basico < tecnico). Se lee de recipe_enforcer para no duplicar la verdad.
try:
    from gates.recipe_enforcer import _DEFAULT_TIER  # "free"
except Exception:  # carga por-ruta / paquete no montado
    _DEFAULT_TIER = "free"

_TIER_ORDER = {"free": 0, "basico": 1, "tecnico": 2}


def tier_rank(tier: Optional[str]) -> int:
    """Rango numérico del tier; desconocido/None → free (0), fail-closed."""
    return _TIER_ORDER.get((tier or "").strip().lower(), 0)


def is_premium_tier(tier: Optional[str]) -> bool:
    """¿La cuenta pagó (basico+)? free/desconocido → False."""
    return tier_rank(tier) >= _TIER_ORDER["basico"]


# ── Visibilidad de templates del catálogo por tier ────────────────────────────────
# Step 5 · P8: vivía en product/backend/app/accounts.py, junto a un SQLite de cuentas
# PARALELO al Postgres (dos tablas `users` desincronizadas — un premium en Postgres era
# free para /catalog). Ese store murió; la política se muda acá, que es su dominio.
#
# OJO: el vocabulario de TEMPLATE ('average'/'técnico') NO es el de CUENTA
# ('free'/'basico'/'tecnico'). Son dos ejes distintos que se cruzan sólo en esta tabla.
TIER_VISIBLE_TEMPLATES: dict[str, set[str]] = {
    "free":    {"average"},
    "basico":  {"average"},
    "tecnico": {"average", "técnico"},
}


def visible_template_tiers(account_tier: Optional[str]) -> set[str]:
    """Qué tiers de template puede VER esta cuenta. Desconocido/None → lo más
    restrictivo (fail-closed, igual que todo el resto del gate)."""
    return TIER_VISIBLE_TEMPLATES.get(
        (account_tier or "").strip().lower(), TIER_VISIBLE_TEMPLATES["free"])


def gate_tier_for_account(account_tier: Optional[str]) -> str:
    """Traduce el tier de CUENTA al vocabulario interno del approval_gate.
    OJO (gotcha real): el gate usa 'average' como centinela de gateado/gratis y NO conoce
    'free'/'basico'/'tecnico'. Pasarle 'free' crudo desbloquearía todo (self.tier=='average'
    daría False). Por eso mapeamos: free/desconocido → 'average' (gateable), premium → 'premium'."""
    return "premium" if is_premium_tier(account_tier) else "average"


# ── (a) REGISTRO ÚNICO de features premium-BINARIAS → tier mínimo ──────────────────
# SOLO features que free NO tiene (candado binario). Los caps GRADUADOS (max_turns,
# max_tool_calls, max_parallel, memoria, rag) NO van acá: esos clampan, no niegan.
PREMIUM_FEATURES: dict[str, str] = {
    "shared_memory_bus":  "basico",   # B2 · bus de memoria entre >1 agente (exemplar YA vivo)
    "memory_composition": "basico",   # sembrar el bus con memoria de agentes al componer (not-built-yet)
    "account_memory":     "basico",   # perfil del usuario cross-agente (not-built-yet)
    # EL MOAT · construir un conector (MCP) NUEVO = invocar el Motor de Inspección/Construcción (las
    # 6 capas) sobre software que NO está en el catálogo. Conectar/usar/equipar los que YA existen
    # (catálogo, registro público, pegar-tu-MCP, OAuth) es GRATIS y NO pasa por este gate.
    "mcp_construction":   "basico",
    # PIEZA MÉTODO · §7 — retención por arquitectura: crear métodos es ILIMITADO
    # (todos los tiers) y el .aleph vivo + PDF simple viajan GRATIS; lo premium es
    # el EXPORT TOTAL (Word/SOP, Markdown, checklist imprimible, JSON crudo) y la
    # BÓVEDA del servidor (fuente de verdad cloud, versiones, historial).
    "method_export_total": "basico",
    "method_vault":        "basico",
}

_MESSAGES: dict[str, str] = {
    # byte-idéntico al mensaje del candado B2 (recipe_assembler) para no romper la UX/tests.
    "shared_memory_bus": ("La memoria COMPARTIDA entre varios agentes es una función Premium. "
                          "Tu plan puede ver el cilindro Memory, pero para cablear el bus entre "
                          "más de un agente del Cuarto necesitas mejorar a Premium."),
    "memory_composition": ("Componer la memoria de varios agentes en un equipo nuevo es una "
                           "función Premium. Tu plan puede reusar un agente y su pericia, pero "
                           "mezclar memorias al armar el equipo necesita mejorar a Premium."),
    "account_memory": ("La memoria de CUENTA (que tus agentes recuerden quién eres entre "
                       "sesiones) es una función Premium. Tu plan corre agentes con su memoria "
                       "propia; el perfil cross-agente necesita mejorar a Premium."),
    "mcp_construction": ("Construir un conector NUEVO —inspeccionar un software que todavía no está "
                         "en el catálogo y armarlo capa por capa— es una función Premium. Con tu "
                         "plan puedes usar y conectar todos los conectores que YA existen (catálogo, "
                         "registro, pegar tu propio MCP, OAuth) y equipar tus agentes; construir uno "
                         "desde cero necesita mejorar a Premium."),
    "method_export_total": ("El export TOTAL de un método (Word/SOP formateado, Markdown, "
                            "checklist imprimible, JSON crudo) es una función Premium. Tu plan "
                            "exporta siempre el .aleph vivo completo y el PDF simple; los "
                            "formatos de oficina necesitan mejorar a Premium."),
    "method_vault": ("La bóveda del servidor para tus métodos (fuente de verdad en la nube, "
                     "sync multi-máquina, versiones e historial) es una función Premium. Tu "
                     "plan guarda y corre métodos localmente sin límite; la bóveda necesita "
                     "mejorar a Premium."),
}


def resolve_account_tier(conn, user_id: Optional[str], repo) -> Optional[str]:
    """(a) El tier SIEMPRE desde la CUENTA. Nunca de recipe/cliente. Anónimo/None → None
    (los llamadores lo tratan como free/fail-closed). NUNCA lanza: si el SELECT falla, None."""
    if not (user_id and conn is not None and repo is not None):
        return None
    try:
        return ((repo.get_user(conn, user_id) or {}).get("tier"))
    except Exception:
        return None


def tier_meets(account_tier: Optional[str], min_tier: str) -> bool:
    """¿El tier de cuenta alcanza el mínimo? desconocido → free (fail-closed)."""
    return tier_rank(account_tier) >= _TIER_ORDER.get(min_tier, 99)


def require_feature(feature: str, account_tier: Optional[str], *,
                    on_event: Optional[Callable[[dict], Any]] = None,
                    extra: Optional[dict] = None) -> Optional[dict]:
    """(c) None si el tier de cuenta alcanza la feature; si NO, RECHAZO honesto estructurado
    (mismo espíritu que record['error']+upsell de B2), reutilizable por TODA superficie premium.

    `account_tier` DEBE venir de resolve_account_tier (server-side), nunca del cliente.
    Emite un evento '<feature>_denied' si se pasa on_event (para el stream/forense).
    """
    min_tier = PREMIUM_FEATURES.get(feature)
    if min_tier is None or tier_meets(account_tier, min_tier):
        return None
    rej = {
        "error": _MESSAGES.get(feature, f"'{feature}' es una función Premium de tu plan."),
        "feature": feature,
        "min_tier": min_tier,
        "tier_gated": True,
    }
    if extra:
        rej.update(extra)
    if on_event:
        try:
            on_event({"type": f"{feature}_denied", "tier_gated": True,
                      "message": rej["error"], "min_tier": min_tier})
        except Exception:
            pass
    return rej


__all__ = [
    "PREMIUM_FEATURES", "resolve_account_tier", "tier_meets", "require_feature",
    "tier_rank", "is_premium_tier", "gate_tier_for_account",
]
