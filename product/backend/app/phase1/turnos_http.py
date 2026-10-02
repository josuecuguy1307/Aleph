"""turnos_http.py — PARAR UN TURNO DE UNA VÍA HTTP. El contrato que faltaba.

Gate 2 · F6-cierre · Obra C.

⚠️ POR QUÉ EXISTE.

F4b construyó el botón de parar y lo cableó al BYO-CLI: ahí parar significa **matar un
proceso hijo**, y `stop_turn` lo hace. Pero las vías HTTP —Ollama local y cualquier API—
no tienen proceso hijo: tienen un socket. F6 lo midió y lo declaró `no_medible` con esas
palabras: «no hay proceso local que matar. Haría falta un contrato de cancelación para
vías HTTP». Esto es ese contrato.

**Parar una vía HTTP es cerrar la conexión.** No es un detalle de implementación: mientras
el socket siga abierto el proveedor sigue generando y —en las vías con costo— sigue
cobrando. Un «parar» que sólo dejara de dibujar en la pantalla sería teatro: el usuario ve
que se detuvo y la factura dice que no.

──────────────────────────────────────────────────────────────────────────────────────
LAS DECISIONES, con su motivo

  1. **EL MISMO VOCABULARIO DE F2d, no uno nuevo.** Los dos resultados son
     `turno_detenido` y `no_habia_turno`, y los dos son 200. Pedir parar algo que ya
     terminó es lo NORMAL —el usuario aprieta justo cuando llegaba la respuesta— y
     contestar 4xx ahí convierte un final feliz en un cartel rojo. Inventar un tercer
     resultado para HTTP habría partido en dos un vocabulario que ya estaba cerrado.

  2. **CERRAR ES IDEMPOTENTE Y NUNCA LEVANTA.** Cerrar un socket que ya murió es normal
     (el turno terminó solo mientras viajaba el pedido de parar). Si `close()` explota, el
     turno igual queda marcado como detenido: el estado que ve el usuario no puede depender
     de que un socket se despida bien.

  3. **LA MARCA VIVE DESPUÉS DEL CIERRE.** Al cerrar el socket, el generador que lo estaba
     leyendo se despierta con una excepción de red cualquiera —«connection closed»— que es
     indistinguible de un corte real. Sin `fue_detenido()` esa excepción se traduciría como
     un fallo de red y la Sala mostraría «se cortó la conexión» sobre un botón que el
     usuario acaba de apretar. Por eso la marca sobrevive al cierre y se consulta al
     traducir: **quién causó el corte es parte del corte**.

  4. **EL REGISTRO SE LIMPIA SIEMPRE**, en el `finally` del turno. Un registro que crece es
     una fuga de memoria con forma de tabla, y peor: un id viejo reusado pararía un turno
     que no es.
"""
from __future__ import annotations

import socket
import threading
import uuid
from typing import Any, Optional

#: Resultados — los MISMOS de F2d (`cli_brain.base`), a propósito.
TURNO_DETENIDO = "turno_detenido"
NO_HABIA_TURNO = "no_habia_turno"

_LOCK = threading.RLock()
_VIVOS: dict[str, "_Turno"] = {}
#: Los ids detenidos que ya salieron del registro. Acotado: sólo interesa el ratito entre
#: que se cierra el socket y que el generador se entera. Sin tope, esto sería la fuga que
#: el registro evita.
_DETENIDOS: list[str] = []
_TOPE_DETENIDOS = 64


class _Turno:
    __slots__ = ("id", "via", "resp", "detenido")

    def __init__(self, turno_id: str, via: str) -> None:
        self.id = turno_id
        self.via = via
        self.resp: Any = None          # la respuesta HTTP viva, cuando ya se abrió
        self.detenido = False


def abrir(via: str) -> str:
    """Registra un turno HTTP en vuelo y devuelve su id. El id viaja al cliente por el
    canal `turno` del SSE — el MISMO que ya usa el BYO-CLI, para que la Sala no tenga que
    aprender un segundo dialecto para apretar el mismo botón."""
    tid = "http-" + uuid.uuid4().hex[:12]
    with _LOCK:
        _VIVOS[tid] = _Turno(tid, via)
    return tid


