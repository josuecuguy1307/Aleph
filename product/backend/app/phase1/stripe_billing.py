"""
stripe_billing.py — la pasarela de PAGO de T7: comprar presupuesto (créditos) → sube el cap.

Diseño: Stripe es OPCIONAL y se degrada HONESTO. Sin `stripe` instalado o sin
`STRIPE_SECRET_KEY`, los endpoints devuelven {configured:false, ...} (no un crash, no un
pago fingido). Cuando hay key:
  - create_checkout_session: abre un Checkout (modo `payment`) por un monto en USD; el
    user_id viaja en metadata para que el webhook sepa a quién acreditar.
  - construct_event: VERIFICA la firma del webhook (STRIPE_WEBHOOK_SECRET) — sin firma
    válida no se acredita nada (anti-spoof).
  - credit_from_event: de un `checkout.session.completed` saca {user_id, usd, event_id}.

El secreto vive en env (STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET). Nunca se loguea ni
se devuelve al cliente. T7 sólo orquesta; la acreditación al cap la hace billing.add_credit.
"""

from __future__ import annotations

import os
from typing import Any, Optional


def _secret_key() -> Optional[str]:
    return os.environ.get("STRIPE_SECRET_KEY") or None


def _webhook_secret() -> Optional[str]:
    return os.environ.get("STRIPE_WEBHOOK_SECRET") or None


def _import_stripe():
    """Import perezoso de la lib `stripe`. None si no está instalada (degradación honesta)."""
    try:
        import stripe  # type: ignore
        return stripe
    except Exception:
        return None


def is_configured() -> bool:
    """¿Hay lib + key para cobrar de verdad? Si no, los endpoints lo dicen sin fingir."""
    return bool(_import_stripe() and _secret_key())


def status() -> dict[str, Any]:
    """Diagnóstico honesto del estado de la pasarela (sin filtrar secretos)."""
    return {
        "configured": is_configured(),
        "lib_installed": bool(_import_stripe()),
        "secret_key_present": bool(_secret_key()),
        "webhook_secret_present": bool(_webhook_secret()),
    }


def create_checkout_session(
    *,
    user_id: str,
    amount_usd: float,
    success_url: str,
    cancel_url: str,
    currency: str = "usd",
) -> dict[str, Any]:
    """
    Crea un Checkout Session de Stripe por `amount_usd` (compra de créditos de presupuesto).
    Devuelve {configured, url, session_id}. Si Stripe no está configurado → {configured:false}
    (el front muestra "pagos no disponibles", no un checkout falso).
    """
    stripe = _import_stripe()
    sk = _secret_key()
    if not stripe or not sk:
        return {"configured": False, "detail": "Stripe no configurado (sin lib o STRIPE_SECRET_KEY)."}
    if amount_usd is None or float(amount_usd) <= 0:
        raise ValueError("amount_no_positivo")
    stripe.api_key = sk
    cents = int(round(float(amount_usd) * 100))
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": currency,
                "product_data": {"name": f"Aleph — crédito de presupuesto (${amount_usd:.2f})"},
                "unit_amount": cents,
            },
            "quantity": 1,
        }],
        # EL LIGADOR: el webhook lee esto para saber a quién acreditar. amount como respaldo.
        metadata={"user_id": str(user_id), "credit_usd": f"{float(amount_usd):.8f}"},
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return {"configured": True, "url": session.get("url"), "session_id": session.get("id")}


def construct_event(payload: bytes, sig_header: Optional[str]) -> dict[str, Any]:
    """
    Verifica y parsea un evento de webhook. Con STRIPE_WEBHOOK_SECRET valida la FIRMA
    (anti-spoof); sin secret de webhook configurado lanza (no aceptamos eventos sin verificar).
    Devuelve el evento (dict). Lanza ValueError si la firma no valida.
    """
    stripe = _import_stripe()
    wh = _webhook_secret()
    if not stripe:
        raise RuntimeError("stripe_lib_ausente")
    if not wh:
        raise RuntimeError("webhook_secret_ausente")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, wh)
    except Exception as exc:  # firma inválida / payload corrupto
        raise ValueError(f"firma_invalida: {type(exc).__name__}")
    return dict(event)


def credit_from_event(event: dict) -> Optional[dict[str, Any]]:
    """
    De un evento de pago confirmado saca {event_id, user_id, usd} para acreditar. Sólo
    actúa sobre `checkout.session.completed` con pago `paid`. Cualquier otro → None.
    El usd se toma del metadata (lo que pusimos al crear el checkout) o de amount_total.
    """
    if not isinstance(event, dict):
        return None
    if event.get("type") != "checkout.session.completed":
        return None
    obj = ((event.get("data") or {}).get("object")) or {}
    if obj.get("payment_status") not in (None, "paid", "no_payment_required"):
        return None
    meta = obj.get("metadata") or {}
    user_id = meta.get("user_id")
    if not user_id:
        return None
    # usd: preferí el metadata explícito; si no, derivá de amount_total (centavos).
    usd: Optional[float] = None
    if meta.get("credit_usd"):
        try:
            usd = float(meta["credit_usd"])
        except (TypeError, ValueError):
            usd = None
    if usd is None and obj.get("amount_total") is not None:
        try:
            usd = int(obj["amount_total"]) / 100.0
        except (TypeError, ValueError):
            usd = None
    if not usd or usd <= 0:
        return None
    return {"event_id": event.get("id"), "user_id": user_id, "usd": usd}


__all__ = [
    "is_configured", "status", "create_checkout_session",
    "construct_event", "credit_from_event",
]
