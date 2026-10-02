"""turnos_obra.py — PARAR UNA OBRA EN VUELO. El hermano que le faltaba a `turnos_http`.

Gate 4 · Fase 5 · obra 5.2.

⚠️ POR QUÉ EXISTE.

F6 construyó `turnos_http` y cerró el chat: parar una vía HTTP es cerrar el socket, y el
chat lo hace. Pero **una OBRA no se podía parar**, y el censo lo midió con nombre:
`grep -n "turnos_http" executor.py recipe_assembler.py` → **0**.

Y no fallaba: **no existía**. Medido en la cara: el `turno_id` sólo viaja por el SSE del
chat (`router.py:2655`), así que durante una obra `pararTurno()` encuentra `ST.turnoId`
vacío y sale sin hacer nada (`sala.html:5678`). El usuario aprieta ⏹, la pantalla cierra el
turno, y del otro lado el motor sigue: llama al modelo, ejecuta tools, toca el mundo y
cobra. Con motores pesados (CFD, render, FEM) eso deja de ser una molestia.

──────────────────────────────────────────────────────────────────────────────────────
POR QUÉ NO ALCANZABA CON `turnos_http`

`turnos_http` registra **un socket**. Una obra no tiene un socket: tiene N llamadas al
modelo (una por turno) y M tool-calls, cada una con su propia vida. Un `turno_id` por
socket sería un id nuevo cada turno y el botón nunca sabría a cuál apuntarle.

Lo que una obra sí tiene desde el instante cero es el **`space_id`**, y lo elige EL
CLIENTE (`router.py:188` ← `sala.html`). Ésa es la llave: existe **antes** de que el run
exista, así que se puede parar un turno que todavía no arrancó — que es justo el caso que
`turnos_http` tuvo que resolver aparte con su `atar()`.

──────────────────────────────────────────────────────────────────────────────────────
LAS DECISIONES, con su motivo

  1. **VIVE EN `platform/`, NO EN `product/`.** El que tiene que preguntar «¿me pararon?»
     es el motor, y `platform/` no depende de `product/` (regla del árbol, escrita en
     `errores_modelo.py:57`). Por eso este módulo es hermano del assembler y el backend lo
     importa, y no al revés.

  2. **EL MISMO VOCABULARIO, otra vez.** `turno_detenido` y `no_habia_turno`, los dos 200.
     Es el tercer consumidor del mismo par (F2d el BYO-CLI, F6 el HTTP, esta obra las
     obras) y sigue sin hacer falta inventar un resultado nuevo. Pedir parar algo que ya
     terminó es lo NORMAL.

  3. **EL CORTE ES COOPERATIVO, NO UN HACHAZO.** Se marca y el motor mira la marca en tres
     lugares: antes del turno, antes de cada tool-call, y en el socket del modelo. La tool
     que YA arrancó se deja terminar. Matar un proceso a mitad de una escritura es
     exactamente cómo se fabrican los estados falsos que esta obra existe para evitar — y
     además, con el Dueño encendido (`dueno.py:592`) ese proceso puede ser de OTRO run.

  4. **EL HILO SE ADUEÑA.** `tomar()` ata el handle al hilo que corre la obra, así el motor
     pregunta `fue_detenido()` sin argumentos y sin enterarse de qué es un `space_id`. Un
     `assemble_and_run` llamado desde una vara o el CLI —sin nadie que haya abierto un
     handle— contesta `False` siempre: cero cambio para todo lo que no pasa por el
     executor.

  5. **LA MARCA VIVE DESPUÉS DEL CIERRE.** Igual que en `turnos_http:32-37`, y por lo
     mismo: cerrar el socket despierta al lector con un error de red indistinguible de un
     corte real. Sin `fue_detenido()` sobreviviendo al cierre, el botón del usuario se
     leería «se cayó la conexión».

  6. **EL REGISTRO SE LIMPIA SIEMPRE**, en el `finally`. Un registro que crece es una fuga
     con forma de tabla, y un `space_id` reusado pararía una obra que no es.
"""
from __future__ import annotations

import socket
import threading
from typing import Any, Optional

#: Resultados — los MISMOS de F2d y F6, a propósito (decisión 2).
TURNO_DETENIDO = "turno_detenido"
NO_HABIA_TURNO = "no_habia_turno"

