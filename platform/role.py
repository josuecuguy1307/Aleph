"""role.py — LA FRONTERA cliente / plano de control. [Casa 2 · Fase 2 · paso 2.0]

Hasta acá no existía. `main.py` montaba sus 23 routers sin un solo condicional y
`deploy/preparar_arbol.sh` copiaba el árbol entero, así que el MISMO binario servía el
webhook de pagos y la memoria del agente. Mientras todo corría en Render daba igual;
empaquetar el cliente con PyInstaller convierte eso en **meter el webhook de Dodo en la
máquina del usuario**.

Este módulo es esa frontera, y es un solo archivo a propósito: lo caro de Fase 2 no es
traducir SQL (está concentrado en 7 archivos), es decidir qué es de quién.

    ALEPH_ROLE = "control"   el plano de control (Render): pagos, tier, Motor B
    ALEPH_ROLE = "client"    el Aleph que corre en la máquina del usuario

⚠️ EL DEFAULT ES "client", Y ES DELIBERADO — fail-closed. Un rol sin declarar NO puede
exponer la superficie de pagos: el peor caso de equivocarse hacia `client` es que un
servidor no arranque su webhook (ruidoso, se ve en 30 segundos); el de equivocarse hacia
`control` es un binario en la máquina de un usuario con el webhook de Dodo colgando
(silencioso, y nadie se entera). Entre romper ruidoso y filtrar callado, se rompe ruidoso.

⚠️ CONSECUENCIA OPERATIVA: producción DEBE declarar `ALEPH_ROLE=control` (está en
`deploy/render.yaml`). Si esa env no llega al contenedor, el plano de control arranca como
`client` y **deja de servir el webhook de pagos**. Por eso `describe()` lo loguea al
arrancar: el rol tiene que ser visible en la primera línea del log, no deducible.
"""
from __future__ import annotations

import os

CONTROL = "control"
CLIENT = "client"
_VALIDOS = (CONTROL, CLIENT)


def current() -> str:
    """El rol de ESTE proceso. Default fail-closed a `client` (ver cabecera)."""
    raw = (os.environ.get("ALEPH_ROLE") or "").strip().lower()
    return raw if raw in _VALIDOS else CLIENT


def is_control() -> bool:
    return current() == CONTROL


def is_client() -> bool:
    return current() == CLIENT


def describe() -> str:
    """Línea de arranque. Que el rol se LEA, no se deduzca."""
    r = current()
    crudo = (os.environ.get("ALEPH_ROLE") or "").strip()
    if not crudo:
        return (f"ALEPH_ROLE sin declarar → asumiendo '{r}' (fail-closed). "
                f"El plano de control DEBE declarar ALEPH_ROLE=control.")
    if crudo.lower() not in _VALIDOS:
        return f"ALEPH_ROLE='{crudo}' no es válido → asumiendo '{r}'. Válidos: {_VALIDOS}."
    return f"ALEPH_ROLE={r}"


# ── QUÉ TABLA ES DE QUIÉN ─────────────────────────────────────────────────────────
# Fuente de verdad EJECUTABLE de la decisión, no un comentario en un MD que se
# desactualiza. El schema SQLite del cliente (paso 2.1) se deriva de acá.

#: Viven en el SQLite del usuario. Son SUS datos: nunca se sincronizan solos.
TABLAS_CLIENTE = frozenset({
    "users",              # identidad local. OJO: `tier` acá NO es autoritativo (D1) —
                          # es caché. La autoridad vive en el plano de control.
    "puppets", "runs", "outputs", "historial",
    "keys",               # BYOK cifrada. Que viva local ES la tesis: la llave del usuario
                          # no tiene por qué pasar por nuestros servidores.
    "chats", "chat_messages",
    "methods", "method_runs",
    "instructions",
    "agent_memories", "shared_memories", "account_memories",
    "knowledge_docs", "knowledge_chunks",
    "job_queue",          # cola durable — ver el spike de SKIP LOCKED→WAL en el plan
    "held_actions", "inspect_leases",
})

#: NUNCA salen del plano de control. Son la autoridad de plata y de plan.
TABLAS_CONTROL = frozenset({
    "subscriptions", "payment_webhook_events", "tier_audit",
    "billing_ledger", "billing_runs_ingested", "billing_quota", "billing_stripe_events",
})

#: Local y SIN SYNC (D3). El moat NO se alimenta exfiltrando al usuario: la señal que
#: importa —qué intenta construir la gente— ya pasa por el plano de control, porque
#: construir es premium y re-verifica contra el Motor B. Meter un canal de telemetría
#: escondido en el cliente traicionaría la tesis local-first, que es EL diferenciador.
#: Si algún día se agrega: opt-in, anonimizado, agregado, patrones y NUNCA contenido.
TABLAS_LOCALES_SIN_SYNC = frozenset({"instrumentation_logs"})

#: Infra del runner de migraciones — existe en las dos bases.
TABLAS_AMBAS = frozenset({"schema_migrations"})

#: SOLO CLIENTE — sin contraparte en Postgres. Rompen el espejo A PROPÓSITO.
#: Las de `TABLAS_CLIENTE` viven en el SQLite del usuario pero TIENEN gemela en
#: `platform/db/migrations/*.sql`; estas no. Van en su propio frozenset para que la
#: excepción se DECLARE en vez de deducirse del silencio: el próximo que agregue una
#: tabla tiene que elegir set, y elegir es leer por qué.
#:   · conexiones — el registro de CONTRACT-CONEXION-v1 §1. Una conexión MCP solo
#:     existe en el escritorio: el control plane no spawnea servidores locales, así
#:     que no hay nada que espejar allá.
TABLAS_SOLO_CLIENTE = frozenset({"conexiones", "modelos_estado"})


def tablas_del_cliente() -> frozenset:
    """Lo que el schema SQLite del cliente tiene que crear (paso 2.1)."""
    return (TABLAS_CLIENTE | TABLAS_LOCALES_SIN_SYNC
            | TABLAS_SOLO_CLIENTE | TABLAS_AMBAS)


__all__ = [
    "CONTROL", "CLIENT", "current", "is_control", "is_client", "describe",
    "TABLAS_CLIENTE", "TABLAS_CONTROL", "TABLAS_LOCALES_SIN_SYNC",
    "TABLAS_SOLO_CLIENTE", "TABLAS_AMBAS",
    "tablas_del_cliente",
]
