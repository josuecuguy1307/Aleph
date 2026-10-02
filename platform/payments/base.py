"""base.py — LA INTERFAZ del procesador de pagos. Vocabulario propio, cero SDKs.

Step 5 · Casa 1 · P2 · §4-bis de la directiva:
    "el plano de control define una interfaz mínima (verificar_webhook,
     evento→efecto_de_tier, consultar_estado) y Dodo es UNA implementación detrás.
     Cambiar a Paddle/Stripe mañana = swap de un módulo, no cirugía. Nada del resto
     del sistema importa el SDK de Dodo directo."

TRES métodos. Ni uno más. La tentación de agregar `crear_checkout`, `cancelar`,
`listar_facturas` "por si acaso" se resiste: una interfaz crece cuando hay un SEGUNDO
implementador que la valida, no antes. Hoy hay uno. (El checkout de P4 vive del lado
Dodo por ahora, precisamente porque no sabemos qué forma tendrá en Paddle.)

EL ANTIPATRÓN QUE ESTO EXISTE PARA IMPEDIR — está vivo en el árbol y es el ejemplo:
`product/backend/app/phase1/billing_router.py:145` hace `from app.phase1 import
stripe_billing` DENTRO del handler HTTP. El SDK del procesador quedó soldado al router;
cambiar de proveedor obliga a tocar el endpoint. Acá no: el router habla `base`.
Un test de contrato (tests/phase1/test_payments_contract.py) FALLA la suite entera si
alguien importa el SDK fuera de su adaptador.
"""
from __future__ import annotations

import abc
import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Optional


class FirmaInvalida(Exception):
    """La firma del webhook no verifica. El caller responde 401 y NO persiste nada.

    Excepción propia a propósito: el router no debe atrapar excepciones del SDK de
    ningún procesador — eso volvería a soldar el proveedor al endpoint.
    """


@dataclass(frozen=True)
class EventoVerificado:
    """Un webhook cuya firma YA fue verificada. Todavía sin interpretar."""

    webhook_id: str          # header `webhook-id` — LA llave de idempotencia (P0 lo confirmó)
    tipo: str                # string CRUDO del procesador ('payment.succeeded'); forense, no se enruta con él
    at: Optional[_dt.datetime]   # timestamp del PAYLOAD, para ordenar (los webhooks llegan desordenados)
    payload: dict = field(default_factory=dict)   # el evento tal cual, ya verificado


@dataclass(frozen=True)
class EfectoDeTier:
    """Lo que UN evento le hace a la relación comercial de UNA cuenta.

    Es la traducción al vocabulario propio (platform/payments/effects). El adaptador
    produce esto; nadie aguas abajo vuelve a mirar el payload del procesador.
    """

    account_id: Optional[str]     # de la metadata del checkout (verificado en P0). None = no atribuible.
    external_id: str              # id del lado del procesador: subscription_id, o payment_id si es one-time
    plan: str                     # 'monthly' | 'annual' | 'lifetime'
    status: str                   # vocabulario de effects: alta|renovada|en_gracia|terminal|baja
    current_period_end: Optional[_dt.datetime] = None
    grace_until: Optional[_dt.datetime] = None
    event_at: Optional[_dt.datetime] = None


@dataclass(frozen=True)
class EstadoRemoto:
    """La verdad del procesador sobre una suscripción, para reconciliar (P5)."""

    external_id: str
    status: str                                   # ya traducido al vocabulario propio
    current_period_end: Optional[_dt.datetime] = None
    raw: Optional[dict] = None                    # el objeto crudo, sólo para diagnóstico


class ProcesadorDePagos(abc.ABC):
    """El contrato. Una implementación por procesador, en su propio módulo."""

    #: Identificador que se persiste en `subscriptions.processor`.
    nombre: str = "abstracto"

    @abc.abstractmethod
    def verificar_webhook(self, raw_body: bytes, headers: dict) -> EventoVerificado:
        """Body CRUDO + headers → evento verificado. Lanza FirmaInvalida si no verifica.

        El body llega sin parsear y sin tocar: verificar primero, interpretar después
        (regla 1 del §2). Parsear antes de verificar es procesar entrada no confiable.
        """

    @abc.abstractmethod
    def evento_a_efecto(self, evento: EventoVerificado) -> Optional[EfectoDeTier]:
        """Evento verificado → efecto sobre el tier, o None si el evento no nos incumbe.

        None NO es un error: la mayoría de los eventos de un procesador (facturas,
        entitlements, créditos) no mueven la frontera free/premium. El caller los marca
        'ignored_unknown' y los ACKea igual — un evento sin ACK se reintenta 8 veces.

        REGLA DURA: ante un evento que no se entiende, None. Jamás inferir un ascenso.
        """

    @abc.abstractmethod
    def consultar_estado(self, external_id: str) -> Optional[EstadoRemoto]:
        """El estado REAL según el procesador. Red de seguridad si un webhook se perdió
        sus 8 reintentos. None si el procesador no lo conoce."""


# ── Registro ────────────────────────────────────────────────────────────────────
# El import del adaptador concreto es PEREZOSO y vive acá adentro: así el resto del
# backend puede importar `base` sin arrastrar el SDK de ningún procesador.

def get_procesador(nombre: str = "dodo", **kw) -> ProcesadorDePagos:
    """Devuelve el adaptador por nombre. El ÚNICO lugar del árbol que sabe qué
    implementaciones existen."""
    n = (nombre or "").strip().lower()
    if n == "dodo":
        from payments.dodo import DodoProcesador
        return DodoProcesador(**kw)
    raise ValueError(f"procesador desconocido: {nombre!r}")
