#!/usr/bin/env python3
"""cola_local.py — LA COLA DE LA VÍA LOCAL (Gate 2 · F5).

EL AGUJERO QUE CIERRA (auditoría 4 §3.1, medido): Ollama **no rechaza, encola**. Tres
requests simultáneos dieron 3× HTTP 200 con latencia 7,9 → 15 → 23 s; cero errores, cero
503. Y encola porque `OLLAMA_NUM_PARALLEL` vale **1** desde el commit `20c3266e`
(2025-07-08): el semáforo del runner tiene peso 1 (`llm/llama_server.go:922`), así que el
segundo pedido **espera** en vez de fallar.

Eso significa que la concurrencia local no se ve como concurrencia: se ve como **latencia
acumulada**, y sin una cola nuestra el usuario mira una barra girar sin saber que hay otro
pedido adelante. El cliente que se cansa y corta produce el famoso `None` — que nunca vino
del servidor (§3.1: «cero `None`»), vino de nosotros.

    SUBIR `NUM_PARALLEL` NO ES LA SOLUCIÓN, Y ESTÁ MEDIDO POR QUÉ: Ollama pide
    `-c NumCtx*numParallel` al runner, así que duplicar el paralelismo **duplica el KV
    cache** — en una máquina de memoria unificada eso es memoria real que sale del mismo
    lado. El default 1 se respeta; lo que se agrega es que la espera sea VISIBLE.

EL PATRÓN es el `SlotPool` de F2b (`cli_brain/slots.py`), **adaptado y no importado**, y la
razón es de capas: `slots.py` modela la ventana de una SUSCRIPCIÓN (pausa por `resetsAt`,
serialización por provider, causas con `origen: "cli"`). Acá no hay suscripción ni ventana
que se agote: hay un proceso local con un semáforo de peso 1. Importarlo ataría el runtime
local al paquete BYO-CLI y arrastraría una capa de pausa que en local no significa nada.

    PROPUESTA, no hecha: si alguna vez hay un TERCER consumidor con la misma forma
    (techo + rechazo tipado), el pool común sale de acá y de `slots.py` a un módulo
    compartido. Con dos, extraerlo es abstraer de más.

QUIÉN FRENÓ, DICHO SIN AMBIGÜEDAD. Cuando rechaza ESTA cola el `origen` es `"aleph"` —
somos nosotros, con nuestro techo— y la evidencia dice que el motivo de fondo es que el
runtime serializa. Cuando rechaza el runtime (503 con >512 pendientes, `sched.go:88,207` →
`routes.go:3083`) el `origen` es `"runtime"`, y eso lo emite `errores_modelo.desde_ollama`
desde F1b, no este módulo. Fundir las dos cosas es el defecto que la auditoría 1 le midió
a LiteLLM y que F2b ya se negó a repetir.

    GATE 2 · F1c: la CAUSA de este rechazo pasó de `rate_limit` a `runtime_ocupado`. El
    `origen` de arriba no se toca — sigue siendo lo que separa quién frenó de por qué.
    El motivo del cambio está en `causa_de`.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

#: UNO, igual que el `OLLAMA_NUM_PARALLEL` del runtime. No es timidez: con el semáforo del
#: runner en peso 1, un segundo turno nuestro no corre en paralelo — se sienta a esperar
#: adentro de Ollama, que es exactamente lo que esta cola viene a hacer visible.
MAX_LOCAL = int(os.environ.get("PUPPET_OLLAMA_SLOTS", "1"))

#: Cuánto espera un turno por su lugar antes de que se lo rechace TIPADO. `0` = no espera
#: (rechazo inmediato, como F2b). Un poco de espera evita rechazar por 200 ms de solape.
ESPERA_S = float(os.environ.get("PUPPET_OLLAMA_ESPERA", "0"))

COLA_OCUPADA = "cola_local_llena"


def activa() -> bool:
    """LA PERILLA. En `0` no hay cola: cada pedido sale directo, como antes de F5.
    Se lee en cada llamada — la vara la prende y la apaga sin reimportar."""
    return (os.environ.get("PUPPET_OLLAMA_COLA", "1").strip().lower()
            not in ("0", "false", "no", "off"))


class SinTurnoLocal(RuntimeError):
    """No hay lugar en la cola local. Lleva con qué explicarlo."""

    def __init__(self, motivo: str = COLA_OCUPADA, *, activos: int = 0, limite: int = 0,
                 esperado_s: float = 0.0):
        self.motivo = motivo
        self.activos = activos
        self.limite = limite
        self.esperado_s = esperado_s
        super().__init__(f"{motivo} ({activos}/{limite})")


class ColaLocal:
    """El contador de turnos contra el runtime local. Puro salvo el reloj."""

    def __init__(self, limite: int = MAX_LOCAL):
        self._lock = threading.Lock()
        self._libre = threading.Condition(self._lock)
        self._limite = max(1, int(limite))
        self._activos = 0
        self.rechazos = 0
        self.pico = 0

    def pedir(self, *, espera_s: Optional[float] = None) -> None:
        """Toma un turno o levanta `SinTurnoLocal`. Nunca espera para siempre."""
        if not activa():
            return
        tope = ESPERA_S if espera_s is None else float(espera_s)
        t0 = time.monotonic()
        with self._libre:
            if self._activos >= self._limite and tope > 0:
                # Espera ACOTADA: el punto es no rechazar por un solape de milisegundos,
                # no convertir la cola en otro lugar donde colgarse.
                self._libre.wait_for(lambda: self._activos < self._limite, timeout=tope)
            if self._activos >= self._limite:
                self.rechazos += 1
                raise SinTurnoLocal(COLA_OCUPADA, activos=self._activos, limite=self._limite,
                                    esperado_s=round(time.monotonic() - t0, 3))
            self._activos += 1
            self.pico = max(self.pico, self._activos)

    def soltar(self) -> None:
        if not activa():
            return
        with self._libre:
            self._activos = max(0, self._activos - 1)
            self._libre.notify()

    def turno(self, *, espera_s: Optional[float] = None):
        """`with COLA.turno(): ...` — suelta pase lo que pase, incluso si el turno revienta."""
        cola = self

        class _T:
            def __enter__(self_inner):
                cola.pedir(espera_s=espera_s)
                return self_inner

            def __exit__(self_inner, *exc):
                cola.soltar()
                return False

        return _T()

    def estado(self) -> dict:
        with self._lock:
            return {"activa": activa(), "limite": self._limite, "activos": self._activos,
                    "pico": self.pico, "rechazos": self.rechazos, "espera_s": ESPERA_S}

    def reiniciar(self) -> None:
        with self._libre:
            self._activos = 0
            self.rechazos = 0
            self.pico = 0
            self._libre.notify_all()


#: La instancia del proceso.
COLA = ColaLocal()


def causa_de(e: SinTurnoLocal) -> Optional[dict]:
    """`SinTurnoLocal` → `CausaModelo` serializada, del vocabulario cerrado.

    ── F1c · CAMBIO DE VEREDICTO DECLARADO ────────────────────────────────────────
    ANTES: `rate_limit` («429 — hay que esperar»), que describía bien lo que hay que hacer
    pero le prestaba al usuario una palabra que significa OTRA COSA: `rate_limit` es la
    ventana o la cuota de un PROVEEDOR, la que se agota y hay que esperar a que resetee.
    Acá no hay cuota que se agote: hay un proceso local con un semáforo de peso 1 y otro
    pedido adelante, y eso dura lo que dure ese pedido.

    AHORA: `runtime_ocupado`. Y es la misma decisión que F1c tomó en `slots.py` — nuestro
    techo delante de un CLI ocupado es `cli_ocupado`, nuestro techo delante de un runtime
    ocupado es `runtime_ocupado`— con el mismo efecto sobre el vocabulario: **`rate_limit`
    pasa a significar UNA sola cosa** en todo el producto, la ventana del proveedor.

    LO QUE NO CAMBIA, porque es la razón por la que este módulo existe: el `origen` sigue
    siendo **`aleph`**. El que frenó fue NUESTRO techo, no el runtime — el runtime habría
    encolado y contestado 200 (medido, auditoría 4 §3.1). Que la razón de fondo sea del
    runtime (serializa con `NUM_PARALLEL=1`) va en la evidencia, no en el `origen`:
    confundir «quién frenó» con «por qué» es exactamente lo que F2b se negó a hacer, y la
    causa nueva no lo funde — lo dice el `origen`, como siempre. Cuando el que rechaza es
    el runtime de verdad (503 con >512 pendientes) el `origen` es `"runtime"`, y eso sale
    de `errores_modelo.desde_ollama`, no de acá.
    """
    try:
        try:
            import errores_modelo as _tr                  # type: ignore
        except ImportError:                                # pragma: no cover
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import errores_modelo as _tr                  # type: ignore
        return _tr.CausaModelo(
            causa=getattr(_tr, "RUNTIME_OCUPADO", _tr.RATE_LIMIT), estado=_tr.ROTO,
            detalle=("Hay otro pedido corriendo en el runtime local. Espera a que "
                     "termine: los modelos locales atienden de a uno.")[:200],
            fuente=_tr.FUENTE_OLLAMA,
            evidencia={"motivo": e.motivo, "origen": "aleph",
                       "activos": e.activos, "limite": e.limite,
                       "porque": "el runtime serializa (OLLAMA_NUM_PARALLEL=1)"},
            reintentable=True).como_dict()
    except Exception:                                      # noqa: BLE001 — jamás rompe el turno
        return None


__all__ = ["ColaLocal", "COLA", "SinTurnoLocal", "causa_de", "activa",
           "MAX_LOCAL", "ESPERA_S", "COLA_OCUPADA"]
