"""dodo.py — Dodo Payments detrás de la interfaz. EL ÚNICO ARCHIVO QUE IMPORTA EL SDK.

Step 5 · Casa 1 · P2. Si `import dodopayments` aparece en cualquier otro archivo del
árbol, el test de contrato pone la suite en rojo (tests/phase1/test_payments_contract.py).

NOMBRES DE EVENTOS: verificados 1:1 contra la doc oficial Y el union type del SDK
(2026-07-20), no de memoria. La directiva original decía `subscription.created` —
NO EXISTE. Codear contra ese nombre habría dado un webhook que jamás activa premium,
fallando en silencio. Tampoco existen `trial_will_end` ni `paused`/`resumed`.

SEMÁNTICA QUE IMPORTA (doc oficial):
  · `subscription.on_hold` = renovación falló, RECUPERABLE actualizando el método de
    pago → gracia.
  · `subscription.failed`  = el mandato inicial nunca prosperó, TERMINAL, jamás se
    reactiva → SIN gracia (no hay pago previo que respetar).
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Optional

from payments import effects
from payments.base import (
    EfectoDeTier, EstadoRemoto, EventoVerificado, FirmaInvalida, ProcesadorDePagos,
)

#: Días de gracia ante un cobro fallido recuperable. La directiva pide "días, no corte
#: inmediato"; la estrategia (§8.8) dice 3-7. Tomamos el techo: cortarle el servicio a
#: alguien que sí quiere pagar es peor negocio que regalarle una semana.
GRACIA_DIAS = 7

#: Estados de Dodo → vocabulario propio. Lo que no esté acá NO asciende (fail-closed).
_STATUS_REMOTO = {
    "active":    effects.ALTA,
    "on_hold":   effects.EN_GRACIA,
    "failed":    effects.TERMINAL,
    "cancelled": effects.BAJA,
    "expired":   effects.BAJA,
    "pending":   effects.TERMINAL,   # todavía no cobró: no otorga nada
}


def _iso(value) -> Optional[_dt.datetime]:
    """Parsea el ISO 8601 del payload. Ante cualquier duda, None — y sin fecha, la
    función pura no otorga premium."""
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def _productos_por_plan() -> dict:
    """plan → product_id del dashboard. Los ids son config, no código: viven en env
    porque cambian entre test_mode y live_mode."""
    return {
        "monthly": os.environ.get("DODO_PRODUCT_MONTHLY"),
        "annual": os.environ.get("DODO_PRODUCT_ANNUAL"),
        "lifetime": os.environ.get("DODO_PRODUCT_LIFETIME"),
    }


class _ProductosLazy(dict):
    """Lee el env en cada acceso: los tests monkeypatchean variables después de
    importar el módulo, y un dict congelado al importar les daría valores viejos."""

    def get(self, k, default=None):  # noqa: D102
        return _productos_por_plan().get(k, default)

    def items(self):  # noqa: D102
        return _productos_por_plan().items()


_PRODUCTO_POR_PLAN = _ProductosLazy()


def _plan_de(data: dict) -> str:
    """Deriva el plan. Recurrente → por su frecuencia; sin subscription_id → lifetime."""
    if not data.get("subscription_id"):
        return "lifetime"
    interval = str(data.get("payment_frequency_interval") or "").strip().lower()
    if interval.startswith("year"):
        return "annual"
    return "monthly"


class DodoProcesador(ProcesadorDePagos):
    nombre = "dodo"

    def __init__(self, *, api_key: Optional[str] = None,
                 webhook_key: Optional[str] = None,
                 environment: Optional[str] = None):
        from dodopayments import DodoPayments  # ← el único import del SDK en todo el árbol

        # El SDK defaultea a live_mode: acá se exige explícito. Olvidarlo en dev
        # significa pegarle a producción con datos de prueba.
        env = environment or os.environ.get("DODO_PAYMENTS_ENVIRONMENT") or "test_mode"
        if env not in ("test_mode", "live_mode"):
            raise ValueError(f"environment inválido: {env!r}")

        self._client = DodoPayments(
            bearer_token=api_key or os.environ.get("DODO_PAYMENTS_API_KEY"),
            webhook_key=webhook_key or os.environ.get("DODO_PAYMENTS_WEBHOOK_KEY"),
            environment=env,
        )
        self.environment = env

    # ── 1/3 ──────────────────────────────────────────────────────────────────────
    def verificar_webhook(self, raw_body: bytes, headers: dict) -> EventoVerificado:
        """Firma PRIMERO (regla 1). `unwrap()` del SDK oficial, spec Standard Webhooks.

        `unsafe_unwrap()` NO se usa nunca: existe sólo para los payloads mock del CLI,
        que no vienen firmados. Un parseo previo a la verificación sería procesar
        entrada no confiable.
        """
        h = {k.lower(): v for k, v in (headers or {}).items()}
        need = ("webhook-id", "webhook-signature", "webhook-timestamp")
        if not all(h.get(k) for k in need):
            raise FirmaInvalida(f"faltan headers de firma: {[k for k in need if not h.get(k)]}")

        try:
            self._client.webhooks.unwrap(raw_body, headers={k: h[k] for k in need})
        except Exception as e:
            # Cualquier fallo de verificación es firma inválida hacia afuera: no se
            # filtran tipos de excepción del SDK a través de la interfaz.
            raise FirmaInvalida(str(e)) from e

        import json
        body = json.loads(raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body)
        return EventoVerificado(
            webhook_id=h["webhook-id"],
            tipo=str(body.get("type") or ""),
            at=_iso(body.get("timestamp")),
            payload=body,
        )

    # ── 2/3 ──────────────────────────────────────────────────────────────────────
    def evento_a_efecto(self, evento: EventoVerificado) -> Optional[EfectoDeTier]:
        data = (evento.payload or {}).get("data") or {}
        tipo = evento.tipo
        # El hilo pago↔cuenta: metadata del checkout, VERIFICADO propagando sobre un
        # evento real en test_mode (reports/step5/P0-evento-crudo.json).
        account_id = ((data.get("metadata") or {}).get("account_id")) or None
        sub_id = data.get("subscription_id")
        ahora = evento.at or _dt.datetime.now(_dt.timezone.utc)

        def _efecto(external_id, plan, status, period_end=None, grace=None):
            return EfectoDeTier(
                account_id=account_id, external_id=str(external_id), plan=plan,
                status=status, current_period_end=period_end, grace_until=grace,
                event_at=evento.at,
            )

        # ── one-time (Early Lifetime) ──────────────────────────────────────────
        if tipo == "payment.succeeded":
            if sub_id:
                # Pago DE una suscripción: los eventos `subscription.*` son la fuente
                # autoritativa de su estado (traen next_billing_date; este payload no).
                # Ignorar acá evita escribir un período de fin inventado.
                return None
            return _efecto(data.get("payment_id"), "lifetime", effects.ALTA)

        if tipo == "refund.succeeded":
            # Le devolvieron la plata: no puede quedarse premium. Sin período que
            # respetar — la baja es inmediata (current_period_end=None → free).
            ext = data.get("subscription_id") or data.get("payment_id")
            if not ext:
                return None
            return _efecto(ext, _plan_de(data), effects.BAJA)

        # ── suscripciones ──────────────────────────────────────────────────────
        if not sub_id:
            return None

        plan = _plan_de(data)
        fin = _iso(data.get("next_billing_date"))

        if tipo in ("subscription.active", "subscription.renewed"):
            estado = effects.ALTA if tipo == "subscription.active" else effects.RENOVADA
            return _efecto(sub_id, plan, estado, period_end=fin)

        if tipo == "subscription.on_hold":
            # Recuperable: sigue premium mientras dure la gracia.
            return _efecto(sub_id, plan, effects.EN_GRACIA, period_end=fin,
                           grace=ahora + _dt.timedelta(days=GRACIA_DIAS))

        if tipo == "subscription.failed":
            # Terminal: el mandato inicial no prosperó. Sin gracia.
            return _efecto(sub_id, plan, effects.TERMINAL)

        if tipo in ("subscription.cancelled", "subscription.expired"):
            # Se respeta el período pagado (§2 regla 5): la función pura lo evalúa
            # contra current_period_end.
            return _efecto(sub_id, plan, effects.BAJA, period_end=fin)

        # Todo lo demás (invoices, entitlements, credits, disputes, dunning…) no mueve
        # la frontera free/premium. El caller lo marca 'ignored_unknown' y ACKea.
        # GAP CONOCIDO Y DELIBERADO: `dispute.lost` (contracargo) NO revoca acá — la
        # reconciliación de P5 lo levanta cuando el procesador cancele la suscripción.
        return None

    # ── EXTRA (no está en la interfaz, a propósito) ──────────────────────────────
    # `crear_checkout` NO sube a ProcesadorDePagos: la forma del checkout en Paddle es
    # una incógnita y una interfaz se generaliza cuando hay un SEGUNDO implementador
    # que la valida, no antes (§4-bis, decisión de persona usuaria). Vive acá, concreto, y el
    # router lo llama por el adaptador de Dodo explícitamente.
    def crear_checkout(self, *, plan: str, account_id: str,
                       return_url: str) -> dict:
        """Crea una sesión de checkout hosteado y devuelve {checkout_url, session_id}.

        `account_id` es EL HILO que liga el pago a la cuenta: viaja en metadata y vuelve
        en el webhook (verificado sobre un evento real en P0). El caller DEBE sacarlo de
        la sesión, nunca del body del cliente — si no, cualquiera acredita un pago a la
        cuenta que quiera.
        """
        pid = _PRODUCTO_POR_PLAN.get(plan)
        if not pid:
            raise ValueError(
                f"plan sin product_id configurado: {plan!r} "
                f"(esperado uno de {sorted(k for k, v in _PRODUCTO_POR_PLAN.items() if v)})")

        s = self._client.checkout_sessions.create(
            product_cart=[{"product_id": pid, "quantity": 1}],
            return_url=return_url,
            metadata={"account_id": str(account_id), "plan": plan},
        )
        d = s.model_dump() if hasattr(s, "model_dump") else dict(s)
        return {"checkout_url": d.get("checkout_url"), "session_id": d.get("session_id")}

    # ── 3/3 ──────────────────────────────────────────────────────────────────────
    def consultar_estado(self, external_id: str) -> Optional[EstadoRemoto]:
        try:
            sub = self._client.subscriptions.retrieve(external_id)
        except Exception:
            return None  # no lo conoce, o la API falló: el caller no cambia nada
        d = sub.model_dump() if hasattr(sub, "model_dump") else dict(sub)
        crudo = str(d.get("status") or "").strip().lower()
        return EstadoRemoto(
            external_id=external_id,
            # Estado no mapeado → TERMINAL (no otorga). Fail-closed también acá.
            status=_STATUS_REMOTO.get(crudo, effects.TERMINAL),
            current_period_end=_iso(d.get("next_billing_date")),
            raw=d,
        )
