#!/usr/bin/env python3
"""verify_marcador_no_se_repite.py — el andamio no se le manda al usuario.

HERMANA de `verify_marcador_ilegible.py`, y cubre el caso CONTRARIO. Aquélla cuida que un
marcador que NO parsea falle visible en vez de servirse como prosa. Ésta cuida el caso en
que SÍ parsea: la llamada ya viaja estructurada en `tool_calls`, así que repetirla en
`content` es mandarle a la persona el `<function=…>{…}` que ella nunca tenía que ver.

Correr:  python3 platform/assembler/cli_brain/verify_marcador_no_se_repite.py
"""
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))

from cli_brain.prompt_bridge import FiltroVivo, texto_visible  # noqa: E402

fallos = []


def ok(cond, que):
    print(("  ✓ " if cond else "  ✗ ") + que)
    if not cond:
        fallos.append(que)


def vivo(trozos):
    f = FiltroVivo()
    return "".join(f.empujar(t) for t in trozos) + f.resto()


print("\n— de una pieza —")
ok(texto_visible('Listo.\n<function=bash>{"a":1}</function>') == "Listo.",
   "la prosa que precede al marcador se conserva, el marcador no")
ok(texto_visible('<function=bash>{"a":1}</function>') == "",
   "un turno que es SÓLO marcador no manda nada de texto")
ok(texto_visible("prosa sin marcadores") == "prosa sin marcadores",
   "un texto normal no se toca")

print("\n— partido, que es como llega en streaming —")
ok(vivo(["Voy.", "<fun", "ction=read>{}"]) == "Voy.",
   "EL CASO QUE UN FILTRO DE UNA PIEZA NO ATRAPA: el marcador cruzado entre dos pedazos")
ok("".join(texto_visible(t) for t in ["Voy.", "<fun", "ction=read>{}"]) == "Voy.<function=read>{}",
   "…y se comprueba que de a uno, efectivamente, se cuela entero")
ok(vivo(["Ya lo reviso.", " Listo."]) == "Ya lo reviso. Listo.",
   "el texto sano cruza sin perder un carácter")

print("\n— lo retenido que no era marcador vuelve —")
ok(vivo(["termina en <"]) == "termina en <", "un `<` al final no se lo come")
ok(vivo(["dos < tres"]) == "dos < tres", "un `<` que es prosa no dispara nada")

print("\n— y el corte no se reabre —")
f = FiltroVivo()
f.empujar('Listo. <function=bash>{"a":1}')
ok(f.empujar("} y sigo hablando") == "" and f.resto() == "",
   "confirmado el marcador, no sale nada más en el turno")

print("\n" + ("PASS el andamio no se repite como texto"
              if not fallos else f"FAIL {len(fallos)} roja(s)"))
sys.exit(1 if fallos else 0)
