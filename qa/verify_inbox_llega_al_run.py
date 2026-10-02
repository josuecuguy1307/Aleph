"""verify_inbox_llega_al_run.py — EL ADJUNTO LLEGA AL WORKDIR DEL RUN. [T2.5c · el bug de alcance]

EL BUG QUE FIJA, medido contra la .app INSTALADA (sidecar 2aa64a13):
el inbox tenía el PDF, el belt levantaba sus 8 servers… y `adjuntos/` NO existía en el
`run_outputs` del run. Causa: `_inbox_dir_de` vivía a nivel de MÓDULO y llamaba a
`_bearer`, que es un CLOSURE de `build_phase1_router`. La llamada tiraba `NameError`, un
`except` mudo lo volvía `None`, y el turno contestaba «no veo ningún archivo» sin una sola
línea en el log. Dos fallas en una: el alcance, y el silencio que lo escondió.

Por eso esta vara mide DOS cosas que se rompen por separado:

  R1 · MISMO ALCANCE. `_inbox_dir_de` y `_bearer` tienen que estar los dos DENTRO de
       `build_phase1_router`. Se mide sobre el fuente de la función construida, no con un
       grep del archivo: un grep no distingue un `def` de módulo de uno anidado, que es
       justo la distinción que falló.

  R2 · EL FALLO SE VE. El `except` tiene que loguear. Un adjunto que no llega es una
       promesa rota, y sin línea en el log nadie puede saber por qué.

PROBADA CAYENDO: R1 se comprueba además contra el fuente del MÓDULO — si alguien vuelve a
sacar el helper afuera, `_bearer` deja de estar en el mismo alcance y R1 se pone roja.

    product/backend/.venv/bin/python qa/verify_inbox_llega_al_run.py
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
os.environ.setdefault("ALEPH_ROLE", "client")
sys.path.insert(0, str(_REPO / "product" / "backend"))
sys.path.insert(0, str(_REPO / "platform"))

_V, _R, _FIN = "\033[32m", "\033[31m", "\033[0m"
_filas = []
_nomed: list = []


def _anotar(b, ok, det):
    _filas.append((b, ok))
    print(f"  [{(_V+'VERDE'+_FIN) if ok else (_R+'ROJA'+_FIN)}] {b} — {det}")


def main() -> int:
    from app.phase1 import router as R
    src = inspect.getsource(R.build_phase1_router)

    print("\n  el adjunto llega al workdir del run\n\nMEDICIÓN")
    juntos = "def _inbox_dir_de" in src and "def _bearer" in src
    _anotar("R1 · mismo alcance", juntos,
            "`_inbox_dir_de` y `_bearer` viven los dos dentro de build_phase1_router"
            if juntos else "el helper quedó FUERA: `_bearer` es un closure y va a dar NameError")

    # Hasta el SIGUIENTE `def` del mismo alcance, no un corte por cantidad de caracteres:
    # el docstring de este helper es largo a propósito y un corte fijo lo dejaba afuera —
    # la vara daba rojo por su propia regla, no por el código.
    #
    # ⚠️ SI R1 ESTÁ ROJA, R2 NO TIENE SUJETO. Antes esto era un `src.index` pelado: con el
    # helper afuera tiraba `ValueError` y MATABA la vara en la línea 59, así que R3 y la
    # sección PROBADA CAYENDO no se medían nunca. Una vara que se cae a mitad esconde el
    # resto de lo que iba a decir — y el árbol donde eso pasa es justamente el que tiene
    # el bug. No medible no es rojo: se declara como tal y no se cuenta como verde.
    if not juntos:
        _nomed.append("R2 · el fallo se ve")
        print("  [NO MEDIBLE] R2 · el fallo se ve — sin el helper en este alcance no hay "
              "except que mirar (lo dice R1)")
    else:
        i = src.index("def _inbox_dir_de")
        j = src.find("\n    def ", i + 10)
        cuerpo = src[i:j if j > 0 else len(src)]
        ve = ("_log.warning" in cuerpo or "_log.exception" in cuerpo)
        _anotar("R2 · el fallo se ve", ve,
                "el except loguea la causa" if ve else "el except es MUDO — el bug vuelve invisible")

    from app.phase1 import executor as E
    esrc = inspect.getsource(E.run_puppet_e2e)
    cablea = "inbox_dir" in esrc and "ADJUNTOS_DIR" in esrc
    _anotar("R3 · el executor copia", cablea,
            "run_puppet_e2e recibe inbox_dir y copia a la carpeta de adjuntos")

    print("\nPROBADA CAYENDO")
    msrc = inspect.getsource(R)
    fuera = msrc.count("def _inbox_dir_de") - src.count("def _inbox_dir_de")
    _anotar("R1 · CAÍDA", fuera == 0,
            f"copias del helper a nivel de módulo: {fuera} "
            f"({'ninguna, bien' if fuera == 0 else 'volvió afuera — ahí es donde falla'})")

    verde = all(ok for _, ok in _filas) and not _nomed
    print(f"\n{'='*70}")
    print(f"{(_V+'VERDE'+_FIN) if verde else (_R+'ROJA'+_FIN)} · "
          + ("el helper ve el closure y su fallo no es mudo" if verde
             else ", ".join([b for b, ok in _filas if not ok]
                            + [f"{b} (no medible)" for b in _nomed])))
    print("=" * 70)
    return 0 if verde else 1


if __name__ == "__main__":
    raise SystemExit(main())
