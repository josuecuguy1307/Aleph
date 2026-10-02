"""verify_step5_p2_firma.py — LLAVE VIVA de P2: la verificación de firma, de verdad.

El mapeo evento→efecto se prueba con el payload real (test_dodo_adapter.py). Lo que
ESTE archivo prueba es lo otro: que `verificar_webhook` acepte una firma legítima y
rechace todo lo demás. Se firma con el algoritmo real (Standard Webhooks, HMAC-SHA256
vía la librería `standardwebhooks` que usa el propio SDK), no con un mock.

    ./product/backend/.venv/bin/python qa/verify_step5_p2_firma.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))

from payments.base import FirmaInvalida  # noqa: E402
from payments.dodo import DodoProcesador  # noqa: E402

SECRETO = base64.b64encode(b"step5-p2-secreto-de-prueba-32bytes!!").decode()
CUERPO = json.dumps({
    "type": "subscription.active",
    "timestamp": "2026-07-20T12:00:00Z",
    "data": {"subscription_id": "sub_firma", "metadata": {"account_id": "acc-1"},
             "payment_frequency_interval": "Month",
             "next_billing_date": "2026-08-20T12:00:00Z"},
}).encode()

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def firmar(cuerpo: bytes, wid: str, ts: int, secreto: str) -> dict:
    """Firma con la MISMA librería que el SDK usa para verificar."""
    from standardwebhooks.webhooks import Webhook
    firma = Webhook(secreto).sign(wid, __import__("datetime").datetime.fromtimestamp(
        ts, __import__("datetime").timezone.utc), cuerpo.decode())
    return {"webhook-id": wid, "webhook-timestamp": str(ts), "webhook-signature": firma}


def main():
    proc = DodoProcesador(api_key="noop", webhook_key=SECRETO, environment="test_mode")
    ts = int(time.time())
    buenos = firmar(CUERPO, "msg_firma_ok", ts, SECRETO)

    # ── 1. La firma legítima PASA y produce el evento ──────────────────────────
    try:
        ev = proc.verificar_webhook(CUERPO, buenos)
        check("firma válida → evento verificado", ev.tipo == "subscription.active")
        check("  → webhook_id sale del HEADER (la llave de idempotencia)",
              ev.webhook_id == "msg_firma_ok")
        check("  → timestamp del PAYLOAD parseado (para ordenar)", ev.at is not None)
        ef = proc.evento_a_efecto(ev)
        check("  → y el efecto llega hasta el vocabulario propio",
              ef is not None and ef.status == "alta")
    except FirmaInvalida as e:
        check("firma válida → evento verificado", False, f"rechazó una firma buena: {e}")

    # ── 2. Todo lo demás se RECHAZA ───────────────────────────────────────────
    def rechaza(label, cuerpo, headers):
        try:
            proc.verificar_webhook(cuerpo, headers)
            check(label, False, "ACEPTÓ lo que debía rechazar")
        except FirmaInvalida:
            check(label, True)

    rechaza("body manipulado (1 byte distinto) → rechazado",
            CUERPO.replace(b"acc-1", b"acc-2"), buenos)
    rechaza("firma de otro secreto → rechazado",
            CUERPO, firmar(CUERPO, "msg_firma_ok", ts, base64.b64encode(b"otro" * 8).decode()))
    rechaza("webhook-id cambiado (la firma lo cubre) → rechazado",
            CUERPO, {**buenos, "webhook-id": "msg_otro"})
    rechaza("timestamp cambiado → rechazado", CUERPO, {**buenos, "webhook-timestamp": str(ts + 99)})
    rechaza("firma vacía → rechazado", CUERPO, {**buenos, "webhook-signature": ""})
    rechaza("sin headers de firma → rechazado", CUERPO, {})
    rechaza("headers incompletos → rechazado", CUERPO, {"webhook-id": "x"})
    rechaza("timestamp viejísimo (anti-replay del spec) → rechazado",
            CUERPO, firmar(CUERPO, "msg_viejo", ts - 86400, SECRETO))

    # ── 3. Los headers se leen sin importar el case (HTTP no lo garantiza) ────
    raros = {k.upper(): v for k, v in buenos.items()}
    try:
        ev = proc.verificar_webhook(CUERPO, raros)
        check("headers en MAYÚSCULAS igual verifican (HTTP es case-insensitive)",
              ev.webhook_id == "msg_firma_ok")
    except FirmaInvalida as e:
        check("headers en MAYÚSCULAS igual verifican", False, str(e))

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


def test_firma_webhook():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
