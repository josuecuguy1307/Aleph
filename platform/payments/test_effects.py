"""test_effects.py — la tabla de verdad estado→tier. Corre con pytest O standalone.

    python3 platform/payments/test_effects.py

El foco NO es el camino feliz (una línea). Es el fail-closed: la regla de oro dice que
un premium abierto por error vacía el moat, así que la mayoría de estos tests son
intentos de que la función diga 'basico' cuando no debe.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from payments.effects import (  # noqa: E402
    ALTA, RENOVADA, EN_GRACIA, TERMINAL, BAJA,
    FREE_TIER, PAID_TIER,
    apply_tier_effect, subscription_grants_premium,
)

NOW = _dt.datetime(2026, 7, 20, 12, 0, 0, tzinfo=_dt.timezone.utc)
FUTURO = NOW + _dt.timedelta(days=10)
PASADO = NOW - _dt.timedelta(days=10)


def _sub(**kw):
    base = {"status": ALTA, "plan": "monthly", "current_period_end": FUTURO, "grace_until": None}
    base.update(kw)
    return base


# ── 1. El camino feliz: lo que SÍ debe abrir ────────────────────────────────────
def test_alta_vigente_es_premium():
    assert apply_tier_effect([_sub()], now=NOW) == PAID_TIER


def test_renovada_vigente_es_premium():
    assert apply_tier_effect([_sub(status=RENOVADA)], now=NOW) == PAID_TIER


def test_lifetime_no_vence():
    # current_period_end NULL a propósito: lifetime no tiene fin de período.
    s = _sub(plan="lifetime", current_period_end=None)
    assert apply_tier_effect([s], now=NOW) == PAID_TIER
    # y sigue valiendo mucho después
    assert apply_tier_effect([s], now=NOW + _dt.timedelta(days=9999)) == PAID_TIER


def test_baja_respeta_el_periodo_pagado():
    # Canceló pero pagó hasta fin de mes: se le respeta lo pagado (§2 regla 5).
    assert apply_tier_effect([_sub(status=BAJA, current_period_end=FUTURO)], now=NOW) == PAID_TIER


def test_en_gracia_sigue_premium_mientras_dure():
    s = _sub(status=EN_GRACIA, current_period_end=PASADO, grace_until=FUTURO)
    assert apply_tier_effect([s], now=NOW) == PAID_TIER


# ── 2. Lo que NO debe abrir ─────────────────────────────────────────────────────
def test_baja_con_periodo_vencido_es_free():
    assert apply_tier_effect([_sub(status=BAJA, current_period_end=PASADO)], now=NOW) == FREE_TIER


def test_terminal_nunca_otorga_ni_con_periodo_vigente():
    # `failed` de Dodo: el mandato inicial no prosperó. No hay pago que respetar,
    # aunque el registro traiga una fecha de fin en el futuro.
    s = _sub(status=TERMINAL, current_period_end=FUTURO, grace_until=FUTURO)
    assert apply_tier_effect([s], now=NOW) == FREE_TIER


def test_gracia_vencida_y_periodo_vencido_es_free():
    s = _sub(status=EN_GRACIA, current_period_end=PASADO, grace_until=PASADO)
    assert apply_tier_effect([s], now=NOW) == FREE_TIER


def test_alta_con_periodo_vencido_es_free():
    assert apply_tier_effect([_sub(current_period_end=PASADO)], now=NOW) == FREE_TIER


def test_recurrente_sin_fecha_de_fin_no_asume_para_siempre():
    # El agujero clásico: falta el dato → se asume lo permisivo. Acá NO.
    assert apply_tier_effect([_sub(current_period_end=None)], now=NOW) == FREE_TIER


def test_sin_suscripciones_es_free():
    assert apply_tier_effect([], now=NOW) == FREE_TIER
    assert apply_tier_effect(None, now=NOW) == FREE_TIER


# ── 3. FAIL-CLOSED: basura, ambigüedad y estados desconocidos ───────────────────
def test_estados_basura_no_ascienden():
    basura = [
        "", " ", None, "premium", "PREMIUM", "activo", "active", "paid", "ok", "true",
        "admin", "alta ", " alta", "ALTA", "Alta", "ALTA_", "ALT4", "renovada\n",
        "baja;DROP TABLE", "🎉", 1, 0, True, [], {},
        "succeeded", "subscription.active",  # ← strings CRUDOS del procesador: no son nuestro vocabulario
    ]
    for mal in basura:
        s = _sub(status=mal, current_period_end=FUTURO)
        assert apply_tier_effect([s], now=NOW) == FREE_TIER, f"ASCENDIÓ con status={mal!r}"


def test_fechas_basura_no_ascienden():
    for mala in ["", "no-es-fecha", "2026-13-45", 12345, [], {}, "ayer"]:
        s = _sub(current_period_end=mala)
        assert apply_tier_effect([s], now=NOW) == FREE_TIER, f"ASCENDIÓ con fecha={mala!r}"


def test_fila_corrupta_no_tumba_las_demas():
    # Una fila rota no puede dejar sin tier a un pagador legítimo.
    assert apply_tier_effect(["no soy un dict", None, 42, _sub()], now=NOW) == PAID_TIER


def test_ninguna_fila_valida_es_free():
    assert apply_tier_effect(["basura", None, 42], now=NOW) == FREE_TIER


# ── 4. El CONJUNTO, no la última fila ───────────────────────────────────────────
def test_lifetime_pagado_sobrevive_a_un_mensual_cancelado():
    # El caso que rompe un diseño de "una suscripción por cuenta".
    subs = [
        _sub(status=BAJA, plan="monthly", current_period_end=PASADO),   # canceló el mensual
        _sub(status=ALTA, plan="lifetime", current_period_end=None),    # pero compró lifetime
    ]
    assert apply_tier_effect(subs, now=NOW) == PAID_TIER
    assert apply_tier_effect(list(reversed(subs)), now=NOW) == PAID_TIER  # el orden no importa


def test_todas_vencidas_es_free():
    subs = [
        _sub(status=BAJA, current_period_end=PASADO),
        _sub(status=TERMINAL, current_period_end=FUTURO),
    ]
    assert apply_tier_effect(subs, now=NOW) == FREE_TIER


# ── 5. Naive datetimes (lo que devuelve psycopg2 según config) ──────────────────
def test_naive_datetime_se_trata_como_utc():
    s = _sub(current_period_end=FUTURO.replace(tzinfo=None))
    assert apply_tier_effect([s], now=NOW) == PAID_TIER


def test_iso_string_se_parsea():
    # El payload del webhook trae ISO 8601 con Z (verificado en P0).
    s = _sub(current_period_end="2026-07-30T12:00:00Z")
    assert apply_tier_effect([s], now=NOW) == PAID_TIER


# ── 6. Contrato con la muralla ya certificada ───────────────────────────────────
def test_el_tier_pago_es_el_que_la_allowlist_reconoce():
    """PAID_TIER tiene que caer dentro de la allowlist de tier_gate, o la puerta
    abriría sobre una cerca que no la reconoce (premium escrito, muro cerrado)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gates import tier_gate
    assert tier_gate.is_premium_tier(PAID_TIER) is True
    assert tier_gate.is_premium_tier(FREE_TIER) is False
    assert tier_gate.gate_tier_for_account(PAID_TIER) == "premium"
    assert tier_gate.gate_tier_for_account(FREE_TIER) == "average"


if __name__ == "__main__":
    fails = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {name}: {e}")
        except Exception as e:
            fails += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - fails}/{len(tests)} verdes")
    sys.exit(1 if fails else 0)
