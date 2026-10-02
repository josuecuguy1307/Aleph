"""test_dodo_adapter.py — el mapeo evento→efecto, anclado al EVENTO REAL de P0.

    python3 platform/payments/test_dodo_adapter.py     (o pytest)

Los payloads de este archivo NO son inventados: el de `payment.succeeded` es el que
Dodo mandó de verdad en test_mode tras un pago real (reports/step5/P0-evento-crudo.json,
con el PII redactado). Un fixture inventado prueba que el código hace lo que el autor
creyó; éste prueba que hace lo que el procesador realmente manda.

Los nombres de evento están verificados 1:1 contra doc oficial + SDK. El test los pinea:
si alguien "corrige" `subscription.active` a `subscription.created` (que NO existe),
esto se pone rojo en vez de fallar en silencio en producción.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from payments import effects  # noqa: E402
from payments.base import EventoVerificado  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EVENTO_REAL = REPO / "reports" / "step5" / "P0-evento-crudo.json"

ACCOUNT = "c4b5de4d-0000-0000-0000-000000000000"


def _adaptador():
    """Instancia el adaptador SIN llamar a la red: sólo se ejercita el mapeo puro."""
    from payments.dodo import DodoProcesador
    return DodoProcesador(api_key="test-noop", webhook_key="test-noop",
                          environment="test_mode")


def _ev(tipo, data, at=None):
    return EventoVerificado(
        webhook_id="msg_test", tipo=tipo,
        at=at or _dt.datetime(2026, 7, 20, 12, 0, tzinfo=_dt.timezone.utc),
        payload={"type": tipo, "data": data},
    )


def _sub_data(**kw):
    base = {
        "subscription_id": "sub_real_1",
        "metadata": {"account_id": ACCOUNT},
        "payment_frequency_interval": "Month",
        "next_billing_date": "2026-08-20T12:00:00Z",
    }
    base.update(kw)
    return base


ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def main():
    a = _adaptador()

    # ── 1. EL EVENTO REAL de P0 ────────────────────────────────────────────────
    real = json.loads(EVENTO_REAL.read_text())
    ev = EventoVerificado(
        webhook_id=real["webhook_headers"]["webhook-id"],
        tipo=real["event"]["type"],
        at=None,
        payload=real["event"],
    )
    ef = a.evento_a_efecto(ev)
    check("evento REAL de P0 produce un efecto", ef is not None)
    if ef:
        check("  → extrae el account_id de la metadata", ef.account_id == ACCOUNT,
              f"dio {ef.account_id!r}")
        check("  → lo clasifica lifetime (one-time, sin subscription_id)",
              ef.plan == "lifetime", f"dio {ef.plan!r}")
        check("  → estado ALTA", ef.status == effects.ALTA, f"dio {ef.status!r}")
        check("  → external_id = el payment_id real",
              ef.external_id == real["event"]["data"]["payment_id"])
        # el cierre del círculo: ese efecto, pasado por la función pura, da premium
        check("  → y ese efecto otorga premium",
              effects.apply_tier_effect([{
                  "status": ef.status, "plan": ef.plan,
                  "current_period_end": ef.current_period_end,
                  "grace_until": ef.grace_until}]) == effects.PAID_TIER)

    # ── 2. Ciclo de vida de suscripción (nombres pineados) ────────────────────
    for tipo, esperado in (("subscription.active", effects.ALTA),
                           ("subscription.renewed", effects.RENOVADA),
                           ("subscription.cancelled", effects.BAJA),
                           ("subscription.expired", effects.BAJA)):
        ef = a.evento_a_efecto(_ev(tipo, _sub_data()))
        check(f"{tipo} → {esperado}", ef is not None and ef.status == esperado,
              f"dio {ef.status if ef else None!r}")

    ef = a.evento_a_efecto(_ev("subscription.on_hold", _sub_data()))
    check("subscription.on_hold → en_gracia CON fecha de gracia",
          ef is not None and ef.status == effects.EN_GRACIA and ef.grace_until is not None)
    if ef:
        check(f"  → la gracia dura {a and 7} días (no corte inmediato)",
              (ef.grace_until - ef.event_at).days == 7)

    ef = a.evento_a_efecto(_ev("subscription.failed", _sub_data()))
    check("subscription.failed → terminal SIN gracia",
          ef is not None and ef.status == effects.TERMINAL and ef.grace_until is None)
    if ef:
        check("  → y terminal NO otorga premium ni con período vigente",
              effects.apply_tier_effect([{
                  "status": ef.status, "plan": ef.plan,
                  "current_period_end": _dt.datetime(2099, 1, 1, tzinfo=_dt.timezone.utc),
                  "grace_until": None}]) == effects.FREE_TIER)

    # ── 3. Plan por frecuencia ────────────────────────────────────────────────
    ef = a.evento_a_efecto(_ev("subscription.active",
                               _sub_data(payment_frequency_interval="Year")))
    check("frecuencia anual → plan 'annual'", ef is not None and ef.plan == "annual",
          f"dio {ef.plan if ef else None!r}")

    # ── 4. Lo que NO debe producir efecto ──────────────────────────────────────
    ef = a.evento_a_efecto(_ev("payment.succeeded", _sub_data(payment_id="pay_x")))
    check("payment.succeeded CON subscription_id → None (los subscription.* mandan)",
          ef is None, f"dio {ef!r}")

    for ruido in ("invoice.created", "license_key.created", "credit.added",
                  "dunning.started", "subscription.created", "cualquier.cosa", ""):
        ef = a.evento_a_efecto(_ev(ruido, _sub_data()))
        check(f"evento no manejado '{ruido}' → None (jamás asciende)", ef is None,
              f"dio {ef!r}")

    # ── 5. Sin metadata: no atribuible, pero no explota ───────────────────────
    ef = a.evento_a_efecto(_ev("subscription.active", _sub_data(metadata={})))
    check("sin account_id en metadata → efecto con account_id None (no revienta)",
          ef is not None and ef.account_id is None)

    # ── 6. environment: el default peligroso del SDK está tapado ──────────────
    from payments.dodo import DodoProcesador
    check("environment inválido se rechaza en el constructor",
          _lanza(lambda: DodoProcesador(api_key="x", environment="produccion")))
    os.environ.pop("DODO_PAYMENTS_ENVIRONMENT", None)
    check("sin env explícito, defaultea a test_mode (no a live_mode como el SDK)",
          DodoProcesador(api_key="x").environment == "test_mode")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


def _lanza(fn):
    try:
        fn()
        return False
    except Exception:
        return True


# ── entrypoints de pytest (además del standalone) ───────────────────────────────
def test_adaptador_dodo():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
