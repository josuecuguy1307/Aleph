#!/usr/bin/env python3
"""verify_recorte_recuperable.py — NADA SE RECORTA EN SILENCIO, y son DOS COSAS.

Decir CUÁNTO se cortó no alcanza: hasta hoy `_bound_tool_result` decía sólo eso, y
medido en la Sala el 2026-08-23 (dos brazos, grok, misma tarea) el modelo lo LEÍA, lo
decía cuatro veces («el listado de pericias está truncado»), reintentaba la misma
consulta con variantes y los dos brazos cerraban **sin entregar la planilla**. Lo que
faltaba era la segunda mitad: CÓMO pedir el resto.

QUÉ PROTEGE ESTA VARA, y por qué cada una puede dar rojo:

  A · sin recorte no pasa nada (identidad byte a byte — el camino de hoy, intacto)
  B · con recorte y sin índice, el pie de SIEMPRE — escrito A MANO acá, no generado
      con la función bajo prueba (ése fue un punto ciego real de esta tanda)
  C · con recorte, el pie NOMBRA la llamada, con id y `desde`
  D · **el crudo se recupera ENTERO** siguiendo el pie al pie de la letra
  E · el `desde` del pie es exactamente el primer carácter que falta (continuidad)
  F · los ids del capador (`t`) no pisan los del pliegue (`s`)
  G · sin disparador el lector no existe (un 0 sin disparador no es una medición)

`--caer` monta el MUTANTE: el capador vuelve al pie viejo —el que declara cuánto y no
cómo—. Las tres que protegen «cómo recuperarlo» tienen que ponerse ROJAS. Si con el
mutante sigue todo verde, la vara no mide nada.
"""
from __future__ import annotations

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.dirname(_AQUI))
for _p in (os.path.join(_RAIZ, "product", "backend"), _AQUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CAER = "--caer" in sys.argv
_verdes = _rojas = 0


def ok(nombre: str, cond: bool, detalle: str = "") -> None:
    global _verdes, _rojas
    if cond:
        _verdes += 1
        print(f"  \U0001f7e2 {nombre}")
    else:
        _rojas += 1
        print(f"  \U0001f534 {nombre}" + (f"   ← {detalle}" if detalle else ""))


import recipe_assembler as ra                                    # noqa: E402
from app.phase1 import salidas_diferidas as sd                   # noqa: E402

if CAER:
    # MUTANTE: el pie de antes del arreglo — dice cuánto, no dice cómo.
    def _mutante(text, *, limit=4000, clave=None, nombre=""):
        text = text or ""
        if len(text) <= limit:
            return text
        head = text[: limit - 200]
        return head + f"\n…[truncado: {len(text) - len(head)} chars omitidos para gestión de contexto]"
    ra._bound_tool_result = _mutante

CLAVE = "vara-recorte"
# El crudo: 12.000 chars con marcas propias en el principio, el medio y el FINAL. La del
# final es la que decide: si el recorte se comiera la cola sin devolverla, no aparece.
CRUDO = ("INICIO-DEL-CRUDO\n"
         + ("x" * 3000) + "\nMEDIO-DEL-CRUDO\n" + ("y" * 8000)
         + "\nFINAL-DEL-CRUDO")

print("── A · sin recorte, el camino de hoy intacto ──")
corto = "una salida chica"
ok("A1 · texto bajo el tope vuelve IDÉNTICO",
   ra._bound_tool_result(corto, clave=CLAVE, nombre="t") == corto)
ok("A2 · el índice no se ensucia con lo que no se recortó",
   not any(f["texto"] == corto for f in sd._indice(CLAVE).por_id.values()))

print("── B · con recorte y sin índice, el pie de SIEMPRE ──")
sin = ra._bound_tool_result(CRUDO, clave=None, nombre="list_skills")
# esperado ESCRITO A MANO: 3.800 de cabeza + el pie viejo, con el número calculado acá
_omit = len(CRUDO) - 3800
_pie_viejo = f"\n…[truncado: {_omit} chars omitidos para gestión de contexto]"
ok("B1 · sin clave, el pie es exactamente el de antes",
   sin == CRUDO[:3800] + _pie_viejo, f"{sin[-90:]!r}")

print("── C · con recorte, el pie dice CÓMO ──")
cap = ra._bound_tool_result(CRUDO, clave=CLAVE, nombre="list_skills")
ok("C1 · el pie nombra la llamada", sd.NOMBRE_LECTOR in cap, cap[-140:])
import re                                                        # noqa: E402
m = re.search(r'id="([a-z0-9]+)" desde=(\d+)', cap)
ok("C2 · el pie trae id y desde", m is not None, cap[-140:])
ok("C3 · sigue diciendo CUÁNTO se cortó", f"{_omit} chars omitidos" in cap)

print("── D · el crudo se recupera ENTERO siguiendo el pie ──")
if m is None:
    ok("D1 · recuperar el resto", False, "sin id en el pie no hay nada que seguir")
    ok("D2 · la cola del crudo llega", False, "idem")
else:
    sid, desde = m.group(1), int(m.group(2))
    juntado, cursor, vueltas = "", desde, 0
    while vueltas < 10:
        vueltas += 1
        tramo = sd.leer(CLAVE, {"id": sid, "desde": cursor})
        cuerpo = tramo.split("\n", 1)[1] if "\n" in tramo else ""
        cola = re.search(r"desde=(\d+)\.\]$", tramo.strip())
        cuerpo = cuerpo.rsplit("\n[… quedan", 1)[0] if "[… quedan" in cuerpo else cuerpo
        juntado += cuerpo
        if cola is None:
            break
        cursor = int(cola.group(1))
    ok("D1 · cabeza + lo recuperado == el crudo, byte por byte",
       CRUDO[:desde] + juntado == CRUDO,
       f"reconstruido {len(CRUDO[:desde] + juntado)} vs crudo {len(CRUDO)}")
    ok("D2 · la marca del FINAL del crudo llega", "FINAL-DEL-CRUDO" in juntado)

print("── E · el `desde` apunta al primer carácter que falta ──")
if m is not None:
    ok("E1 · desde == largo de la cabeza (3.800)", int(m.group(2)) == 3800, m.group(2))
    ok("E2 · la cabeza del pie es la del crudo", cap.startswith(CRUDO[:3800]))
else:
    ok("E1 · desde == largo de la cabeza (3.800)", False, "sin pie")
    ok("E2 · la cabeza del pie es la del crudo", False, "sin pie")

print("── F · los ids del capador no pisan los del pliegue ──")
sid2 = sd.registrar(CLAVE, "otra", "z" * 50)
ok("F1 · el capador numera con prefijo `t`", sid2.startswith("t"), sid2)
ok("F2 · dos registros dan ids distintos", sid2 != (m.group(1) if m else ""))
ok("F3 · el pliegue numera con prefijo `s` (no colisiona)",
   sd._indice("otra-clave").sid(1).startswith("s"))

print("── G · sin disparador, el lector no existe ──")
ok("G1 · una salida chica no registra nada nuevo",
   ra._bound_tool_result("nada", clave=CLAVE, nombre="t") == "nada")
ok("G2 · un id inventado se contesta diciendo que no está, no con datos",
   "no existe una salida" in sd.leer(CLAVE, {"id": "no-existe"}))

print(f"\n{_verdes} verdes · {_rojas} rojas" + ("   [MUTANTE]" if CAER else ""))
