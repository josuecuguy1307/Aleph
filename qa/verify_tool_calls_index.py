#!/usr/bin/env python3
"""verify_tool_calls_index — cada `tool_call` del stream lleva su `index`.

POR QUÉ EXISTE. Sin `index` el turno MUERE, y el usuario ve el JSON del error en la
pantalla. Capturado del chat del dueño:

    AI_TypeValidationError: Type validation failed:
    {"model":"claude-opus-5","choices":[{"delta":{"tool_calls":
    [{"id":"call_257d…","type":"function","function":{"name":"write",…}}]}}]}

El esquema con el que el stack valida CADA chunk (`@ai-sdk/openai-compatible@1.0.30`) es:

    tool_calls: z.array(z.object({
      index: z.number(),            ← REQUERIDO (los otros tres son .nullish())
      id: z.string().nullish(),
      function: z.object({ name: …, arguments: … })
    })).nullish()

`index` es el único obligatorio de los cuatro. Esta vara reproduce esa regla sobre los
chunks que emite el borde: si falta uno, cae — que es lo que el stack hace, pero acá con
un mensaje que dice qué falta en vez de un volcado de JSON.

⚠️ ESTA VARA ES EN VIVO: PEGA CONTRA EL BORDE QUE ESTÉ CORRIENDO, NO CONTRA EL ÁRBOL.
Su rojo dice «el borde que me contestó no manda `index`», y eso puede significar dos cosas
opuestas: que el arreglo no está en el código, o que el arreglo SÍ está en el código pero la
`.app` instalada todavía es la vieja. Pasó el 2026-08-29: otra sesión la corrió contra la
instalada sin el fix, le dio rojo, y el rojo era CORRECTO — describía exactamente lo que el
dueño veía en pantalla. Antes de leer un rojo como «el arreglo no sirve», mirá contra QUÉ
binario corriste: `--puerto` sin argumento apunta a la instalada; con `--puerto 8331` (u
otro) apunta al backend de árbol que hayas levantado vos.

Es la misma familia de «¿de qué es cierto lo que medí?»: el veredicto es del borde que
contestó, no del código que tenés abierto.

Uso:
    python3 qa/verify_tool_calls_index.py                  # contra la .app instalada
    python3 qa/verify_tool_calls_index.py --puerto 8331    # contra un backend de árbol
    python3 qa/verify_tool_calls_index.py --ws legal
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from verify_primer_texto import LECTORES                      # noqa: E402

#: Obliga a usar una tool de escritura: es el caso exacto que reventó.
PROMPT = ("Escribí un archivo llamado nota-vara.md en el proyecto con tres líneas sobre "
          "qué es un qubit. Usá la herramienta de escritura de archivos.")


def valida_chunk(d: dict) -> list[str]:
    """Las mismas reglas del esquema del stack. Devuelve los incumplimientos."""
    fallas = []
    for ch in (d.get("choices") or []):
        for tc in ((ch.get("delta") or {}).get("tool_calls") or []):
            if not isinstance(tc.get("index"), int):
                fallas.append("tool_call sin `index` entero: %s"
                              % json.dumps(tc, ensure_ascii=False)[:160])
            fn = tc.get("function")
            if fn is not None and not isinstance(fn, dict):
                fallas.append("`function` no es objeto: %r" % (fn,))
    return fallas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", default="ciencia")
    ap.add_argument("--puerto", default="")
    args = ap.parse_args()

    base, key, cab, modelo = LECTORES[args.ws]()
    cab.setdefault("X-Aleph-Space", "space-ws-%s-varatoolidx" % args.ws)
    cab.setdefault("X-Aleph-Chat", "vara-tool-index-%s" % args.ws)
    if args.puerto:
        base = re.sub(r"//127\.0\.0\.1:\d+", "//127.0.0.1:" + args.puerto, base)

    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", method="POST",
        data=json.dumps({"model": modelo, "stream": True,
                         "messages": [{"role": "user", "content": PROMPT}],
                         # EL DISPARADOR NO SE DEJA AL AZAR. Sin esto el modelo puede
                         # contestar en texto y la vara sale [no medible] — le pasó en la
                         # primera corrida contra el binario. El borde honra `tool_choice`
                         # desde B0-2, así que pedirlo es la forma barata de garantizar que
                         # haya un `tool_call` que mirar.
                         "tool_choice": "required",
                         "tools": [{"type": "function", "function": {
                             "name": "write",
                             "description": "Escribe un archivo",
                             "parameters": {"type": "object", "properties": {
                                 "filePath": {"type": "string"},
                                 "content": {"type": "string"}},
                                 "required": ["filePath", "content"]}}}]}).encode(),
        headers={**cab, "Authorization": "Bearer " + key,
                 "Content-Type": "application/json", "Accept": "text/event-stream"})

    n_tc, fallas = 0, []
    with urllib.request.urlopen(req, timeout=300) as r:
        for cruda in r:
            linea = cruda.decode("utf8", "replace").strip()
            if not linea.startswith("data:"):
                continue
            p = linea[5:].strip()
            if p == "[DONE]":
                break
            try:
                d = json.loads(p)
            except Exception:                                  # noqa: BLE001
                continue
            for ch in (d.get("choices") or []):
                n_tc += len((ch.get("delta") or {}).get("tool_calls") or [])
            fallas += valida_chunk(d)

    print("tool_calls vistos: %d" % n_tc)
    if not n_tc:
        print("⚪ [no medible] el turno no usó ninguna tool — el disparador no estuvo")
        return 0
    if fallas:
        print("❌ %d incumplimiento(s) del esquema del stack:" % len(fallas))
        for f in fallas[:5]:
            print("   ·", f)
        return 1
    print("✅ los %d tool_calls llevan `index` — el esquema del stack los acepta" % n_tc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
