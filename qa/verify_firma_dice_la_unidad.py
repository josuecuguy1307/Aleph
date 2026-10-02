#!/usr/bin/env python3
"""verify_firma_dice_la_unidad.py — un número sin unidad es una trampa.

EL DEFECTO, medido el 2026-08-29 en un turno real de Ciencia que se caía a la mitad.

El `notebook` del stack declara su `timeout` en MILISEGUNDOS y lo dice en la descripción
del parámetro. La firma que Aleph le rinde al cerebro CLI tiraba esa descripción, así que
el modelo veía `timeout: number`, mandó `600` pensando en segundos, y el kernel lo subió a
su piso de 5.000 ms. En el transcript quedaron cinco respuestas seguidas peleando contra
eso: «the kernel enforces a hard 5 s per-cell cap», «matplotlib's import consistently
exceeds the kernel's hard cap». El tope lo habíamos fabricado nosotros, escondiéndole una
palabra.

QUÉ CUIDA ESTA VARA. Que la unidad viaje —y que siga costando poco: sólo los numéricos,
porque volcar el schema entero son +4.000 tokens por turno en Finanzas (medido en el
docstring de `_firma_params`) y los numéricos son el 6,1 % de los parámetros.

Correr:  python3 qa/verify_firma_dice_la_unidad.py
"""
from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "platform/assembler"))

from cli_brain.prompt_bridge import _firma_params  # noqa: E402

fallos: list[str] = []


def ok(cond, que):
    print(("  ✓ " if cond else "  ✗ ") + que)
    if not cond:
        fallos.append(que)


def firma(props, requeridos=()):
    return _firma_params({"type": "object", "required": list(requeridos),
                          "properties": props})


print("\n── el caso real que rompió el turno ──")
f = firma({"action": {"type": "string"},
           "timeout": {"type": "number",
                       "description": "Execution timeout in ms (default: 120s, max: 600s)"}},
          requeridos=["action"])
ok("ms" in f, "la firma dice que el timeout va en ms")
ok("timeout?: number (" in f, "y lo dice pegado al parámetro, no en otro lado")

print("\n── sólo los numéricos, que es lo que lo hace barato ──")
f = firma({"city": {"type": "string", "description": "The city to look up, e.g. Buenos Aires"}})
ok("(" not in f, "un `string` NO arrastra su descripción: se explica solo y cuesta tokens")
f = firma({"n": {"type": "integer", "description": "Cuántos resultados devolver"}})
ok("(Cuántos" in f, "un `integer` con descripción sí la lleva")
f = firma({"n": {"type": "number"}})
ok(f == "n?: number", "un numérico SIN descripción queda como estaba")

print("\n── el recorte ──")
largo = "x" * 200
f = firma({"n": {"type": "number", "description": largo}})
ok(len(f) < 100, f"la descripción se recorta (quedó {len(f)} chars, no 200+)")

print("\n── lo que ya funcionaba sigue igual ──")
f = firma({"queries": {"type": "array", "items": {"type": "string"}}}, requeridos=["queries"])
ok(f == "queries: string[]", "las listas siguen diciendo que son listas")
f = firma({"tipo": {"const": "web_search"}})
ok("web_search" in f, "los valores fijos siguen viajando")

print("\n" + ("PASS la unidad viaja y sigue costando poco"
              if not fallos else f"FAIL {len(fallos)} punto(s)"))
sys.exit(1 if fallos else 0)