#: De quién fue el corte. Se firma con `tool_result.ORIGEN_USUARIO` río arriba; acá sólo
#: se registra el hecho.
_LOCK = threading.RLock()
_VIVAS: dict[str, "_Obra"] = {}
_ALIAS: dict[str, str] = {}            # run_id -> handle (el run_id nace después)
#: Los handles detenidos que ya salieron del registro. Acotado por el mismo motivo que en
#: `turnos_http`: sólo interesa el ratito entre que se marca y que el motor se entera.
_DETENIDAS: list[str] = []
_TOPE_DETENIDAS = 64

_HILO = threading.local()


class _Obra:
    __slots__ = ("handle", "run_id", "detenido", "resp")

    def __init__(self, handle: str) -> None:
        self.handle = handle
        self.run_id: Optional[str] = None
        self.detenido = False
        self.resp: Any = None          # el socket del modelo, cuando hay uno abierto


# ── CICLO DE VIDA ──────────────────────────────────────────────────────────────────

def abrir(handle: Optional[str]) -> Optional[str]:
    """Registra una obra en vuelo bajo el handle que eligió el cliente (`space_id`).

    Sin handle no hay registro y todo lo demás es no-op: un run anónimo (una vara, el CLI,
    un sub-agente) no se puede parar desde afuera y tampoco tiene quién lo pare.
    """
    if not handle:
        return None
    h = str(handle)
    with _LOCK:
        _VIVAS.setdefault(h, _Obra(h))
    return h


def ligar(handle: Optional[str], run_id: Optional[str]) -> None:
    """Ata el `run_id` al handle, en cuanto existe. Un alias, no una segunda llave: parar
    por `run_id` y parar por `space_id` tienen que ser el mismo acto."""
    if not handle or not run_id:
        return
    with _LOCK:
        o = _VIVAS.get(str(handle))
        if o is None:
            return
        o.run_id = str(run_id)
        _ALIAS[str(run_id)] = str(handle)


def tomar(handle: Optional[str]) -> None:
    """Este hilo corre ESA obra. Lo llama el executor antes de entrar al motor."""
    _HILO.handle = str(handle) if handle else None


def soltar() -> None:
    _HILO.handle = None


def handle_del_hilo() -> Optional[str]:
    return getattr(_HILO, "handle", None)


# ── EL SOCKET DEL MODELO ───────────────────────────────────────────────────────────

def atar_socket(resp: Any) -> None:
    """Ata la respuesta HTTP viva del modelo a la obra de ESTE hilo.

    Igual que `turnos_http.atar`: si el corte ya llegó mientras el pedido viajaba, se
    cierra en el acto. Sin esto, una obra parada arrancaría a generar justo después de que
    le pidieron que no — y el proveedor cobra igual.
    """
    h = handle_del_hilo()
    if not h:
        return
    with _LOCK:
        o = _VIVAS.get(h)
        if o is None:
            return
        o.resp = resp
        ya = o.detenido
    if ya:
        _cerrar_socket(resp)


def soltar_socket() -> None:
    """El pedido terminó: la obra sigue viva pero ya no hay socket que cerrar."""
    h = handle_del_hilo()
    if not h:
        return
    with _LOCK:
        o = _VIVAS.get(h)
        if o is not None:
            o.resp = None


