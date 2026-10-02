"""verify_cara_baseline.py — corredor de `qa/vara_visual.mjs`. [rediseño · fase 1 · cable (c)]

Mete la vara visual en el pool (`correr_varas.py` sólo recolecta `verify_*.py`). Tarda
~2 min: son 24 arranques de Chrome (dos por pantalla, porque cada una se captura dos veces
para poder decir si es medible). Es el precio de tener, por primera vez, una red que ve la
cara — y sale mucho más barato que un rediseño que rompe una pantalla en silencio.

⚠️ SI NO ESTÁ CHROME, ESTO ES ROJO, NO SALTEADO. La ausencia de una señal no es una
medición: una vara que se saltea sola cuando le falta su instrumento le informa «verde» al
pool sobre algo que nadie miró.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

VARA = Path(__file__).parent / "vara_visual.mjs"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

def main() -> int:
    if not CHROME.is_file():
        print(f"✗ no está el instrumento: {CHROME}")
        print("  Esta vara NO puede correr, y eso es rojo. Instalá Chrome o sacá esta vara")
        print("  del árbol — pero no la dejes dando verde sobre una pantalla que nadie miró.")
        return 1
    return subprocess.run(["node", str(VARA), *sys.argv[1:]], text=True).returncode

if __name__ == "__main__":
    raise SystemExit(main())
