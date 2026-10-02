"""effects.py — la REGLA que convierte estado comercial en TIER. Función PURA.

Step 5 · Casa 1 · P1. Es la pieza que decide si una cuenta es premium, y por eso es
deliberadamente la más aburrida y la más testeada del bloque: sin I/O, sin framework,
sin red, sin DB. Entra una lista de suscripciones, sale un string de tier.

DOCTRINA (heredada de MURALLA-PREMIUM.md — regla de oro de persona usuaria):
    "Prefiero un premium bloqueado por error (molesto) que un premium abierto por
     error (te vacían el moat)."
Traducción operativa acá: TODO lo que no sea inequívocamente una suscripción viva
devuelve `free`. Estado desconocido, mal escrito, None, fecha ausente, basura → free.
Nunca al revés.

VOCABULARIO PROPIO (§4-bis · processor-agnostic): este módulo NO conoce a Dodo. Habla
`SubStatus`, que el adaptador produce traduciendo los eventos del procesador de turno.
Si mañana entra Paddle, este archivo no se toca.

POR QUÉ el tier sale del CONJUNTO de suscripciones y no de una: una cuenta puede tener
un lifetime pagado Y un mensual cancelado. La respuesta correcta es premium, y sale de
tomar el MÁXIMO de lo que cada fila habilita — nunca de "la última que tocamos".
"""
from __future__ import annotations

import datetime as _dt
from typing import Iterable, Optional

# ── Vocabulario propio de estado (lo que el adaptador debe producir) ──────────────
ALTA = "alta"            # suscripción viva y paga (o compra one-time consumada)
RENOVADA = "renovada"     # renovó bien; equivalente a ALTA para efectos de tier
EN_GRACIA = "en_gracia"   # cobro falló pero es RECUPERABLE (Dodo: subscription.on_hold).
#                           Sigue premium hasta grace_until — no se corta de golpe.
TERMINAL = "terminal"     # falló de entrada y NO se reactiva (Dodo: subscription.failed).
#                           Sin gracia: nunca hubo cobro exitoso que proteger.
BAJA = "baja"             # cancelada o expirada. Premium hasta el fin del período PAGADO.

#: Los únicos estados que este módulo entiende. Cualquier otra cosa → free (fail-closed).
KNOWN_STATUSES = frozenset({ALTA, RENOVADA, EN_GRACIA, TERMINAL, BAJA})

#: Tier que otorga una suscripción viva. Deliberadamente `basico`: es el que la allowlist
#: de tier_gate.gate_tier_for_account traduce a premium. `tecnico` no se vende todavía
#: (§1.6: para el launch sólo Free + Premium) — cuando exista, se mapea por plan acá.
PAID_TIER = "basico"
FREE_TIER = "free"


def _as_utc(value) -> Optional[_dt.datetime]:
    """Normaliza a datetime UTC consciente de zona. Devuelve None ante CUALQUIER duda.

    Un naive datetime se asume UTC (es lo que Postgres devuelve con TIMESTAMPTZ ya
    convertido, y lo que trae el ISO 8601 del payload). Basura → None, y el caller
    trata None como 'no hay fecha que me proteja' → no otorga premium.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, _dt.datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(_dt.timezone.utc)


def subscription_grants_premium(sub: dict, *, now: Optional[_dt.datetime] = None) -> bool:
    """¿ESTA fila, por sí sola, habilita premium en este instante?

    `sub` es un dict con las columnas de `subscriptions` (status, plan,
    current_period_end, grace_until). Tolera claves faltantes: lo ausente resta, nunca suma.
    """
    now = _as_utc(now) or _dt.datetime.now(_dt.timezone.utc)

    # Comparación EXACTA, sin strip ni lower. El único escritor de esta columna es
    # nuestro adaptador, que escribe las constantes de este módulo — no hay fuente
    # legítima de " alta " ni "ALTA". Normalizar ensancharía el conjunto que abre la
    # puerta a cambio de nada, y el precedente certificado (test_premium_wall #4) es
    # que sólo el string exacto desbloquea. Ante variación → free.
    status = sub.get("status")
    if not isinstance(status, str) or status not in KNOWN_STATUSES:
        return False  # fail-closed: no entiendo el estado → no abro nada

    if status == TERMINAL:
        # El mandato inicial nunca prosperó: no hay período pagado que respetar.
        # Verificado en la doc oficial de Dodo: `failed` es terminal, jamás se reactiva.
        return False

    if status in (ALTA, RENOVADA):
        plan = str(sub.get("plan") or "").strip().lower()
        if plan == "lifetime":
            return True  # no vence por definición; current_period_end es NULL a propósito
        end = _as_utc(sub.get("current_period_end"))
        # Sin fecha de fin en un plan recurrente NO se asume "para siempre": se asume dudoso.
        return end is not None and end > now

    if status == EN_GRACIA:
        # Cobro fallido pero recuperable. Sigue premium mientras dure la gracia —
        # y SÓLO mientras dure: sin grace_until no hay gracia que valga.
        grace = _as_utc(sub.get("grace_until"))
        if grace is not None and grace > now:
            return True
        # La gracia venció; puede quedarle período pagado por delante igual.
        end = _as_utc(sub.get("current_period_end"))
        return end is not None and end > now

    if status == BAJA:
        # Canceló, pero pagó hasta fin de mes: se le respeta lo pagado (§2 regla 5).
        end = _as_utc(sub.get("current_period_end"))
        return end is not None and end > now

    return False  # inalcanzable; el fail-closed queda escrito igual


def apply_tier_effect(subs: Iterable[dict], *, now: Optional[_dt.datetime] = None) -> str:
    """EL veredicto: qué tier corresponde a una cuenta, dadas TODAS sus suscripciones.

    Devuelve 'basico' si alguna fila habilita premium; 'free' si ninguna. Nunca lanza:
    una fila corrupta se ignora, no tumba el cálculo de las demás (una excepción acá,
    en el camino del webhook, dejaría a un pagador sin su tier).
    """
    for sub in (subs or []):
        try:
            if isinstance(sub, dict) and subscription_grants_premium(sub, now=now):
                return PAID_TIER
        except Exception:
            continue  # fila rota = fila que no otorga nada; seguimos con las otras
    return FREE_TIER
