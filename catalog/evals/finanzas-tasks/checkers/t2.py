#!/usr/bin/env python
"""Checker T2 — exit 0 = COMPLETÓ (script corre limpio + tabla existe). Uso: t2.py <workdir>"""
import json, subprocess, sys
from pathlib import Path

wd = Path(sys.argv[1])
out = {"script_corre": False, "tabla": False, "ref_beta_inversion": None}
try:
    r = subprocess.run([sys.executable, "regresion_panel.py"], cwd=wd,
                       capture_output=True, text=True, timeout=180)
    out["script_corre"] = r.returncode == 0
    if r.returncode != 0:
        out["stderr_tail"] = r.stderr[-500:]
    tab = wd / "tabla_regresion.md"
    if not tab.exists():
        tab = wd / "tabla_regresion.txt"
    out["tabla"] = tab.exists()
    if tab.exists():
        t = tab.read_text()
        out["tiene_parentesis_SE"] = "(" in t
        out["tiene_estrellas"] = "*" in t
        out["tiene_N"] = "N" in t
    # referencia FE-within con SE cluster (para el juez)
    import pandas as pd, statsmodels.formula.api as smf
    df = pd.read_csv(Path(__file__).resolve().parents[1]
                     / "fixtures/T2-panel-firmas.csv")
    m = smf.ols("roa ~ inversion_id + apalancamiento + log_activos + C(firma_id)",
                df).fit(cov_type="cluster", cov_kwds={"groups": df["firma_id"]})
    out["ref_beta_inversion"] = round(float(m.params["inversion_id"]), 4)
    out["ref_se_inversion"] = round(float(m.bse["inversion_id"]), 4)
    ok = out["script_corre"] and out["tabla"]
except Exception as e:
    out["error"] = str(e); ok = False
print(json.dumps(out, ensure_ascii=False))
sys.exit(0 if ok else 1)
