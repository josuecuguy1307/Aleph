#!/usr/bin/env python3
"""verify_senales_mudas.py — dos señales que trabajaban y no se decían.

Cubre los dos defectos de la obra 3, y los cubre por el lado que falla:

  A · TODO `type` que el borde emite tiene que estar en `EVENT_TYPES`. Si no está,
      `EventLog.append` lo RECHAZA y el `except` del emisor se lo come: cero eventos en
      disco y cero señal de error. Así murieron las cuatro señales del plegado y de code
      execution sin que nadie lo notara.
  B · TODA causa que el backend puede levantar tiene que tener copy en `CAUSAS`. Sin
      copy, la causa viaja entera y no se puede mostrar en ninguna superficie.

Con `--caer` se muta la lista de tipos válidos (se le saca la del plegado) y la vara A
tiene que ponerse roja. Los esperados están escritos A MANO: no salen de leer el mismo
archivo que se prueba.
"""
from __future__ import annotations

import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "platform", "flywheel"))

CAER = "--caer" in sys.argv
_OK = _MAL = 0


def ok(cond, etiqueta, detalle=""):
    global _OK, _MAL
    if cond:
        _OK += 1
        print(f"  🟢 {etiqueta}")
    else:
        _MAL += 1
        print(f"  🔴 {etiqueta}" + (f"  ← {detalle}" if detalle else ""))


import events_replay as ER  # noqa: E402

TIPOS = set(ER.EVENT_TYPES)
if CAER:
    TIPOS.discard("aleph_salidas_diferidas")
    print("  ⚠️  MUTANTE: `aleph_salidas_diferidas` sale de EVENT_TYPES")

print("── A · los tipos que el borde emite, contra la lista que los valida ──")
# ESCRITOS A MANO desde los `on_event({...})` de las dos piezas, no leídos de un archivo.
EMITE_EL_BORDE = [
    ("aleph_salidas_diferidas", "salidas_diferidas.paso"),
    ("codemode_script_inicio", "codemode_borde.paso"),
    ("codemode_script_fin", "codemode_borde._cerrar"),
    ("codemode_script_ilegible", "codemode_borde.paso"),
    ("workspace_step", "llamada_repetida.paso / workspace_brain"),
]
for tipo, quien in EMITE_EL_BORDE:
    ok(tipo in TIPOS, f"A · `{tipo}` es válido (lo emite {quien})",
       "no está en EVENT_TYPES: EventLog lo rechaza y el emisor se lo come")

print("── A2 · y el emisor ya no se traga el rechazo ──")
rt = open(os.path.join(RAIZ, "product/backend/app/phase1/router.py"),
          encoding="utf-8").read()
i = rt.find("def _make_space_emitter")
cuerpo = rt[i:i + 1800]
ok("except Exception:\n                pass" not in cuerpo,
   "A2 · `_make_space_emitter` no tiene un `except: pass` mudo")
ok("DESCARTADO" in cuerpo and "warning" in cuerpo,
   "A2b · y avisa qué evento se descartó y en qué espacio")

print("── B · toda causa del backend tiene copy ──")
sem = open(os.path.join(RAIZ, "product/app/design/cuarto/cuarto.semaforo.js"),
           encoding="utf-8").read()
bloque = sem[sem.index("export const CAUSAS = {"):sem.index("export const CAUSAS_PERMANENTES")]
con_copy = set(re.findall(r"^\s{2}([a-z_]+):\s*\{", bloque, re.MULTILINE))
# ESCRITAS A MANO desde `model_use_resolver.py`, no extraídas con el mismo regex
DEL_RESOLVER = ["capability_unavailable", "capability_unknown"]
for c in DEL_RESOLVER:
    ok(c in con_copy, f"B · `{c}` tiene copy en CAUSAS",
       f"sin copy: la causa no se puede mostrar. hay {len(con_copy)} con copy")

print("── B2 · el copy dice la verdad de CADA una, no una frase para las dos ──")
def _es(c):
    m = re.search(r"^\s{2}%s:\s*\{[^}]*es:\s*\"([^\"]+)\"" % c, bloque, re.MULTILINE)
    return m.group(1) if m else ""
ok(_es("capability_unavailable") != _es("capability_unknown"),
   "B2 · las dos causas NO comparten la misma frase",
   f"{_es('capability_unavailable')!r} vs {_es('capability_unknown')!r}")
ok(_es("capability_unavailable") and "roto" not in _es("capability_unavailable").lower(),
   "B2b · y no cae en el default «roto»", _es("capability_unavailable"))

print("── B3 · son permanentes: reintentar con el mismo modelo da lo mismo ──")
perm = sem[sem.index("export const CAUSAS_PERMANENTES"):]
for c in DEL_RESOLVER:
    ok(f'"{c}"' in perm, f"B3 · `{c}` está en CAUSAS_PERMANENTES")

print(f"\n{_OK} verdes · {_MAL} rojas" + ("   [MUTANTE]" if CAER else ""))
raise SystemExit(0 if _MAL == 0 else 1)
