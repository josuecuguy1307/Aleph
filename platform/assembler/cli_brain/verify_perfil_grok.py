#!/usr/bin/env python3
"""verify_perfil_grok.py — el perfil de producción de Grok no le da órdenes de canario.

POR QUÉ EXISTE. `aleph-zero.md` es el perfil que `grok_cli._instalar_perfil` copia al
workdir en CADA turno de Grok, en las siete superficies. Hasta hoy su cuerpo decía:

    «You have no tools. If asked to read a file, reply exactly NO-LEI-ARCHIVO.»

Las dos frases hacen daño y la segunda es un CANARIO DE UNA MEDICIÓN VIEJA que quedó en
producción — y está en la `.app` instalada, en dos copias. Medido el 2026-08-23: un turno
de la Sala que pedía armar un .xlsx cerró respondiendo literalmente `NO-LEI-ARCHIVO`, sin
entregar el archivo. Se reportó como «el modelo inventó un marcador»; era el perfil
mandándoselo. El grep que lo habría encontrado falló por buscar sólo en `.py/.js/.html`.

QUÉ PROTEGE, y por qué cada una puede dar rojo:
  A · ningún marcador de canario sobrevive en el perfil
  B · el perfil no le miente al modelo diciéndole que no tiene herramientas
  C · el frontmatter que produce el ahorro medido (5.508 tok) sigue INTACTO — este
      arreglo toca el cuerpo, no la perilla
  D · el perfil sigue siendo el que `build_argv` instala (`--agent aleph-zero`)

`--caer` monta el MUTANTE: se le devuelve al cuerpo la línea vieja. A y B tienen que
ponerse ROJAS.
"""
from __future__ import annotations

import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_ASM = os.path.dirname(_AQUI)
if _ASM not in sys.path:
    sys.path.insert(0, _ASM)

CAER = "--caer" in sys.argv
_v = _r = 0


def ok(n, cond, det=""):
    global _v, _r
    if cond:
        _v += 1
        print(f"  \U0001f7e2 {n}")
    else:
        _r += 1
        print(f"  \U0001f534 {n}" + (f"   ← {det}" if det else ""))


from cli_brain.grok_cli import _perfil_path, _PERFIL_NOMBRE, GrokCliProvider  # noqa: E402

cuerpo = open(_perfil_path(), encoding="utf-8").read()
if CAER:
    cuerpo = cuerpo + "\nYou have no tools. If asked to read a file, reply exactly NO-LEI-ARCHIVO.\n"

# Marcadores de canario: TODO-MAYÚSCULAS-CON-GUIONES precedido de «reply exactly» o
# «respondé exactamente». Escrito a mano, no derivado del archivo bajo prueba.
_ORDENES = (r"reply exactly\s+[A-Z][A-Z0-9-]{4,}",
            r"respond[eé] exactamente\s+[A-Z][A-Z0-9-]{4,}",
            r"escrib[ií] exactamente\s+[A-Z][A-Z0-9-]{4,}")

print("── A · sin órdenes de canario en producción ──")
hallada = [p for p in _ORDENES if re.search(p, cuerpo, re.I)]
ok("A1 · no hay «reply exactly <MARCADOR>»", not hallada, str(hallada))
ok("A2 · el marcador concreto que rompió una entrega no está",
   "NO-LEI-ARCHIVO" not in cuerpo)

print("── B · el perfil no le miente sobre sus herramientas ──")
ok("B1 · no afirma «You have no tools»", "You have no tools" not in cuerpo)
ok("B2 · le dice de dónde SÍ salen las herramientas",
   ("catálogo" in cuerpo or "catalogo" in cuerpo) and "<function=" in cuerpo)

print("── C · la perilla del ahorro, intacta ──")
fm = cuerpo.split("---")[1] if cuerpo.count("---") >= 2 else ""
for clave in ("name: aleph-zero", "mcpInheritance: none", "agents_md: false",
              "disallowedTools:"):
    ok(f"C · el frontmatter conserva `{clave.rstrip(':')}`", clave in fm, fm[:80])

print("── D · sigue siendo el perfil que se instala ──")
argv = GrokCliProvider().build_argv("/bin/echo", "P", "grok-4.6", os.path.dirname(_perfil_path()))
ok("D1 · `--agent aleph-zero` está en el argv real",
   "--agent" in argv and _PERFIL_NOMBRE in argv, " ".join(argv[1:])[:90])

print(f"\n{_v} verdes · {_r} rojas" + ("   [MUTANTE]" if CAER else ""))