def atar(turno_id: str, resp: Any) -> None:
    """Ata la conexión abierta al turno. Se llama apenas existe la respuesta.

    Puede llegar un `detener` ANTES de que el socket exista (el usuario apretó mientras el
    pedido viajaba). En ese caso la marca ya está puesta y acá se cierra en el acto: sin
    esto, el turno arrancaría a generar justo después de que le pidieron que no.
    """
    with _LOCK:
        t = _VIVOS.get(turno_id)
        if t is None:
            return
        t.resp = resp
        ya = t.detenido
    if ya:
        _cerrar(resp)


def _cerrar(resp: Any) -> None:
    """Cierra la conexión desde OTRO hilo. Y `close()` solo NO alcanza.

    ⚠️ `HTTPResponse.close()` marca el objeto como cerrado y suelta la conexión, pero **no
    despierta a un `read()` que ya está bloqueado en otro hilo** — y ése es justamente el
    caso: el turno se lee en un hilo del threadpool y el `detener` llega por el loop. Con
    sólo `close()`, el lector sigue esperando hasta que el proveedor termine solo, y
    entonces «parar» es una coincidencia con buena prensa.

    Lo que sí lo despierta es un `shutdown()` sobre el socket crudo: corta las dos
    direcciones y el `recv` bloqueado vuelve en el acto. Va PRIMERO; el `close()` queda
    después para liberar el recurso. Los dos en `try` por separado a propósito: si el
    socket ya murió, el `shutdown` levanta y el `close` tiene que correr igual.

    Es el MISMO arreglo que `assembler/turnos_obra._cerrar_socket`, que lo midió contra un
    proveedor falso callado 8 s: sin el `shutdown`, cortaba «a los 8,01 s» — o sea nunca.
    Este módulo nació con la mitad del par y por eso hereda la conclusión, no la duda.
    """
    try:
        _sock = getattr(getattr(resp, "fp", None), "raw", None)
        _sock = getattr(_sock, "_sock", None)
        if _sock is not None:
            _sock.shutdown(socket.SHUT_RDWR)
    except Exception:                              # noqa: BLE001 — ya estaba muerto: da igual
        pass
    try:
        resp.close()
    except Exception:                              # noqa: BLE001 — ver decisión 2
        pass


def detener(turno_id: str) -> dict:
    """Para el turno. Respuesta TIPADA y RESUELVE SIEMPRE (F2d)."""
    with _LOCK:
        t = _VIVOS.get(turno_id)
        if t is None:
            return {"resultado": NO_HABIA_TURNO, "turno_id": turno_id}
        t.detenido = True
        resp = t.resp
        _marcar_detenido(turno_id)
    if resp is not None:
        _cerrar(resp)                              # fuera del lock: cerrar puede bloquear
    return {"resultado": TURNO_DETENIDO, "turno_id": turno_id, "via": t.via}


def _marcar_detenido(turno_id: str) -> None:
    _DETENIDOS.append(turno_id)
    if len(_DETENIDOS) > _TOPE_DETENIDOS:
        del _DETENIDOS[: len(_DETENIDOS) - _TOPE_DETENIDOS]


def fue_detenido(turno_id: Optional[str]) -> bool:
    """¿Este corte lo pidió el usuario? Ver decisión 3 — sin esto, parar se lee «se cayó
    la red», que es culparle al proveedor algo que hizo el botón."""
    if not turno_id:
        return False
    with _LOCK:
        t = _VIVOS.get(turno_id)
        if t is not None and t.detenido:
            return True
        return turno_id in _DETENIDOS


def cerrar(turno_id: Optional[str]) -> None:
    """Saca el turno del registro. Va en el `finally` del turno, pase lo que pase."""
    if not turno_id:
        return
    with _LOCK:
        _VIVOS.pop(turno_id, None)


def vivos() -> list[dict]:
    """Lo que está en vuelo. Para forense y para la vara."""
    with _LOCK:
        return [{"turno_id": t.id, "via": t.via, "detenido": t.detenido,
                 "atado": t.resp is not None} for t in _VIVOS.values()]


__all__ = ["TURNO_DETENIDO", "NO_HABIA_TURNO", "abrir", "atar", "detener",
           "fue_detenido", "cerrar", "vivos"]
