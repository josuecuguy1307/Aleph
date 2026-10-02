#!/usr/bin/env python
"""Checker T4 — exit 0 = COMPLETÓ (.ipynb corre end-to-end). Uso: t4.py <workdir>"""
import json, sys
from pathlib import Path

wd = Path(sys.argv[1])
out = {"artifact": False, "corre": False, "ref": {}}
try:
    import nbformat
    from nbclient import NotebookClient
    p = wd / "brief_macro.ipynb"
    nb = nbformat.read(p, as_version=4)
    out["artifact"] = True
    NotebookClient(nb, timeout=240, kernel_name="python3",
                   resources={"metadata": {"path": str(wd)}}).execute()
    out["corre"] = True
    out["n_celdas"] = len(nb.cells)
    out["tiene_grafico"] = any("image/png" in (o.get("data") or {})
                               for c in nb.cells if c.cell_type == "code"
                               for o in c.get("outputs", []))
    # referencia para el juez
    import pandas as pd
    fx = Path(__file__).resolve().parents[1] \
        / "fixtures/T4-macro-series.csv"
    df = pd.read_csv(fx)
    cpi = df[df.serie == "CPIAUCSL"].sort_values("fecha").valor.values
    out["ref"]["cpi_yoy_pct"] = round((cpi[-1] / cpi[-13] - 1) * 100, 3)
    out["ref"]["cpi_mom_saar_pct"] = round(((cpi[-1] / cpi[-2]) ** 12 - 1) * 100, 3)
    ok = out["corre"]
except Exception as e:
    out["error"] = str(e)[:400]; ok = False
print(json.dumps(out, ensure_ascii=False))
sys.exit(0 if ok else 1)
