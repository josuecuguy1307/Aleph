#!/usr/bin/env python3
"""codemode_borde.py — code execution EN EL BORDE de un workspace heredado.

════════════════════════════════════════════════════════════════════════════════
EL PROBLEMA QUE ESTA PIEZA RESUELVE

En el borde, **Aleph no ejecuta las tools del stack — las corre el stack**
(`router.py:4746`). Así que la receta de la Sala no sirve acá: no hay `registry.call`
al que colgar las funciones del script.

Y sin embargo el ahorro es real, porque lo que cuesta no son las tools: son **las
CRUCES** —cada vez que el catálogo entero viaja al modelo—. Medido: Ciencia cruza 5
veces por turno con 25 tools; Finanzas 8 con 94.

════════════════════════════════════════════════════════════════════════════════
CÓMO SE RESUELVE · EL SCRIPT SE SUSPENDE

El script corre en Aleph, pero cuando llama a una tool del stack **se queda
bloqueado** y Aleph le devuelve al stack esa llamada en su formato de siempre. El
stack la ejecuta —como siempre—, vuelve con el resultado, y Aleph se lo entrega al
script, que sigue donde estaba.

    stack → Aleph : messages + 25 tools
    Aleph → MODELO: 1 tool (`aleph_run_code`) + la superficie        ← CRUZA
    MODELO → Aleph: run_code(script)
    Aleph corre el script … el script llama `arxiv_search(...)`
    Aleph → stack : tool_calls:[arxiv_search]   **SIN LLAMAR AL MODELO**  ← NO cruza
    stack → Aleph : {role:"tool", content:…}
    Aleph despierta el script … el script llama otra … y otra …          ← NO cruzan
    el script termina
    Aleph → MODELO: el stdout del script                              ← CRUZA
    Aleph → stack : el texto final

**EL STACK NO SE ENTERA DE NADA.** Recibe exactamente lo que recibía: una llamada a
una tool suya, con su id, y devuelve su resultado. Ni una línea suya se toca.

LO QUE COLAPSA son las CRUCES DEL MODELO (5 → 2 en Ciencia). Las vueltas del stack
siguen siendo las mismas, y no cuestan tokens: son HTTP local.

════════════════════════════════════════════════════════════════════════════════
LEY 0. El stack suelto, fuera de Aleph, no cambia: esta pieza vive entera del lado
de Aleph y sólo se enciende para los workspaces que la perilla nombre
(`ALEPH_CODE_EXECUTION_WS=ciencia,finanzas`). Sin la perilla devuelve `None` y el
borde hace lo de siempre, byte por byte.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
import uuid
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

for _p in ("platform/assembler", "platform"):
    _abs = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))), _p)
    if os.path.isdir(_abs) and _abs not in sys.path:
        sys.path.insert(0, _abs)

import code_execution as CE                                          # noqa: E402

#: Cuánto espera el script a que el stack ejecute UNA tool suya. Generoso a propósito:
#: del otro lado hay un proveedor real, no un stub.
ESPERA_TOOL_S = 300

#: Cuánto vive un script suspendido sin que nadie lo despierte, antes de barrerse.
#: Un turno abandonado no puede dejar un subproceso colgado para siempre.
VIDA_SESION_S = 900


def workspaces_encendidos() -> set:
    """Los workspaces con la perilla puesta. **Por stack, jamás global.**"""
    crudo = (os.environ.get("ALEPH_CODE_EXECUTION_WS") or "").strip()
    return {x.strip().lower() for x in crudo.split(",") if x.strip()}


def encendido_para(workspace: str) -> bool:
    return (workspace or "").strip().lower() in workspaces_encendidos()


class _Suspendido:
    """Un script corriendo, bloqueado esperando que el stack ejecute una tool suya."""

    def __init__(self, clave: str):
        self.clave = clave
        self.pide: queue.Queue = queue.Queue()      # script → borde: (id, nombre, args)
        self.trae: queue.Queue = queue.Queue()      # borde → script: el resultado
        self.terminado = threading.Event()
        self.salida: Optional[dict] = None          # lo que devolvió `CE.ejecutar`
        self.pendiente: Optional[dict] = None       # la llamada que el stack está corriendo
        self.tocado = time.time()
        self.hilo: Optional[threading.Thread] = None
        self.tools_pedidas: list = []               # el CONJUNTO, para la vara 1

    def despachar(self, nombre: str, args: dict) -> str:
        """Corre en el hilo del script. Publica la llamada y SE BLOQUEA."""
        cid = "codemode-" + uuid.uuid4().hex[:16]
        self.tools_pedidas.append(nombre)
        self.pide.put({"id": cid, "name": nombre, "arguments": json.dumps(args, ensure_ascii=False)})
        try:
            res = self.trae.get(timeout=ESPERA_TOOL_S)
        except queue.Empty:
            raise TimeoutError(
                f"el stack no devolvió el resultado de `{nombre}` en {ESPERA_TOOL_S}s")
        if res.get("__cancelado__"):
            raise RuntimeError("el turno se canceló mientras el script esperaba")
        return res.get("contenido") or ""


_SESIONES: dict = {}
_LOCK = threading.Lock()


def _barrer():
    ahora = time.time()
    for k, s in list(_SESIONES.items()):
        if ahora - s.tocado > VIDA_SESION_S:
            try:
                s.trae.put({"__cancelado__": True})
            except Exception:
                pass
            _SESIONES.pop(k, None)
            log.warning("codemode_borde: barrida la sesión abandonada %s", k)


def _ultimo_resultado(messages: list) -> Optional[dict]:
    """El último mensaje `tool` de la conversación — el resultado que trae el stack."""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "tool":
            return m
    return None


def _respuesta_tool(call: dict, modelo: str) -> dict:
    """La forma EXACTA que `complete()` devuelve, para que el borde no note diferencia.

    `usage` va en None —no en ceros— porque en este paso NO se llamó al modelo: poner
    un dict de ceros lo contaría como llamada medida y rompería el único contador de
    honestidad que hay. Ver el mismo criterio en `router.py`.
    """
    return {
        "content": None,
        "tool_calls": [call],
        "model": modelo,
        "usage": None,
        "route": None,
        "degraded": None,
        "cost_events": [],
        "finish_reason": "tool_calls",
        "repliegue": None,
        # marca para la vara y para el ledger: este paso NO cruzó el catálogo
        "aleph_codemode": {"paso": "sin_cruce", "tool": call.get("name")},
    }


def paso(*, clave: str, workspace: str, messages: list, tools: list,
         llamar_modelo: Callable[[list, list], dict],
         on_event: Optional[Callable] = None) -> Optional[dict]:
    """UN paso del borde con code execution. `None` = no aplica, seguí como siempre.

    `llamar_modelo(messages, tools)` es el `complete()` de siempre: acá se lo llama
    **como mucho dos veces por turno** en vez de una por tool.
    """
    if not encendido_para(workspace):
        return None
    with _LOCK:
        _barrer()
        s = _SESIONES.get(clave)

    # ── (1) HAY UN SCRIPT ESPERANDO: el stack trae el resultado de su tool ──────────
    if s is not None and s.pendiente is not None:
        res = _ultimo_resultado(messages)
        if res is None:
            # El stack volvió sin resultado para la tool que le pedimos. No se inventa
            # nada: se cancela el script y se cae al camino normal, que sabe qué hacer.
            _cancelar(clave)
            return None
        s.tocado = time.time()
        s.pendiente = None
        s.trae.put({"contenido": res.get("content") if isinstance(res.get("content"), str)
                    else json.dumps(res.get("content"), ensure_ascii=False, default=str)})
        return _seguir(s, clave, workspace, messages, llamar_modelo, on_event)

    # ── (2) TURNO NUEVO: se le pide al modelo UN SCRIPT ─────────────────────────────
    utiles = CE.funciones_validas(tools)
    if len(utiles) < CE.MINIMO_TOOLS:
        return None
    msgs = _con_superficie(messages, utiles)
    out = llamar_modelo(msgs, [CE.tool_unica(len(utiles))])
    llamadas = out.get("tool_calls") or []
    codigo, pidio_script, crudo = None, False, ""
    for c in llamadas:
        if c.get("name") == CE.NOMBRE_TOOL:
            pidio_script = True
            crudo = c.get("arguments") or ""
            codigo = _sacar_codigo(crudo)
            break
    if pidio_script and not codigo:
        # ⚠️ EL VERDE MUDO QUE ESTE BLOQUE EXISTE PARA IMPEDIR.
        # El modelo pidió el script pero su `arguments` no trae un `code` usable (pasa en
        # el camino CLI: el script viaja como JSON entre marcadores `<function=…>` y un
        # programa con comillas y saltos no siempre sobrevive el viaje).
        #
        # Devolver `out` acá —que es lo que esta pieza hacía— le entrega al STACK una
        # llamada a `aleph_run_code`, **una tool que el stack no tiene**. El stack no
        # explota: contesta un error de tool, el modelo se recompone y el turno termina
        # dando la respuesta correcta. Se ve perfecto y el mecanismo NUNCA CORRIÓ.
        # Medido así el 2026-08-22 en Ciencia: dos `aleph_run_code` filtrados al stack,
        # cero llamadas por el puente, y una respuesta impecable.
        #
        # Así que no se reenvía: se cae al camino de siempre —que sabe hacer el turno— y
        # se DICE, con el crudo adjunto para poder arreglarlo.
        log.warning("codemode_borde: el modelo pidió el script y no se pudo leer su "
                    "`code` (%d bytes de arguments); se cae al camino normal", len(crudo))
        _avisar(on_event, {"type": "codemode_script_ilegible", "kind": "workspace",
                           "workspace": workspace, "bytes_arguments": len(crudo),
                           "muestra": crudo[:300]})
        return None
    if not codigo:
        # El modelo contestó texto, o pidió otra cosa. Se devuelve tal cual.
        return out

    _diag = (os.environ.get("ALEPH_CODEMODE_DIAG") or "").strip()
    if _diag:
        try:
            with open(_diag, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ws": workspace, "clave": clave,
                                     "arguments_bytes": len(crudo),
                                     "codigo": codigo}, ensure_ascii=False) + "\n")
        except Exception:                            # noqa: BLE001
            pass

    s = _Suspendido(clave)
    with _LOCK:
        _SESIONES[clave] = s
    _arrancar(s, codigo, utiles, on_event, workspace)
    if on_event:
        _avisar(on_event, {"type": "codemode_script_inicio", "kind": "workspace",
                           "workspace": workspace, "tools": len(utiles)})
    return _seguir(s, clave, workspace, messages, llamar_modelo, on_event,
                   modelo=out.get("model"))


def _sacar_codigo(crudo: str) -> Optional[str]:
    """El script que el modelo mandó, tolerando que el JSON no haya sobrevivido el viaje.

    Tres intentos, del más limpio al más terco:
      1. JSON bien formado con `code`.
      2. JSON con el `code` cortado a mitad (el caso del CLI): se rescata el string.
      3. `arguments` que ES el script, sin envoltorio.
    Devuelve `None` sólo si no hay nada que ejecutar — y entonces el llamante lo DICE.
    """
    crudo = (crudo or "").strip()
    if not crudo:
        return None
    try:
        v = json.loads(crudo)
        if isinstance(v, dict) and isinstance(v.get("code"), str) and v["code"].strip():
            return v["code"]
    except Exception:                                # noqa: BLE001
        pass
    # 2 · el `code` quedó abierto: se toma desde la comilla y se des-escapa a mano.
    marca = '"code"'
    i = crudo.find(marca)
    if i >= 0:
        j = crudo.find('"', i + len(marca) + 1)
        if j >= 0:
            cuerpo = crudo[j + 1:]
            if cuerpo.rstrip().endswith("}"):
                cuerpo = cuerpo.rstrip()[:-1].rstrip().rstrip('"')
            cuerpo = (cuerpo.replace('\\n', '\n').replace('\\t', '\t')
                            .replace('\\"', '"').replace('\\\\', '\\'))
            if cuerpo.strip():
                return cuerpo
    # 3 · sin envoltorio: si parece Python, es Python.
    if any(t in crudo for t in ("print(", "import ", "=", "for ", "def ")):
        return crudo
    return None


#: ⚠️ LA REGLA QUE FALTABA, Y ERA LA CAUSA DE QUE NO ENTREGARA.
#:
#: DIAGNOSTICADO CAPTURANDO EL SCRIPT (2026-08-23, `ALEPH_CODEMODE_DIAG`), en vez de
#: deducirlo por los efectos. El script de Ciencia fue, ENTERO:
#:
#:     dbs = science_list_dbs()
#:     print(json.dumps(items)[:3000])
#:
#: `ok=True`, una tool, sin `stderr`. **El script no se rompe: hace UN paso de
#: reconocimiento y para.** Y no es tontera del modelo: en un loop de tools eso es
#: exactamente lo correcto —mirás qué bases hay, y en la vuelta siguiente buscás—. La
#: superficie le decía cómo llamar a las funciones pero NUNCA le dijo que **no hay
#: vuelta siguiente**. Después `_cerrar` le avisa «ya NO tenés herramientas», y ahí ya
#: es tarde: el turno se cierra con media tarea hecha.
#:
#: Mismo modo de fallo en los tres (legal «all I have is the file's location», ciencia
#: «the actual query never executed», oficina «mi script imprimió el archivo crudo en
#: lugar de sumar»): los tres son un primer paso exploratorio, no un error.
_UN_SOLO_TIRO = (
    "TIENES UN SOLO TIRO. No hay una vuelta siguiente: este script es la ÚNICA vez que "
    "vas a poder llamar a esas funciones, y NO vas a ver su salida antes de responder — "
    "lo que sigue es tu respuesta final. Así que no escribas un script que sólo mira "
    "(listar, describir, localizar) para decidir después: no vas a poder decidir después. "
    "Escribe el trabajo COMPLETO de una: si necesitas el resultado de una función para "
    "elegir la próxima, encadenalas ADENTRO del script con Python normal (`if`, `for`, "
    "indexar el dict). Si no estás seguro de la forma de lo que devuelve una función, "
    "programa las dos ramas en vez de frenar a mirar."
)


def _con_superficie(messages: list, utiles: list) -> list:
    """La superficie va al final del `system`, sin tocar el resto de la conversación."""
    msgs = [dict(m) if isinstance(m, dict) else m for m in (messages or [])]
    txt = CE.superficie(utiles) + "\n" + _UN_SOLO_TIRO
    for i, m in enumerate(msgs):
        if isinstance(m, dict) and m.get("role") == "system":
            msgs[i] = {**m, "content": (m.get("content") or "") + "\n" + txt}
            return msgs
    return [{"role": "system", "content": txt}] + msgs


def _arrancar(s: _Suspendido, codigo: str, utiles: list, on_event, workspace: str):
    def _correr():
        try:
            s.salida = CE.ejecutar(codigo, utiles, s.despachar,
                                   on_event=(lambda ev, d: _avisar(
                                       on_event, {"type": ev, "kind": "workspace",
                                                  "workspace": workspace, **d}))
                                   if on_event else None)
        except Exception as exc:                      # noqa: BLE001
            s.salida = {"ok": False, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}",
                        "timed_out": False, "recortada": False, "total_impreso": None,
                        "tools_corridas": [], "n_tools_corridas": 0}
        finally:
            s.terminado.set()
    s.hilo = threading.Thread(target=_correr, name=f"codemode-{s.clave}", daemon=True)
    s.hilo.start()


def _seguir(s: _Suspendido, clave: str, workspace: str, messages: list,
            llamar_modelo, on_event, modelo: Optional[str] = None) -> dict:
    """Espera al script: o pide otra tool, o terminó."""
    while True:
        try:
            call = s.pide.get(timeout=1.0)
        except queue.Empty:
            if s.terminado.is_set():
                return _cerrar(s, clave, workspace, messages, llamar_modelo, on_event)
            continue
        s.pendiente = call
        s.tocado = time.time()
        return _respuesta_tool(call, modelo or "codemode")


def _cerrar(s: _Suspendido, clave: str, workspace: str, messages: list,
            llamar_modelo, on_event) -> dict:
    """El script terminó: se le pide al modelo la respuesta final CON su salida."""
    with _LOCK:
        _SESIONES.pop(clave, None)
    r = s.salida or {}
    cuerpo = r.get("stdout") or ""
    if not r.get("ok"):
        # Un script que se rompió NO se disfraza de respuesta: el motivo viaja al modelo
        # para que lo diga, y el stderr va entero (recortado por `code_execution`).
        cuerpo = (cuerpo + "\n[el script falló]\n" + (r.get("stderr") or "")).strip()
    _diag = (os.environ.get("ALEPH_CODEMODE_DIAG") or "").strip()
    if _diag:
        try:
            with open(_diag, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"fin": True, "ok": bool(r.get("ok")),
                                     "stdout": (r.get("stdout") or "")[:1500],
                                     "stderr": (r.get("stderr") or "")[:600],
                                     "tools": list(s.tools_pedidas)}, ensure_ascii=False) + "\n")
        except Exception:                            # noqa: BLE001
            pass
    if on_event:
        _avisar(on_event, {"type": "codemode_script_fin", "kind": "workspace",
                           "workspace": workspace, "ok": bool(r.get("ok")),
                           "tools_corridas": [c["tool"] for c in (r.get("tools_corridas") or [])],
                           "recortada": bool(r.get("recortada")),
                           "total_impreso": r.get("total_impreso")})
    msgs = list(messages or []) + [{
        "role": "user",
        # ⚠️ LA INSTRUCCIÓN TIENE QUE SER TERMINANTE, Y SE GANÓ MIDIENDO.
        # Con un simple «respondé con esto» el modelo seguía escribiendo un marcador
        # `<function=bash>…`: el paso va sin catálogo, así que nadie lo parsea como
        # tool_call y **se filtra como TEXTO a la cara del usuario**. Medido en Ciencia
        # el 2026-08-22: la respuesta final fue `<function=bash> python3 -c "print(2**37)"`,
        # sin el canario y sin el número. El turno «anduvo» y no dijo nada.
        "content": ("Este es el resultado REAL de ejecutar tu script:\n\n"
                    + (cuerpo or "(el script no imprimió nada)")
                    + "\n\nAhora RESPONDE EN PROSA, en el idioma del usuario, usando SÓLO "
                      "estos datos. Ya NO tienes herramientas: este es el último paso. NO "
                      "escribas `<function=...>` ni ningún marcador de llamada — si lo "
                      "haces, el usuario lo va a leer literal. Si el resultado no alcanza "
                      "para contestar, dilo con todas las letras."),
    }]
    out = llamar_modelo(msgs, [])          # sin catálogo: no hace falta, ya no llama nada

    # LA GUARDA, porque una instrucción no es una garantía. Si aun así vino un marcador,
    # NO se le entrega al usuario: se recorta y **se declara** — un texto mutilado que se
    # lee como respuesta completa es exactamente el modo de fallo que esta obra persigue.
    txt = out.get("content")
    if isinstance(txt, str) and "<function=" in txt:
        limpio = txt[:txt.index("<function=")].strip()
        out["content"] = limpio or (
            "No pude cerrar la respuesta: el modelo intentó llamar otra herramienta en el "
            "paso final, donde ya no hay ninguna. Esto es lo que dio el cálculo:\n\n"
            + (cuerpo or "(vacío)"))
        _avisar(on_event, {"type": "codemode_marcador_filtrado", "kind": "workspace",
                           "workspace": workspace, "recortado": len(txt) - len(limpio)})
        log.warning("codemode_borde: el paso de cierre emitió un marcador de tool; "
                    "se recortó y se declaró")

    if not (out.get("content") or "").strip():
        # Un cierre vacío tampoco pasa: vuelve la salida del script, que es un hecho.
        out["content"] = ("El script corrió y esto es lo que dio:\n\n" + (cuerpo or "(vacío)"))
    out["aleph_codemode"] = {"paso": "cierre", "ok": bool(r.get("ok")),
                             "tools_corridas": list(s.tools_pedidas)}
    return out


def _cancelar(clave: str):
    with _LOCK:
        s = _SESIONES.pop(clave, None)
    if s is not None:
        try:
            s.trae.put({"__cancelado__": True})
        except Exception:                             # noqa: BLE001
            pass


def _avisar(on_event, datos: dict):
    if on_event is None:
        return
    try:
        on_event(datos)
    except Exception:                                 # noqa: BLE001
        pass


def hay_sesion(clave: str) -> bool:
    with _LOCK:
        return clave in _SESIONES