def _cerrar_socket(resp: Any) -> None:
    """Cierra el socket del modelo desde OTRO hilo. Y `close()` solo NO alcanza.

    ⚠️ MEDIDO POR LA VARA, y es la diferencia entre parar y decir que se paró.
    `HTTPResponse.close()` marca el objeto como cerrado y suelta la conexión, pero **no
    despierta a un `read()` que ya está bloqueado en otro hilo**: la primera versión de
    esto cortaba recién a los 8,01 s contra un proveedor falso que se quedaba callado 8 s,
    o sea que no cortaba nada — el turno terminaba solo y el «paré» era una coincidencia.
    La marca hacía que igual se leyera `turno_detenido`, así que el defecto habría pasado
    por verde sin la aserción de TIEMPO.

    Lo que sí despierta al lector es un `shutdown()` sobre el socket crudo: le corta las
    dos direcciones y el `recv` bloqueado vuelve en el acto. Va PRIMERO, y el `close()`
    de siempre queda después para liberar el recurso.

    Los dos van en `try` por separado a propósito: si el socket ya murió, el `shutdown`
    levanta y el `close` tiene que correr igual. Cerrar es idempotente y jamás levanta —
    el estado que ve el usuario no puede depender de que un socket se despida bien.

    ── ACEPTA LAS DOS FORMAS: RESPUESTA O CONEXIÓN ────────────────────────────────
    Una `HTTPResponse` guarda su socket en `.fp.raw._sock`; una `HTTPConnection` lo tiene
    en `.sock`. Se buscan las dos porque **atar la conexión es la única forma de poder
    cortar ANTES de que haya respuesta**, y ése es justamente el caso que importa: el CLI
    no manda headers hasta el primer delta, así que durante todo el turno la respuesta
    todavía no existe. Atar sólo respuestas era llegar tarde por definición.
    """
    try:
        _sock = getattr(getattr(resp, "fp", None), "raw", None)
        _sock = getattr(_sock, "_sock", None)
        if _sock is None:
            _sock = getattr(resp, "sock", None)     # una HTTPConnection
        if _sock is not None:
            _sock.shutdown(socket.SHUT_RDWR)
    except Exception:                              # noqa: BLE001 — ya estaba muerto: da igual
        pass
    try:
        resp.close()
    except Exception:                              # noqa: BLE001 — cerrar es idempotente
        pass


# ── PARAR ──────────────────────────────────────────────────────────────────────────

def detener(clave: Optional[str]) -> dict:
    """Para la obra. Respuesta TIPADA y RESUELVE SIEMPRE. Acepta handle o `run_id`."""
    if not clave:
        return {"resultado": NO_HABIA_TURNO, "turno_id": clave}
    k = str(clave)
    with _LOCK:
        h = k if k in _VIVAS else _ALIAS.get(k, "")
        o = _VIVAS.get(h) if h else None
        if o is None:
            return {"resultado": NO_HABIA_TURNO, "turno_id": k}
        o.detenido = True
        resp = o.resp
        _marcar(h)
        if o.run_id:
            _marcar(o.run_id)
        run_id = o.run_id
    if resp is not None:
        _cerrar_socket(resp)                       # fuera del lock: cerrar puede bloquear
    return {"resultado": TURNO_DETENIDO, "turno_id": h, "run_id": run_id, "via": "obra"}


def _marcar(clave: str) -> None:
    _DETENIDAS.append(clave)
    if len(_DETENIDAS) > _TOPE_DETENIDAS:
        del _DETENIDAS[: len(_DETENIDAS) - _TOPE_DETENIDAS]


def fue_detenido(clave: Optional[str] = None) -> bool:
    """¿Pidieron parar esto? Sin argumento, pregunta por la obra de ESTE hilo.

    Ver decisión 5: la marca sobrevive a la salida del registro, porque el motor puede
    enterarse del corte después de que el `finally` ya limpió.
    """
    k = clave if clave is not None else handle_del_hilo()
    if not k:
        return False
    k = str(k)
    with _LOCK:
        h = k if k in _VIVAS else _ALIAS.get(k, "")
        o = _VIVAS.get(h) if h else None
        if o is not None and o.detenido:
            return True
        return k in _DETENIDAS


def cerrar(handle: Optional[str]) -> None:
    """Saca la obra del registro. Va en el `finally` del run, pase lo que pase."""
    if not handle:
        return
    h = str(handle)
    with _LOCK:
        o = _VIVAS.pop(h, None)
        if o is not None and o.run_id:
            _ALIAS.pop(o.run_id, None)


def vivas() -> list[dict]:
    """Lo que está en vuelo. Para forense y para la vara."""
    with _LOCK:
        return [{"handle": o.handle, "run_id": o.run_id, "detenido": o.detenido,
                 "con_socket": o.resp is not None} for o in _VIVAS.values()]


__all__ = ["TURNO_DETENIDO", "NO_HABIA_TURNO", "abrir", "ligar", "tomar", "soltar",
           "handle_del_hilo", "atar_socket", "soltar_socket", "detener", "fue_detenido",
           "cerrar", "vivas"]
