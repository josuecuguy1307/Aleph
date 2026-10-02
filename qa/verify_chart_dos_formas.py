#!/usr/bin/env python3
"""verify_chart_dos_formas.py — EL CHART SE DIBUJA EN SUS DOS FORMAS.

EL DEFECTO, visto en la .app instalada (sidecar 30cde224): el modelo escribió el bloque
```chart en la forma de Chart.js —`{"type":"bar","data":{"labels":[…],"datasets":[…]}}`— y
el `.html` que bajó el usuario traía **el JSON crudo como texto**, entre los párrafos. Es
el mismo defecto que T2.7 y T2.12 cerraron para pdf/docx/pptx, entrando por otra puerta.

Tres funciones del mismo archivo leían el spec por su cuenta y las tres fallaban distinto:
`_chart_a_filas` y `_chart_a_svg` devolvían `None`, y `_gen_dashboard_csv` —que parecía la
tolerante— reventaba con `KeyError: 0` porque en Chart.js `spec["data"]` es un dict.

Ahora hay UN lector (`_chart_normalizado`) y los tres lo usan. Esta vara existe para que
siga siendo uno: si alguien vuelve a leer `spec["labels"]` a mano en cualquiera de los tres,
la forma de Chart.js se cae de nuevo y acá se pone en rojo.

PROBADA CAYENDO: los casos de Chart.js SON la caída. Contra el árbol anterior al arreglo,
R2/R4/R6 dan rojo y R7 explota — que es exactamente el estado que tenía el usuario.

    product/backend/.venv/bin/python qa/verify_chart_dos_formas.py
"""
import json
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "product/backend"))
os.environ.setdefault("ALEPH_DATA_DIR", "/tmp/aleph-vara-chart")

from app.phase1 import artifact_export as X            # noqa: E402

_V, _R, _F = "\033[32m", "\033[31m", "\033[0m"
_filas = []


def _a(nombre, ok, det):
    _filas.append((nombre, ok))
    print(f"  [{(_V+'VERDE'+_F) if ok else (_R+'ROJA'+_F)}] {nombre} — {det}")


#: LAS DOS FORMAS, con los MISMOS números: si las dos se leen bien, las dos tablas coinciden.
RAIZ_SPEC = {"type": "bar", "title": "Ventas", "labels": ["ene", "feb", "mar"],
             "series": [{"name": "Ventas 2025", "data": [48200, 51300, 47900]}]}
CJS_SPEC = {"type": "bar", "data": {"labels": ["ene", "feb", "mar"],
            "datasets": [{"label": "Ventas 2025", "data": [48200, 51300, 47900]}]}}
#: Un hueco REAL: `null` no es cero y no se rellena.
HUECO = {"type": "line", "labels": ["ene", "feb"],
         "series": [{"name": "MM3", "data": [None, 49133.33]}]}
#: Forma que no se entiende ⇒ `None`, jamás una lectura forzada.
ROTA = {"type": "bar", "data": {"labels": ["a"], "datasets": [{"label": "x", "data": "no-es-lista"}]}}


def main() -> int:
    print("\n  el chart se dibuja en sus dos formas\n\nMEDICIÓN")

    fr, fc = X._chart_a_filas(RAIZ_SPEC), X._chart_a_filas(CJS_SPEC)
    _a("R1 · tabla · forma de la raíz", fr is not None and len(fr) == 4,
       f"{'4 filas' if fr else 'None'}")
    _a("R2 · tabla · forma de Chart.js", fc is not None and len(fc) == 4,
       f"{'4 filas' if fc else 'None — el JSON se cuela crudo al pdf/docx'}")
    _a("R3 · las dos dan LO MISMO", fr == fc,
       "mismo dato en las dos formas" if fr == fc else f"{fr} != {fc}")

    sr, sc = X._chart_a_svg(RAIZ_SPEC), X._chart_a_svg(CJS_SPEC)
    _a("R4 · svg · las dos formas", bool(sr) and bool(sc),
       f"raíz={'ok' if sr else 'None'} · chartjs={'ok' if sc else 'None — el html baja sin gráfico'}")
    # El `xmlns="http://www.w3.org/2000/svg"` NO es una conexión: es el namespace que el
    # formato exige y ningún navegador lo resuelve por red. Se saca ENTERO antes de buscar
    # URLs — un `replace("www.w3.org","")` deja `http:///2000/svg`, que sigue matcheando y
    # pone la vara en rojo por su propia regla. (Me pasó al escribirla.)
    sin_ns = re.sub(r'https?://(www\.)?w3\.org[^"\s]*', "", sc or "")
    _a("R5 · el svg no trae CDN ni script",
       bool(sc) and "<script" not in sc and "http://" not in sin_ns and "https://" not in sin_ns,
       "sin script y sin URL externa (el xmlns de w3.org no cuenta: es el namespace)")

    # ⚠️ CON `try`, Y NO ES DEFENSIVO POR COSTUMBRE. Sin él, contra el árbol de antes del
    # arreglo esta línea tira el `KeyError: 0` del que habla la vara y **mata la corrida**:
    # R7, R8 y R9 no se medían nunca, justo en el árbol que tiene el defecto. Una vara que
    # se cae a mitad esconde el resto de lo que iba a decir. La excepción ES el hallazgo,
    # así que se reporta como rojo con su nombre y se sigue.
    try:
        lineas = X._gen_dashboard_csv(
            "```chart\n" + json.dumps(CJS_SPEC) + "\n```", "t").decode("utf-8-sig").strip().splitlines()
        _a("R6 · el dashboard_csv ya no explota", len(lineas) == 4,
           f"{len(lineas)} líneas")
    except Exception as exc:                                            # noqa: BLE001
        _a("R6 · el dashboard_csv ya no explota", False,
           f"{type(exc).__name__}: {exc} — revienta y se lleva el CSV entero, no sólo este chart")

    h = X._chart_a_filas(HUECO)
    _a("R7 · un null sigue siendo un hueco", h is not None and h[1][1] == "",
       "vacío, no cero — rellenarlo sería inventar" if h and h[1][1] == "" else str(h))
    _a("R8 · una forma rota NO se fuerza",
       X._chart_a_filas(ROTA) is None and X._chart_a_svg(ROTA) is None,
       "las dos devuelven None")

    print("\nPROBADA CAYENDO")
    fuente = (RAIZ / "product/backend/app/phase1/artifact_export.py").read_text()
    lectores = fuente.count('spec.get("labels")') + fuente.count('spec.get("series")')
    _a("R9 · UN solo lector del spec", lectores == 0,
       f"lecturas sueltas de spec['labels']/['series'] fuera del normalizador: {lectores} "
       f"({'ninguna' if lectores == 0 else 'volvió a haber más de un criterio — ahí es donde falla'})")

    verde = all(ok for _n, ok in _filas)
    print("\n" + "=" * 70)
    print(f"{(_V+'VERDE'+_F) if verde else (_R+'ROJA'+_F)} · "
          + ("las dos formas se leen igual y nada se cuela crudo" if verde
             else ", ".join(n for n, ok in _filas if not ok)))
    print("=" * 70)
    return 0 if verde else 1


if __name__ == "__main__":
    raise SystemExit(main())
