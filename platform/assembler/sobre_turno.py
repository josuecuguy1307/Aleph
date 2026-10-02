"""sobre_turno — el sobre de un turno (su id y su deadline) del BORDE al SPAWN.

QUÉ ES EL SOBRE Y POR QUÉ NECESITA UN CANAL PROPIO
--------------------------------------------------
Un turno de un workspace heredado nace afuera (en el harness del stack) y termina adentro
(en el `claude -p` / `codex exec` que spawnea el server BYO-CLI). Entre esas dos puntas hay
DOS saltos HTTP:

    stack ──(1)──▶ borde de Aleph :8330 ──(2)──▶ server de CLIs :8926 ──▶ spawn

Dos datos tienen que sobrevivir los dos saltos, y ninguno cabe en el cuerpo OpenAI:

    X-Aleph-Turno-Id        el MISMO id para el pedido y todos sus reintentos
    X-Aleph-Deadline-Epoch  el MISMO instante absoluto de corte para todos ellos

EL AGUJERO QUE CIERRA ESTE MÓDULO, MEDIDO 2026-08-15 CONTRA LA `.app` INSTALADA
-------------------------------------------------------------------------------
El salto (2) NO existía. El par falsable, mismo minuto, mismo sobre:

    directo a :8926 con el sobre   → turno_id `PRUEBA-DIRECTO-B`, remaining_s = 24,98  ✔
    por el borde con EL MISMO sobre → turno_id inventado,          remaining_s = 180,0  ✘

O sea que el lector del `:8926` (`server.py`) siempre estuvo bien y el que tiraba el sobre
era el borde: fabricaba un `chatcmpl-…` nuevo y arrancaba un deadline nuevo de 180 s.

**La consecuencia se midió en el turno Apple**: sus 5 ejecuciones del CLI recibieron
`remaining_s = 180,0` CADA UNA. El techo de un turno no era 180 s: era 180 s *por
ejecución* — y con la multiplicación de reintentos intacta (6 spawns medidos), hasta
6 × 180 = 1.080 s.

POR QUÉ UN ContextVar Y NO UN PARÁMETRO MÁS
--------------------------------------------
Entre el handler del borde y el `urllib.request.Request` que sale al `:8926` hay una
cadena larga (`workspace_brain_complete` → preflight → executor → resolución de modelo →
`_preparar_pedido`) cuyas firmas no hablan de turnos. Enhebrar dos parámetros por toda esa
cadena toca decenas de sitios que no tienen nada que ver con esto, y cada uno es una
oportunidad de romper algo que hoy anda.

Un `ContextVar` viaja solo: se copia al thread del threadpool (FastAPI corre los endpoints
sync ahí, y `iterate_in_threadpool` copia el contexto) y a las tasks hijas de asyncio. Se
pone y se saca con token en un `try/finally`, así que no se filtra al pedido siguiente.

**El sobre NO se manda a cualquiera.** Sale sólo cuando el destino es el server BYO-CLI
local (`_is_cli_brain_endpoint`): un id de intento nuestro y un deadline nuestro son datos
de control internos, no metadata para un proveedor remoto.
"""
from __future__ import annotations

import math
from contextvars import ContextVar, Token
from typing import Optional, Tuple

#: `(turno_id, deadline_epoch, sesion)` del turno en curso, o `None` si no hay sobre.
_SOBRE: ContextVar[Optional[Tuple[Optional[str], Optional[float], Optional[str]]]] = (
    ContextVar("aleph_sobre_turno", default=None))

#: Los nombres, en un solo lugar: los escribe el stack, los reenvía el borde y los lee el
#: server de CLIs. Que vivan acá evita la tercera copia del string.
H_TURNO = "X-Aleph-Turno-Id"
H_DEADLINE = "X-Aleph-Deadline-Epoch"
#: La CONVERSACIÓN (no el intento). Viaja como cabecera hasta el borde y de ahí al `:8926`
#: **en el cuerpo**, porque así lo lee el server (`req["sesion"]`) y ese contrato ya existe.
H_SESION = "X-Aleph-Sesion"


def _turno_limpio(valor) -> Optional[str]:
    """Un id con CR/LF es una inyección de cabecera. Se descarta entero, no se recorta."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s or "\r" in s or "\n" in s:
        return None
    return s[:200]


def _deadline_limpio(valor) -> Optional[float]:
    """Un deadline que no es un número finito no es un deadline: se descarta."""
    if valor is None or valor == "":
        return None
    try:
        d = float(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    return d if math.isfinite(d) else None


def poner(turno_id=None, deadline_epoch=None, sesion=None) -> Token:
    """Deja el sobre puesto para todo lo que se llame desde acá. Devuelve el token.

    Siempre devuelve token —incluso con las tres partes en None— para que el llamador
    pueda hacer `finally: sacar(token)` sin ramas."""
    return _SOBRE.set((_turno_limpio(turno_id), _deadline_limpio(deadline_epoch),
                       _turno_limpio(sesion)))


def sacar(token: Token) -> None:
    """Restaura lo que había. Va SIEMPRE en un `finally`: un sobre que sobrevive a su
    pedido le pondría el id de un turno ajeno al siguiente."""
    try:
        _SOBRE.reset(token)
    except ValueError:                                  # noqa: BLE001 — otro contexto
        _SOBRE.set(None)


def actual() -> Tuple[Optional[str], Optional[float], Optional[str]]:
    """`(turno_id, deadline_epoch, sesion)` — todo `None` si no hay sobre puesto."""
    v = _SOBRE.get()
    return (None, None, None) if v is None else v


def cabeceras(es_borde_cli: bool) -> dict:
    """Las cabeceras del sobre para ESTE destino. Vacío si no hay sobre o no es el nuestro.

    `es_borde_cli` no se deduce acá a propósito: quien conoce el destino es el que arma el
    pedido, y este módulo no tiene por qué saber de URLs."""
    if not es_borde_cli:
        return {}
    turno_id, deadline, _sesion = actual()
    out = {}
    if turno_id:
        out[H_TURNO] = turno_id
    if deadline is not None:
        out[H_DEADLINE] = "%.6f" % deadline
    return out


def campos_del_cuerpo(es_borde_cli: bool) -> dict:
    """Lo del sobre que viaja en el CUERPO, no en cabeceras. Hoy: la conversación.

    Va en el cuerpo porque el server de CLIs lee la clave de conversación de ahí
    (`req["sesion"]`, `cli_brain/server.py`) y ese contrato ya existe y está probado con
    Claude. Inventarle una cabecera nueva sería un segundo camino para el mismo dato."""
    if not es_borde_cli:
        return {}
    _turno, _deadline, sesion = actual()
    return {"sesion": sesion} if sesion else {}
