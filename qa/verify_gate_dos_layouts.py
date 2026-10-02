#!/usr/bin/env python3
"""verify_gate_dos_layouts.py — EL GATE DEL BUNDLE MIDE LOS DOS LAYOUTS. [TANDA 3]

EL ROJO FALSO QUE LA PIDIÓ
--------------------------
`gate_bundle_aleph._datos_que_faltan` leía el **TOC del CArchive del ejecutable**. Eso vale
para un onefile, donde los `datas` viven adentro del binario. En **onedir** viven sueltos en
`_internal/` — la misma raíz que el proceso ve como `sys._MEIPASS` (medido con un onedir
mínimo el 2026-08-22). Resultado: el primer build onedir abortó reportando **47 archivos
«que no viajaron»** con los 47 en disco al lado del binario.

No fue un defecto del bundle: fue el guard mirando el lugar equivocado. Y es peor que un
verde falso, porque tira un build de 20 minutos y manda a buscar un archivo que está.
Hermana de la lección de la obra 6d («el TOC no es el bundle»).

QUÉ MIDE
--------
Con layouts FALSOS pero de la forma real —un dir con `<exe>` + `_internal/<datos>`— se
comprueba que el guard:
  · encuentra los datos declarados cuando están;
  · **da rojo** cuando falta uno (si no puede, no mide nada);
  · y sigue leyendo el TOC cuando NO hay `_internal` (onefile), sin regresión.

CORRE: `python3 qa/verify_gate_dos_layouts.py`
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "qa"))
sys.path.insert(0, str(RAIZ / "deploy" / "fase4"))

FALLOS: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"  {'✓' if cond else '✗'} {etiqueta}" + ("" if cond or not extra else f" — {extra}"))
    if not cond:
        FALLOS.append(etiqueta)


def main() -> int:
    import gate_bundle_aleph as G

    requeridos = G._datos_requeridos()
    ok(len(requeridos) > 10, "la lista declarada de datos se pudo leer",
       f"{len(requeridos)}")

    tmp = Path(tempfile.mkdtemp(prefix="vara-gate-"))
    try:
        # ── ONEDIR FALSO, con la forma REAL: <dir>/<exe> + <dir>/_internal/<datos> ──
        d = tmp / "onedir"
        (d / "_internal").mkdir(parents=True)
        exe = d / "aleph_sidecar"
        exe.write_bytes(b"no soy un Mach-O, y no hace falta que lo sea: este guard mira DISCO")
        for rel in requeridos:
            p = d / "_internal" / rel.replace("/", os.sep)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")

        ok(G._raiz_onedir(exe) == d / "_internal",
           "`_raiz_onedir` reconoce el layout onedir", str(G._raiz_onedir(exe)))

        faltan, estan, nota = G._datos_que_faltan(exe)
        ok(nota == "", "onedir: el guard pudo mirar (no es NO MEDIBLE)", nota)
        ok(not faltan and len(estan) == len(requeridos),
           "onedir: encuentra los datos declarados en `_internal/`",
           f"faltan={len(faltan)} estan={len(estan)}")

        # ── Y TIENE QUE PODER DAR ROJO. Un guard que sólo sabe decir que sí no mide. ──
        victima = requeridos[len(requeridos) // 2]
        (d / "_internal" / victima.replace("/", os.sep)).unlink()
        faltan2, _, nota2 = G._datos_que_faltan(exe)
        ok(nota2 == "" and faltan2 == [victima],
           "onedir: borrar UN dato declarado lo pone en rojo, y lo nombra",
           f"faltan={faltan2[:3]}")

        # ── ONEFILE: sin `_internal`, se sigue leyendo el TOC ──────────────────────────
        solo = tmp / "onefile"
        solo.mkdir()
        falso = solo / "aleph_sidecar"
        falso.write_bytes(b"tampoco es un CArchive")
        ok(G._raiz_onedir(falso) is None,
           "sin `_internal/` el guard NO cree que sea onedir")
        _, _, nota3 = G._datos_que_faltan(falso)
        # No es un CArchive válido ⇒ el guard tiene que decir NO MEDIBLE, jamás verde.
        ok(nota3 != "",
           "onefile ilegible ⇒ NO MEDIBLE declarado, nunca verde por omisión", nota3)

        # ── El onefile REAL instalado sigue certificando por TOC (sin regresión) ──────
        # ── LA .app INSTALADA, SEA CUAL SEA SU LAYOUT ────────────────────────────────
        # ⚠️ ESTA ASERCIÓN DECÍA «el onefile INSTALADO» y daba rojo apenas se instaló una
        # onedir: el instrumento tenía horneado un hecho que esta misma tanda cambió. Lo
        # que hay que exigirle al guard no es un layout, es que **certifique el que haya**.
        inst = Path("/Applications/Aleph.app/Contents/MacOS/aleph_sidecar")
        if inst.exists():
            raiz = G._raiz_onedir(inst)
            forma = "onedir (.app)" if raiz else "onefile"
            faltan4, estan4, nota4 = G._datos_que_faltan(inst)
            ok(nota4 == "" and not faltan4 and len(estan4) == len(requeridos),
               f"la .app INSTALADA certifica sus datos · forma={forma}",
               f"nota={nota4} faltan={len(faltan4)} raiz={raiz}")
        else:
            print("  · [no medible] no hay .app instalada para el contraste real")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n✗ %d fallo(s)" % len(FALLOS) if FALLOS else "\n✓ gate en dos layouts: todo verde")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
