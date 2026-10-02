"""payments_router.py — la slice /v1/payments/* · Step 5 · Casa 1 · P3.

EL PUNTO DONDE EL PAGO SE VUELVE TIER. Todo lo demás de Casa 1 converge acá.

Este módulo NO importa el SDK de ningún procesador — habla la interfaz
(`platform/payments/base.ProcesadorDePagos`). Un test de contrato en la suite
(tests/phase1/test_payments_contract.py) pone la regresión en rojo si eso cambia.
El antipatrón vive al lado, documentado: billing_router.py importa el SDK de Stripe
dentro del handler (carril viejo, intocado por decisión — ticket post-launch).

LAS REGLAS DEL §2, todas en el mismo handler:
  1. FIRMA PRIMERO — el body llega crudo y no se parsea hasta verificar. Parsear antes
     es procesar entrada no confiable.
  2. ACK RÁPIDO — Dodo corta a los 15 s y reintenta 8 veces (backoff hasta ~28 h). El
     handler verifica, persiste el evento y responde 2xx; el efecto se aplica en
     background. Nada pesado adentro.
  3. IDEMPOTENCIA — por el header `webhook-id`, resuelta por el motor
     (INSERT ... ON CONFLICT DO NOTHING RETURNING). Un duplicado se ACKea sin reprocesar:
     no ACKear lo haría reintentar 8 veces más.
  4. SIN ORDEN GARANTIZADO — el upsert descarta un evento más viejo que el último
     aplicado (`last_event_at`), así un `cancelled` demorado no degrada a alguien que
     acaba de renovar.

FAIL-CLOSED: cualquier problema (firma, evento raro, cuenta no atribuible) termina en
"no se cambia nada". Nunca en un ascenso inferido. La regla de oro del Step 5: un
premium bloqueado por error es molesto; uno abierto por error vacía el moat.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel


# Los eventos de Dodo son JSON chicos. El límite vive en ESTA frontera pública y no en
# middleware global porque checkout/reconcile y los uploads tienen contratos distintos.
# Se cuentan los bytes recibidos aunque falte Content-Length (HTTP chunked).
_MAX_WEBHOOK_BODY_BYTES = 1024 * 1024


async def _read_webhook_body(request: Request) -> bytes:
    """Lee el body crudo sin permitir agregación ilimitada antes de verificar firma."""
    content_lengths = request.headers.getlist("content-length")
    if len(content_lengths) > 1:
        raise HTTPException(status_code=400,
                            detail={"error": "content_length_invalido"})
    if content_lengths:
        try:
            declared = int(content_lengths[0])
        except ValueError:
            raise HTTPException(status_code=400,
                                detail={"error": "content_length_invalido"})
        if declared < 0:
            raise HTTPException(status_code=400,
                                detail={"error": "content_length_invalido"})
        if declared > _MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail={"error": "webhook_body_demasiado_grande",
                        "max_bytes": _MAX_WEBHOOK_BODY_BYTES},
            )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail={"error": "webhook_body_demasiado_grande",
                        "max_bytes": _MAX_WEBHOOK_BODY_BYTES},
            )
        body.extend(chunk)
    return bytes(body)


class CheckoutRequest(BaseModel):
    """Lo que el cliente PUEDE elegir: el plan y a dónde volver. Nada más.

    Nótese la AUSENCIA de `account_id`/`user_id`: la cuenta sale de la sesión. Un campo
    que no existe no se puede falsificar."""

    plan: str                                   # 'monthly' | 'annual' | 'lifetime'
    return_url: Optional[str] = None
    procesador: Optional[str] = "dodo"


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    a = authorization.strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else (a or None)


# ── [Casa 2 · Fase 4 · 4.2.d.3] tier AUTORITATIVO desde el control (con TTL, respeta D1) ──
_CONTROL_TIER_TTL = 60.0
_control_tier_cache: dict = {}   # owner -> (respuesta|None, monotonic_ts)


def _fetch_control_tier(authorization, owner):
    """El tier autoritativo vive en el CONTROL (users.tier lo escribe el webhook de Dodo). El
    cliente lo consulta con TTL —NO llama a casa en cada check (D1)— y cachea también el fallo.
    None si no se pudo (→ el caller cae a la caché local, honesta)."""
    import time as _time
    now = _time.monotonic()
    hit = _control_tier_cache.get(owner)
    if hit and (now - hit[1]) < _CONTROL_TIER_TTL:
        return hit[0]
    import json as _json
    import urllib.request as _req
    try:
        import aleph_paths as _ap
    except ImportError:
        sys.path.insert(0, str(_REPO_ROOT / "platform"))
        import aleph_paths as _ap
    result = None
    try:
        r = _req.Request(_ap.control_url() + "/v1/payments/me/tier",
                         headers={"Authorization": authorization or "", "Accept": "application/json"})
        with _req.urlopen(r, timeout=4) as resp:
            data = _json.loads(resp.read().decode("utf-8", "ignore")) or {}
        if isinstance(data, dict) and data.get("tier"):
            data["source"] = "control"
            result = data
    except Exception:  # noqa: BLE001  (401 / red / timeout → caché local honesta)
        result = None
    _control_tier_cache[owner] = (result, now)   # cachea el fallo también → 1 consulta por TTL
    return result


def _RETURN_URL_DEFAULT() -> str:
    """A dónde vuelve el usuario tras pagar. Configurable porque cambia entre local y
    prod; el default apunta al front de dev."""
    base = os.environ.get("PUPPET_SPA_BASE") or "http://localhost:8151"
    return f"{base.rstrip('/')}/"

# `payments` vive en platform/ (no es paquete instalado) — mismo patrón que gates/.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLATFORM = str(_REPO_ROOT / "platform")
if _PLATFORM not in sys.path:
    sys.path.insert(0, _PLATFORM)


def build_payments_router(get_conn: Callable[[], Any], rol: str = "client") -> APIRouter:
    """[Casa 2 · 2.0] Acá el corte cliente/control es POR ENDPOINT, no por router.

    Este archivo mezcla los dos lados a propósito —son el mismo dominio— pero no la misma
    frontera de confianza:

      · SOLO plano de control — `/webhook/{procesador}`, `/checkout`, `/reconcile`: cobrar
        y activar el plan. Un webhook de pagos en la máquina de un usuario es superficie
        que no tiene por qué existir: recibe POSTs de afuera y escribe `subscriptions`,
        tabla que NUNCA sale del plano de control.
      · LAS DOS PUNTAS — `GET /me/tier` y `GET /status`: el cliente NECESITA preguntar su
        plan, y por D1 lo contesta desde su caché local en vez de llamar a casa en cada
        check (eso rompería local-first). El tier local es caché NO autoritativa; el muro
        real re-verifica server-side cuando algo se paga.

    `rol` default "client" = fail-closed, igual que platform/role.py.
    """
    es_control = (rol or "").strip().lower() == "control"
    router = APIRouter(prefix="/v1/payments", tags=["payments"])

    def solo_control(decorador):
        """Registra la ruta SOLO si este proceso es el plano de control.

        Se hace así —envolviendo el decorador— y no con un `if` alrededor de cada función
        porque eso obligaría a re-indentar los cuerpos enteros: mucho diff, mucho riesgo de
        romper algo, por una decisión que se lee en una línea. Cuando no aplica, la función
        se define igual pero NO se registra: no existe ruta, no hay superficie.
        """
        return decorador if es_control else (lambda fn: fn)

    def _procesador(nombre: str):
        from payments.base import get_procesador
        return get_procesador(nombre)

    # ── EL APLICADOR (corre en background, fuera del ACK) ─────────────────────
    def _aplicar(nombre_proc: str, webhook_id: str, raw: bytes, headers: dict) -> None:
        """Traduce el evento a efecto y lo persiste. Nunca lanza hacia afuera: esto
        corre desatendido, y una excepción acá sólo debe dejar rastro, no tumbar nada.

        Re-verifica la firma en vez de recibir el evento ya parseado del handler: el
        costo es despreciable y evita que un refactor futuro empiece a pasar por acá
        un payload que nadie verificó.
        """
        from app.phase1 import repo

        outcome = "error:desconocido"
        conn = None
        try:
            proc = _procesador(nombre_proc)
            evento = proc.verificar_webhook(raw, headers)
            efecto = proc.evento_a_efecto(evento)

            if efecto is None:
                # La mayoría de los eventos (facturas, entitlements, créditos) no mueven
                # la frontera free/premium. No es un error.
                outcome = "ignored_unknown"
                return

            if not efecto.account_id:
                # Sin metadata no hay a quién atribuirlo. Se registra y NO se toca ningún
                # tier: adivinar la cuenta sería justo el ascenso indebido que evitamos.
                outcome = "error:sin_account_id"
                return

            conn = get_conn()
            repo.upsert_subscription(
                conn,
                account_id=efecto.account_id,
                processor=proc.nombre,
                external_id=efecto.external_id,
                plan=efecto.plan,
                status=efecto.status,
                current_period_end=efecto.current_period_end,
                grace_until=efecto.grace_until,
                event_at=efecto.event_at,
            )
            # EL MOMENTO: el tier se RECALCULA desde el conjunto de suscripciones
            # (función pura), nunca se copia de lo que diga el procesador.
            repo.resync_account_tier(
                conn, efecto.account_id,
                reason=f"webhook:{evento.tipo}", webhook_id=webhook_id,
            )
            outcome = "applied"
        except Exception as e:  # noqa: BLE001 — desatendido: se registra, no se propaga
            outcome = f"error:{type(e).__name__}"
        finally:
            try:
                c = conn or get_conn()
                from app.phase1 import repo as _repo
                _repo.close_webhook_event(c, webhook_id, outcome)
                c.close()
            except Exception:
                pass

    # ── EL ENDPOINT ───────────────────────────────────────────────────────────
    @solo_control(router.post("/webhook/{procesador}"))
    async def webhook(procesador: str, request: Request, background: BackgroundTasks):
        """Público pero VERIFICADO por firma. Responde rápido; aplica en background."""
        try:
            proc = _procesador(procesador)
        except ValueError:
            raise HTTPException(status_code=404,
                                detail={"error": "procesador_desconocido"})

        # Crudo, acotado y todavía sin parsear: la firma se verifica sobre estos bytes
        # exactos. El conteo en stream impide el bypass por chunked/Content-Length falso.
        raw = await _read_webhook_body(request)
        headers = dict(request.headers.items())

        # 1 · FIRMA PRIMERO ---------------------------------------------------
        try:
            from payments.base import FirmaInvalida
            evento = proc.verificar_webhook(raw, headers)
        except FirmaInvalida as e:
            # Firma inválida → 401 y NO se persiste nada. Un atacante no debe poder
            # ni sembrar filas en la tabla de eventos.
            raise HTTPException(status_code=401,
                                detail={"error": "firma_invalida", "detail": str(e)})
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=401,
                                detail={"error": "firma_invalida", "detail": type(e).__name__})

        # 2 · IDEMPOTENCIA (la decide el motor) -------------------------------
        conn = get_conn()
        try:
            from app.phase1 import repo
            primero = repo.claim_webhook_event(
                conn,
                webhook_id=evento.webhook_id,
                processor=proc.nombre,
                event_type=evento.tipo,
                payload=json.dumps(evento.payload),
                event_at=evento.at,
            )
        finally:
            conn.close()

        if not primero:
            # Ya lo procesamos. Se ACKea igual: sin 2xx, Dodo reintenta 8 veces más.
            return {"received": True, "duplicate": True}

        # 3 · ACK RÁPIDO + background -----------------------------------------
        background.add_task(_aplicar, proc.nombre, evento.webhook_id, raw, headers)
        return {"received": True, "queued": True}

    # ── CHECKOUT ──────────────────────────────────────────────────────────────
    @solo_control(router.post("/checkout"))
    def checkout(body: CheckoutRequest, authorization: Optional[str] = Header(default=None)):
        """Abre el checkout hosteado del procesador para la cuenta de LA SESIÓN.

        ⚠ EL PUNTO CRÍTICO: `account_id` sale de la sesión, NUNCA del body. Si el
        cliente pudiera elegir a qué cuenta se acredita el pago, todo el puente
        pago→tier no serviría de nada — cualquiera pagaría $15 y ascendería la cuenta
        que quisiera (o reclamaría el pago de otro). Por eso el request NO tiene campo
        de cuenta: no hay nada que falsificar.
        """
        from app.phase1 import repo

        tok = _bearer(authorization)
        owner = repo.session_owner(tok) if tok else None
        if not owner:
            raise HTTPException(status_code=401, detail={
                "error": "no_session",
                "detail": "Inicia sesión para poder mejorar tu plan."})

        plan = (body.plan or "").strip().lower()
        if plan not in ("monthly", "annual", "lifetime"):
            raise HTTPException(status_code=400, detail={
                "error": "plan_invalido",
                "detail": "plan debe ser 'monthly', 'annual' o 'lifetime'."})

        try:
            proc = _procesador(body.procesador or "dodo")
            datos = proc.crear_checkout(
                plan=plan, account_id=owner,
                return_url=body.return_url or _RETURN_URL_DEFAULT(),
            )
        except ValueError as e:
            # plan sin product_id configurado (p.ej. el anual, que todavía no existe):
            # 501 honesto en vez de un 500 mudo.
            raise HTTPException(status_code=501, detail={
                "error": "plan_no_disponible", "detail": str(e)})
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail={
                "error": "procesador_no_responde", "detail": type(e).__name__})

        if not datos.get("checkout_url"):
            raise HTTPException(status_code=502, detail={
                "error": "sin_checkout_url",
                "detail": "El procesador no devolvió una URL de pago."})
        return datos

    # ── EL CHECK DE TIER (§2.3) ───────────────────────────────────────────────
    @router.get("/me/tier")
    def me_tier(authorization: Optional[str] = Header(default=None)):
        """La respuesta AUTORITATIVA sobre el plan de la sesión.

        Deliberadamente sobre `repo.session_owner()`: esa función es LA COSTURA que
        cambia cuando la identidad pase a Supabase (CONTRACT-AUTH-v2). Mientras
        respete `token → user_id | None`, este endpoint no se entera de quién emite
        el token.

        NO devuelve el tier "para que el cliente decida": los muros lo siguen
        resolviendo server-side en cada request. Esto es para que el cliente sepa qué
        mostrar y qué permitir LOCALMENTE sin quedar rehén de la red.
        """
        from app.phase1 import repo

        tok = _bearer(authorization)
        owner = repo.session_owner(tok) if tok else None
        if not owner:
            # 401 = "no sé quién sos", que el cliente traduce a free. No es lo mismo
            # que "sos free": el cache distingue una cosa de la otra.
            raise HTTPException(status_code=401, detail={"error": "no_session"})

        # [Casa 2 · Fase 4 · 4.2.d.3] En el CLIENTE el tier AUTORITATIVO vive en el control (D1:
        # users.tier local es caché). Se consulta con TTL y cae a la caché local si el control no
        # responde. En CONTROL, users.tier YA es autoritativo → sigue de largo (lee local).
        if not es_control:
            fresh = _fetch_control_tier(authorization, owner)
            if fresh is not None:
                return fresh

        conn = get_conn()
        try:
            user = repo.get_user(conn, owner)
            tier = (user or {}).get("tier") or "free"
            # [Casa 2 · Fase 2 · 2.2b] `subscriptions` es TABLA DE CONTROL (role.py:83):
            # no existe en el SQLite del cliente. Este endpoint NO está bajo `solo_control`
            # —y no debe estarlo, porque D1 dice que el cliente pregunta su plan sin
            # llamar a casa— así que el corte va acá adentro: en el cliente el tier sale
            # de `users.tier`, la caché autoritativa-para-mostrar, y el detalle del plan
            # queda vacío. Sin esto, /me/tier muere con "no such table: subscriptions".
            subs = repo.list_subscriptions(conn, owner) if es_control else []
        finally:
            conn.close()

        # El detalle del plan sale de la suscripción VIVA, si hay alguna.
        from payments import effects
        viva = next((s for s in subs
                     if effects.subscription_grants_premium(s)), None)
        return {
            "account_id": str(owner),
            "tier": tier,
            "es_premium": tier in ("basico", "tecnico"),
            "plan": (viva or {}).get("plan"),
            "expires_at": (viva or {}).get("current_period_end"),
            "in_grace": bool((viva or {}).get("grace_until")),
            "source": "control" if es_control else "local-cache",   # [4.2.d.3]
        }

    # ── RECONCILIACIÓN de la propia cuenta (§2 regla 6) ───────────────────────
    @solo_control(router.post("/reconcile"))
    def reconcile_mine(authorization: Optional[str] = Header(default=None)):
        """"Pagué y no se activó" — el caso de soporte más caro en confianza.

        En vez de pedirle al usuario que espere al barrido periódico, le pregunta al
        procesador por SU cuenta y corrige en el momento. Owner-gated: reconcilia la
        cuenta de la sesión y sólo esa (pasar un account_id ajeno no es una opción
        porque el endpoint no lo acepta).
        """
        from app.phase1 import repo
        from payments import reconcile as _rec

        tok = _bearer(authorization)
        owner = repo.session_owner(tok) if tok else None
        if not owner:
            raise HTTPException(status_code=401, detail={"error": "no_session"})

        conn = get_conn()
        try:
            res = _rec.reconciliar(conn, _procesador("dodo"), repo,
                                   solo_account_id=owner)
            tier = repo.get_user(conn, owner)["tier"]
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail={
                "error": "reconciliacion_fallida", "detail": type(e).__name__})
        finally:
            conn.close()
        # `detalle` queda afuera: puede nombrar ids del procesador. El usuario necesita
        # saber en qué quedó su tier, no la tripa.
        return {"revisadas": res["revisadas"], "corregidas": res["corregidas"],
                "tier": tier}

    # ── Diagnóstico ───────────────────────────────────────────────────────────
    @router.get("/status")
    def status():
        """¿Está cableada la pasarela?

        [audit superficie · H7] No devuelve claves, pero SÍ regalaba el mapa: procesador
        (dodo), modo (test_mode) y qué env están seteadas. A un atacante eso le dice qué
        atacar y que el sistema todavía está en pruebas. Un endpoint de diagnóstico no
        tiene por qué ser público.

        Detrás de `PUPPET_DIAG=1` (default OFF, como /health freshness): sin el flag,
        confirma vivo y nada más. El dev que necesite el detalle lo prende en su stack.
        """
        if str(os.environ.get("PUPPET_DIAG", "")).strip().lower() in ("1", "true", "yes", "on"):
            return {
                "procesador": "dodo",
                "environment": os.environ.get("DODO_PAYMENTS_ENVIRONMENT") or "test_mode",
                "api_key_configurada": bool(os.environ.get("DODO_PAYMENTS_API_KEY")),
                "webhook_key_configurada": bool(os.environ.get("DODO_PAYMENTS_WEBHOOK_KEY")),
            }
        return {"ok": True}

    return router
