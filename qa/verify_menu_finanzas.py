#!/usr/bin/env python3
"""verify_menu_finanzas.py — corredor de `verify_menu_finanzas.mjs`. [rediseño · fase 5 · obra 5.0]

POR QUÉ EXISTE ESTE ARCHIVO DE DIEZ LÍNEAS, y no es burocracia: `qa/correr_varas.py` sólo
recolecta `verify_*.py` (`correr_varas.py:140`). Hay **111 varas `.mjs` en el árbol que el
pool no corre nunca** — la misma queja que `dom_minimo.mjs` dejó escrita: «están todas en
el árbol, todas verdes de hace semanas, ninguna corriendo». Una vara que el pool no ve es
una vara que se abandona. Este runner la mete en la corrida.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

VARA = Path(__file__).with_suffix(".mjs")

def main() -> int:
    r = subprocess.run(["node", str(VARA), *sys.argv[1:]], text=True)
    return r.returncode

if __name__ == "__main__":
    raise SystemExit(main())
