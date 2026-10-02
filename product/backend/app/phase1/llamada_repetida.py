#!/usr/bin/env python3
"""llamada_repetida.py — el mismo pedido, dos veces, segundos aparte: se contesta una.

════════════════════════════════════════════════════════════════════════════════
EL NÚMERO, Y LA CORRECCIÓN QUE LO PRECEDE

El brief de esta obra decía que el agente `title` de Ciencia «recibe las 25 tools del
stack (~14,5k tokens)» y corre con `max_tokens: 32000`. **Medido: recibe CERO tools.**
Sus seis cruces en una conversación de 3 turnos llevan `n_tools=0`. Podar tools no
ahorra nada ahí porque no hay tools que podar.

El desperdicio existe, pero es **OTRO**, y se ve con el hash del contenido — no con el
tamaño (`grabador_prompt` guarda un hash por mensaje justamente para esto):

    auxiliar #3  ts=…759,5  hash=fb44103853c56565   868 tok
    auxiliar #4  ts=…767,2  hash=fb44103853c56565   868 tok   ← MISMO hash, 7,7 s después
    auxiliar #5  ts=…834,7  hash=cb63c57faad3d662   868 tok
    auxiliar #6  ts=…841,3  hash=cb63c57faad3d662   868 tok   ← MISMO hash, 6,6 s después

**El mismo prompt, byte por byte, dos veces por turno.** Y no es un reintento de Aleph:
el tap que los grabó está en `router.workspace_brain_openai`, que corre **una vez por
pedido HTTP** — o sea que son dos pedidos distintos del stack. Aleph no puede impedir
que el stack pregunte dos veces; sí puede contestar sin quemar una llamada al modelo.

⚠️ **Y SON CONCURRENTES, no consecutivas.** Esto lo corrigió la medición, no el diseño:
la primera versión de esta pieza guardaba el resultado al TERMINAR y buscaba en esa
caché al empezar — y no acertó ni una vez en dos corridas enteras. El diagnóstico lo
mostró sin lugar a dudas, en el orden de las líneas:

    PIDE  clave=…d9378581   | en memoria: []
    GUARDA clave=…165fcaba                        ← termina OTRA, no ésta
    PIDE  clave=…d9378581   | en memoria: [165f…] ← la gemela llega con la primera EN VUELO

La segunda llega **mientras la primera todavía está esperando al modelo**. Una caché de
resultados terminados nunca puede acertarle a eso. Lo que hace falta es **single-flight**:
la segunda se cuelga de la primera y se lleva su respuesta cuando llega.

Costo medido de la repetición, por conversación de 3 turnos en Ciencia:
  · 1.736 tokens de prompt NUESTRO (2 × 868)
  · **más el preámbulo del CLI en cada una** — ~3,7k con Claude, ~11,8k con Codex —
    que es donde está el grueso: ~9,1k con Claude, ~25k con Codex
  · ~6 s de reloj de pared (2,7 s + 3,1 s medidos)

════════════════════════════════════════════════════════════════════════════════
LAS CUATRO REGLAS QUE LO VUELVEN SEGURO

1. **SÓLO llamadas SIN TOOLS.** Una llamada sin catálogo es una transformación de texto
   pura: no tiene efectos. Una llamada CON tools puede querer otra jugada, y ahí repetir
   no es desperdicio sino reintento. La regla es estrecha a propósito.

2. **UNA sola repetición por clave.** La segunda llamada idéntica se contesta del eco;
   una TERCERA vuelve al modelo. Si el stack estuviera re-muestreando a propósito, el
   eco no se lo impide para siempre — le cuesta una vuelta, no la capacidad.

3. **VENTANA CORTA** (`VENTANA_S`). El eco existe para el par que llega junto, no para
   ser una caché. Fuera de la ventana, al modelo.

4. **SE DICE SIEMPRE.** Un turno servido del eco **emite igual su `workspace_step`**, con
   `servido_del_eco: true`. Lo que NO emite es un cost-event: no hubo llamada al modelo,
   y un dict de ceros contaría como llamada medida y rompería el único contador de
   honestidad que hay (mismo criterio que `codemode_borde._respuesta_tool` y que el
   `usage` omitido de `router.py`). **Una optimización que hace que algo deje de decirse
   no es una optimización.**

LEY 0. Vive entera del lado de Aleph. El stack pregunta lo de siempre y recibe una
respuesta válida a lo que preguntó. Sin la perilla
(`ALEPH_ECO_AUXILIAR_WS=<ws>,<ws>`) esto no hace absolutamente nada.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Callable, Optional

#: Cuánto vive un eco. Medido: los pares llegan a 6,6 y 7,7 s. 120 s da margen de
#: sobra sin convertir esto en una caché de respuestas, que es otra cosa y no la quiero.
VENTANA_S = 120.0

#: Cuántas veces se contesta del eco por clave. UNA. La tercera llamada idéntica va al
#: modelo: si el stack re-muestrea a propósito, el eco le cuesta una vuelta, no la
#: capacidad de hacerlo.
MAX_ECOS = 1

#: Cuánto espera la gemela a la que ya está en vuelo. Generoso contra la latencia de un
#: turno (medido: 2,7-3,1 s para el auxiliar) y muy por debajo de cualquier deadline de
#: turno. Si se pasa, la gemela llama por su cuenta: el eco puede no ahorrar, nunca colgar.
ESPERA_S = 60.0

_LOCK = threading.Lock()
_ECOS: dict = {}


#: LOS STACKS CON EL ECO PRENDIDO DE FÁBRICA. Uno solo: **Ciencia**.
#:
#: SE ENVÍA PRENDIDO, y la decisión se ganó midiendo. Una perilla que hay que acordarse de
#: prender es una perilla que se olvida — y ésta ya se olvidó una vez: la obra la dejó
#: cableada con default vacío y el −4,1 % no se realizó en ninguna instalación.
#:
#: POR QUÉ ES SEGURO PRENDERLO SIN VIGILANCIA. La pregunta que había que contestar antes
#: era «¿puede colapsar dos pedidos que NO eran gemelos?». Medido en
#: `verify_eco_no_colapsa_ajenos.py`, con hilos de verdad y contando LLAMADAS AL MODELO:
#:   · un solo carácter distinto en el prompt ⇒ DOS llamadas
#:   · el mismo prompt con otro `max_tokens` ⇒ DOS llamadas
#:   · el mismo prompt en otro chat ⇒ DOS llamadas
#: La clave entra el workspace, el chat, los mensajes ENTEROS y los parámetros de
#: generación; para colapsar hay que ser idéntico en todo eso, sin tools, dentro de la
#: ventana, y una sola vez. Dos pedidos así SON el mismo pedido.
#:
#: ⚠️ Y NO SE EXTRAPOLA. Es de Ciencia y de nadie más: en Diseño el mismo síntoma tenía
#: otra causa —reintentos secuenciales del SDK por un 409 nuestro, ya arreglado— y en
#: Legal y Oficina no hay duplicación que colapsar. Agregar un stack acá es una decisión
#: con su medición, no una línea.
POR_DEFECTO = "ciencia"


def workspaces_encendidos() -> set:
    """Los stacks con el eco puesto. Ausente ⇒ el default; presente-y-vacío ⇒ APAGADO.

    Se usa `get(VAR, POR_DEFECTO)` y no `get(VAR) or POR_DEFECTO` a propósito: con `or`,
    poner `ALEPH_ECO_AUXILIAR_WS=""` para apagarlo volvería a caer en el default y la
    perilla no tendría forma de apagarse. Así, la cadena vacía explícita apaga.
    """
    crudo = (os.environ.get("ALEPH_ECO_AUXILIAR_WS", POR_DEFECTO)).strip()
    return {x.strip().lower() for x in crudo.split(",") if x.strip()}


def encendido_para(workspace: str) -> bool:
    return (workspace or "").strip().lower() in workspaces_encendidos()


def _texto(x) -> str:
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:                       # noqa: BLE001
        return str(x)


def clave_de(workspace: str, messages: list, max_tokens, temperature) -> str:
    """La huella del PEDIDO. Dos pedidos con esta huella igual son el mismo pedido.

    Entra todo lo que puede cambiar la respuesta: el workspace (para que un eco no
    cruce de stack), los mensajes enteros —rol y contenido— y los parámetros de
    generación. Lo que NO entra son las tools: esta pieza sólo se aplica cuando no hay.
    """
    h = hashlib.sha256()
    h.update(("ws=" + (workspace or "")).encode("utf-8", "replace"))
    for m in (messages or []):
        m = m if isinstance(m, dict) else {}
        h.update(("\x00" + str(m.get("role") or "") + "\x01").encode("utf-8", "replace"))
        h.update(_texto(m.get("content")).encode("utf-8", "replace"))
        if m.get("tool_calls"):
            h.update(_texto(m["tool_calls"]).encode("utf-8", "replace"))
    h.update(("\x02mt=%s\x03t=%s" % (max_tokens, temperature)).encode("utf-8"))
    return h.hexdigest()


def _barrer(ahora: float) -> None:
    for k in [k for k, v in _ECOS.items() if ahora - v["ts"] > VENTANA_S]:
        _ECOS.pop(k, None)


def paso(*, clave: str, workspace: str, messages: list, tools: list,
         max_tokens=None, temperature=None,
         llamar_modelo: Callable[[], dict],
         on_event: Optional[Callable] = None) -> Optional[dict]:
    """La llamada, con eco. `None` = no aplica, seguí por el camino de siempre.

    SINGLE-FLIGHT. La entrada se reserva ANTES de llamar al modelo, con un `Event` sin
    disparar. La gemela que llega mientras tanto encuentra la reserva y **espera** en vez
    de largar una segunda llamada. Cuando la primera vuelve, dispara el `Event` y las dos
    salen con la misma respuesta. Si la primera se cae o tarda más que `ESPERA_S`, la que
    esperaba **hace su propia llamada** — el eco puede no ahorrar, pero nunca puede
    colgar un turno ni tragarse un error.
    """
    _diag = bool(os.environ.get("ALEPH_ECO_DIAG"))
    if not encendido_para(workspace):
        return None
    if tools:
        return None                     # regla 1: sólo llamadas SIN tools
    k = clave + "::" + clave_de(workspace, messages, max_tokens, temperature)

    esperar = None
    with _LOCK:
        _barrer(time.time())
        eco = _ECOS.get(k)
        if eco is None:
            # Somos la primera: RESERVAMOS antes de llamar, que es justamente lo que la
            # versión anterior no hacía y por eso no acertaba nunca.
            _ECOS[k] = {"out": None, "listo": threading.Event(), "ts": time.time(),
                        "usos": 0}
            mia = True
        elif eco["usos"] < MAX_ECOS:
            eco["usos"] += 1
            esperar = eco
            mia = False
        else:
            mia = None                  # ya se sirvió su repetición: al modelo, sin eco

    if mia is None:
        return llamar_modelo()

    if not mia:
        n = esperar["usos"]
        if esperar["out"] is None:
            if _diag:
                print("[eco·diag] ESPERA a la gemela en vuelo", flush=True)
            esperar["listo"].wait(ESPERA_S)
        guardado = esperar["out"]
        if guardado is None:
            # La primera no llegó a tiempo o se cayó. No se inventa nada: se llama.
            if _diag:
                print("[eco·diag] la gemela no trajo nada; llamo yo", flush=True)
            return llamar_modelo()
        if on_event:
            # SE DICE. El paso existió y el ledger tiene que verlo; lo que no existió es
            # la llamada al modelo, y por eso no va cost-event.
            try:
                on_event({"type": "workspace_step", "kind": "workspace",
                          "workspace": workspace, "servido_del_eco": True, "eco_uso": n,
                          "detalle": "pedido IDÉNTICO a otro del mismo instante; se "
                                     "contestó con su respuesta, sin llamar al modelo",
                          "tools_declared": 0, "tool_calls_requested": []})
            except Exception:           # noqa: BLE001 — avisar no puede tumbar el turno
                pass
        salida = dict(guardado)
        # El `usage` del original NO se repite: contarlo dos veces sería inventar una
        # medición. `None` se declara, jamás se rellena con ceros.
        salida["usage"] = None
        salida["cost_events"] = []
        salida["aleph_eco"] = {"servido": True, "uso": n}
        return salida

    # Somos la primera: llamamos, y pase lo que pase liberamos a quien esté esperando.
    out = None
    try:
        out = llamar_modelo()
    finally:
        with _LOCK:
            entrada = _ECOS.get(k)
            if entrada is not None:
                # Una jugada de tool no se comparte: no es una transformación de texto,
                # y repetirla sería repetir un efecto. Se deja la entrada en `None` para
                # que la gemela llame por su cuenta.
                if out is not None and not (out.get("tool_calls") or []):
                    entrada["out"] = out
                    entrada["ts"] = time.time()
                else:
                    _ECOS.pop(k, None)
                entrada["listo"].set()
    if _diag:
        print("[eco·diag] PRIMERA terminó, gemela liberada", flush=True)
    return out
