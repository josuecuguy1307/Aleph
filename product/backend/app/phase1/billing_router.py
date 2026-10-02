"""
billing_router.py — la slice /v1/billing/* · owner: T7-billing.

Expone el metering, el cap y la pasarela de pago sobre la lógica pura de `billing.py`.
Mismo patrón de inyección que el resto del backend (build_*_router(get_conn=...) montado
en main.py). AUTHZ por SESIÓN (§4.5): cada endpoint con identidad verifica que la sesión
sea dueña del user_id — preferimos el módulo congelado `authz` (owner T6) y caemos a
`repo.session_owner` si todavía no está mergeado (forward-compatible, verificable hoy).

Endpoints:
  GET  /v1/billing/meter/{user_id}      — gastado / cap / restante / over (owner-gated)
  GET  /v1/billing/preflight/{user_id}  — EL CORTE: ¿puede arrancar un run? 402 si excedió
  POST /v1/billing/limit/{user_id}      — el usuario se pone un tope de gasto (autocontrol)
  POST /v1/billing/checkout             — Stripe Checkout para comprar presupuesto
  POST /v1/billing/webhook/stripe       — webhook firmado → acredita el pago al cap
  GET  /v1/billing/stripe-status        — diagnóstico de la pasarela (sin secretos)
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel


# ── auth: preferí authz (T6, congelado) y caé a repo.session_owner (presente en main) ──
def _session_owner(token: Optional[str]) -> Optional[str]:
    try:
        from app.phase1 import authz  # owner T6 (cuando esté mergeado)
        return authz.session_owner(token)
    except Exception:
        from app.phase1 import repo
        return repo.session_owner(token)


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    a = authorization.strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else (a or None)


def _authorize(claimed_user_id: str, authorization: Optional[str]) -> str:
    """IDENTIDAD OBLIGATORIA (None ⇒ deny). Sin sesión → 401; sesión de otro → 403.
    Mismo candado anti-IDOR que el resto del backend (§4.5)."""
    owner = _session_owner(_bearer(authorization))
    if owner is None:
        raise HTTPException(status_code=401,
            detail={"error": "no_session", "detail": "Inicia sesión para continuar."})
    if str(owner) != str(claimed_user_id):
        raise HTTPException(status_code=403,
            detail={"error": "forbidden", "detail": "Esa cuenta no es la tuya."})
    return owner


class LimitRequest(BaseModel):
    self_limit_usd: Optional[float] = None  # None = quitar el tope


class CheckoutRequest(BaseModel):
    user_id: str
    amount_usd: float
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


def build_billing_router(*, get_conn: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/v1/billing", tags=["billing"])

    def _conn():
        try:
            return get_conn()
        except Exception as exc:
            raise HTTPException(status_code=503,
                detail={"error": "db_unavailable", "detail": str(exc)})

    # ── METERING: la verdad de gasto del usuario ──────────────────────────────
    @router.get("/meter/{user_id}")
    def meter(user_id: str, authorization: Optional[str] = Header(default=None)):
        _authorize(user_id, authorization)
        from app.phase1 import billing
        conn = _conn()
        try:
            return billing.get_meter(conn, user_id)
        finally:
            conn.close()

    # ── PREFLIGHT: EL CORTE. 402 (Payment Required) si el usuario ya excedió su cap.
    @router.get("/preflight/{user_id}")
    def preflight(user_id: str, authorization: Optional[str] = Header(default=None)):
        _authorize(user_id, authorization)
        from app.phase1 import billing
        conn = _conn()
        try:
            pf = billing.preflight(conn, user_id)
        finally:
            conn.close()
        if not pf["allowed"]:
            # 402: el cliente (y el run path) saben que está cortado por presupuesto.
            raise HTTPException(status_code=402, detail={"error": "over_budget", **pf})
        return pf

    # ── SELF-LIMIT: autocontrol de gasto (sólo BAJA el cap efectivo) ──────────
    @router.post("/limit/{user_id}")
    def set_limit(user_id: str, body: LimitRequest,
                  authorization: Optional[str] = Header(default=None)):
        _authorize(user_id, authorization)
        from app.phase1 import billing
        conn = _conn()
        try:
            try:
                return billing.set_self_limit(conn, user_id, body.self_limit_usd)
            except ValueError as e:
                raise HTTPException(status_code=400, detail={"error": str(e)})
        finally:
            conn.close()

    # ── CHECKOUT: comprar presupuesto (sube el cap al confirmarse el pago) ────
    @router.post("/checkout")
    def checkout(body: CheckoutRequest, authorization: Optional[str] = Header(default=None)):
        _authorize(body.user_id, authorization)
        # LOGIN SUAVE §4: el muro premium sigue exigiendo CUENTA. Una sesión local
        # anónima (device user) es sesión válida para trabajar, pero NO para comprar:
        # rechazo honesto que invita al login (la fusión conserva su trabajo).
        from app.phase1 import repo
        conn = _conn()
        try:
            u = repo.get_user(conn, body.user_id)
        finally:
            conn.close()
        if repo.is_device_user(u):
            raise HTTPException(status_code=403, detail={
                "error": "account_required",
                "detail": ("Para comprar necesitas una cuenta: tu sesión actual es local, "
                           "de este equipo. Crea tu cuenta o ingresa — tu trabajo local "
                           "se liga solo a la cuenta.")})
        from app.phase1 import stripe_billing
        if body.amount_usd is None or body.amount_usd <= 0:
            raise HTTPException(status_code=400, detail={"error": "amount_no_positivo"})
        try:
            res = stripe_billing.create_checkout_session(
                user_id=body.user_id,
                amount_usd=body.amount_usd,
                success_url=body.success_url or "https://aleph.ai/billing/ok",
                cancel_url=body.cancel_url or "https://aleph.ai/billing/cancel",
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"error": str(e)})
        if not res.get("configured"):
            # honesto: no hay pasarela. 503 tipado, no un checkout fingido.
            raise HTTPException(status_code=503,
                detail={"error": "stripe_not_configured", **res})
        return res

    # ── WEBHOOK Stripe: PÚBLICO pero VERIFICADO por firma → acredita el pago ──
    @router.post("/webhook/stripe")
    async def stripe_webhook(request: Request,
                             stripe_signature: Optional[str] = Header(default=None)):
        from app.phase1 import stripe_billing, billing
        payload = await request.body()
        try:
            event = stripe_billing.construct_event(payload, stripe_signature)
        except ValueError as e:
            # firma inválida → 400, NO se acredita nada (anti-spoof)
            raise HTTPException(status_code=400, detail={"error": "bad_signature", "detail": str(e)})
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail={"error": "stripe_not_configured", "detail": str(e)})

        credit = stripe_billing.credit_from_event(event)
        if credit is None:
            return {"received": True, "credited": False, "reason": "no_credit_event"}

        conn = _conn()
        try:
            # IDEMPOTENCIA del webhook: Stripe puede reenviar. Acreditamos UNA vez por event_id.
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO billing_stripe_events (event_id, type, user_id, usd) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
                    (credit["event_id"], event.get("type"), credit["user_id"], str(credit["usd"])),
                )
                first_time = cur.fetchone() is not None
            conn.commit()
            if not first_time:
                return {"received": True, "credited": False, "reason": "already_processed"}
            meter = billing.add_credit(conn, credit["user_id"], credit["usd"])
            return {"received": True, "credited": True, "usd": credit["usd"], "meter": meter}
        finally:
            conn.close()

    # ── diagnóstico de la pasarela (sin secretos) ─────────────────────────────
    @router.get("/stripe-status")
    def stripe_status():
        from app.phase1 import stripe_billing
        return stripe_billing.status()

    return router


__all__ = ["build_billing_router"]
