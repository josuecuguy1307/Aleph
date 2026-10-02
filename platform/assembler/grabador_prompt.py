#!/usr/bin/env python3
"""grabador_prompt.py — QUÉ PESA CADA PARTE DEL PROMPT, cruce por cruce.

El hermano de `grabador_tools`. Aquél contesta *cuántas veces cruza el catálogo*;
éste contesta **de qué está hecho lo que cruza** — y sobre todo cuánto de eso son
**salidas de tools** que ya se leyeron antes y se vuelven a mandar.

POR QUÉ HACE FALTA. Code execution se llevó los resultados INTERMEDIOS: se quedan
adentro del sandbox. Pero el resultado FINAL vuelve al contexto, y **los seis
workspaces cruzan con `sesion=None`** (`workspace_brain.py` no menciona la palabra
`sesion` ni una vez), así que `server._armar_prompt` cae siempre en
`render_prompt(mensajes, …)` — el render COMPLETO. Es decir: cada salida de tool que
ya está en el historial **se re-manda entera en cada paso posterior y en cada turno
posterior de la misma conversación**. Eso es lo que nadie midió.

CÓMO MIDE, y por qué así:

  · **Graba crudo y tokeniza DESPUÉS.** Tokenizar en el camino del turno es un
    efecto observador: mete latencia en lo que se está midiendo. Acá el camino
    caliente sólo serializa y escribe; las cuentas las hace `analizar_prompt.py`
    sobre el JSONL, fuera del turno.
  · **Guarda el contenido ENTERO de cada mensaje**, no su largo. Sin el contenido no
    se puede contar cuántas veces se RE-LEE una salida: la identidad de una salida es
    su contenido, y hace falta poder compararla entre cruces.
  · **Nunca levanta.** Un grabador que rompe el turno no mide nada, mide otra cosa.
  · **Apagado sin `ALEPH_GRABAR_PROMPT=<ruta.jsonl>`.** Sin la variable no toca disco.

DOS TOMAS, a propósito, y NO son redundantes:

  `borde`  — en `router.workspace_brain_openai`: acá se sabe **QUÉ WORKSPACE** pide
             (`X-Aleph-Workspace`) y se ven los `messages` **tal como los manda el
             stack**. Es la toma con identidad.
  `render` — en `server._armar_prompt`: acá se ve **el prompt FINAL**, ya con lo que
             Aleph le agregue, y si salió completo o incremental. Es la toma con la
             verdad de lo que cruza.

  Correlacionarlas por tiempo da las dos mitades. Cada una sola miente por un lado
  distinto: el borde no sabe qué le agregó Aleph, y el render no sabe quién pidió.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time

_LOCK = threading.Lock()


def encendido() -> str:
    return (os.environ.get("ALEPH_GRABAR_PROMPT") or "").strip()


def _h(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8", "replace")).hexdigest()[:16]


def _texto(x) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, ensure_ascii=False, default=str)
    except Exception:
        return str(x)


def _mensaje(m: dict, i: int) -> dict:
    """Un mensaje, reducido a lo que la cuenta necesita — SIN perder el contenido.

    El `hash` es la identidad de la salida entre cruces: dos cruces que traen la misma
    salida traen el mismo hash, y de ahí sale «cuántas veces se re-lee» sin inferir nada.
    """
    m = m if isinstance(m, dict) else {}
    rol = m.get("role") or "?"
    cont = _texto(m.get("content"))
    tcs = m.get("tool_calls") or []
    fila = {
        "i": i,
        "rol": rol,
        "chars": len(cont),
        "hash": _h(cont) if cont else "",
        "content": cont,
        # ⚠️ EL TIPO CRUDO, porque `_texto` YA APLANÓ y sin esto el tap no puede decir si
        # `content` venía como lista de bloques o como cadena. Costó una hipótesis
        # equivocada: los dos casos se graban idénticos y parecen el mismo dato.
        "content_tipo": type(m.get("content")).__name__,
        "content_n": (len(m["content"]) if isinstance(m.get("content"), list) else None),
    }
    if rol == "tool":
        fila["name"] = m.get("name") or ""
        fila["tool_call_id"] = m.get("tool_call_id") or ""
    if tcs:
        fila["tool_calls"] = [{
            "id": tc.get("id") or "",
            "name": (tc.get("function") or {}).get("name", ""),
            "arguments": _texto((tc.get("function") or {}).get("arguments")),
        } for tc in tcs if isinstance(tc, dict)]
    return fila


def grabar_cruce(toma: str, superficie: str, messages, tools,
                 tool_choice=None, *, paso: str = "",
                 prompt: str | None = None, incremental=None,
                 extra: dict | None = None) -> None:
    """Anota UN cruce. `toma` es `borde` o `render` (ver el docstring del módulo)."""
    ruta = encendido()
    if not ruta:
        return
    try:
        msgs = list(messages or [])
        tools = list(tools or [])
        fila = {
            "ts": time.time(),
            "toma": toma,
            "superficie": superficie or "?",
            "paso": paso,
            "pid": os.getpid(),
            "n_tools": len(tools),
            "n_messages": len(msgs),
            "tools_nombres": [(t.get("function", t) or {}).get("name")
                              for t in tools if isinstance(t, dict)],
            "tools": tools,
            "tool_choice": tool_choice,
            "mensajes": [_mensaje(m, i) for i, m in enumerate(msgs)],
        }
        if prompt is not None:
            fila["prompt"] = prompt
            fila["prompt_chars"] = len(prompt)
        if incremental is not None:
            fila["incremental"] = bool(incremental)
        if extra:
            fila.update(extra)
        linea = json.dumps(fila, ensure_ascii=False, default=str)
        with _LOCK, open(ruta, "a", encoding="utf-8") as fh:
            fh.write(linea + "\n")
    except Exception:
        pass


def grabar_usage(proveedor: str, usage, medidos) -> None:
    """El `usage` del CLI, en la misma cinta que los cruces.

    Va como una fila `toma="usage"` para que quede intercalada en el tiempo con el
    cruce que la produjo: el par (cruce, usage) es lo que permite decir «este prompt
    de N tokens se facturó así». Nunca levanta y no hace nada sin la variable.
    """
    ruta = encendido()
    if not ruta:
        return
    try:
        u = dict(usage or {})
        fila = {"ts": time.time(), "toma": "usage", "superficie": "_cli_brain",
                "proveedor": proveedor, "medidos": bool(medidos), "usage": u,
                "pid": os.getpid()}
        with _LOCK, open(ruta, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
