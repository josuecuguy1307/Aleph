#!/usr/bin/env python3
"""Tier 1 — corre el agente de finanzas por el PATH DE PROD (:8080) y verifica el .xlsx."""
import json, sys, urllib.request, urllib.error
from pathlib import Path

BASE = "http://localhost:8080"
HERE = Path(__file__).resolve().parent
RECIPE = json.loads((HERE / "recipe-tier1.json").read_text())
PROMPT = ("Armame un Excel con el PIB de Ecuador del Banco Mundial y la tabla de "
          "comercialización de derivados del Banco Central del Ecuador, con la fuente "
          "de cada dato. El archivo se llama finanzas_ecuador.xlsx.")


def _post(path, payload, timeout=240):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": e.read().decode(errors="replace") if hasattr(e, "read") else ""}


# 1) validar
st, val = _post("/v1/recipes/validate", {"recipe": RECIPE}, timeout=20)
print(f"[validate] status={st} valid={val.get('valid')} errors={val.get('errors')}")
if not (st == 200 and val.get("valid")):
    print("RECIPE INVÁLIDA — abortando"); sys.exit(1)

# 2) run E2E
st, out = _post("/v1/puppets/run", {"recipe": RECIPE, "prompt": PROMPT}, timeout=240)
print(f"\n[run] status={st} run_id={out.get('run_id')} ok={out.get('ok')} "
      f"gate_enforced={out.get('gate_enforced')} instr_log={out.get('instrumentation_log_id')} "
      f"error={out.get('error')}")
rec = out.get("record") or {}
print(f"[run] model_final={rec.get('model_final')} turns={rec.get('turns')} "
      f"tools_cabled={rec.get('tools_cabled')} workdir={rec.get('workdir')}")
print("[run] tool-calls (lo que el agente hizo):")
xlsx_path = None
for t in rec.get("tool_calls", []):
    print(f"   - {t.get('tool')} [{t.get('gate_action')}] -> {str(t.get('result'))[:120]}")
    if t.get("tool") == "build_workbook":
        try:
            r = json.loads(t["result"]) if isinstance(t["result"], str) else t["result"]
            xlsx_path = r.get("path")
        except Exception:
            pass
print(f"\n[run] respuesta del agente:\n   {(out.get('answer') or '').strip()[:400]}")

# fallback: buscar el xlsx en el workdir
if not xlsx_path and rec.get("workdir"):
    found = sorted(Path(rec["workdir"]).glob("*.xlsx"))
    if found:
        xlsx_path = str(found[0])

print(f"\n[run] xlsx producido: {xlsx_path}")
# guardar el path para el verificador
(HERE / "_last_xlsx.txt").write_text(xlsx_path or "", encoding="utf-8")
(HERE / "_last_run.json").write_text(json.dumps({"run_id": out.get("run_id"), "xlsx": xlsx_path,
                                                 "ok": out.get("ok"), "gate_enforced": out.get("gate_enforced")},
                                                indent=2), encoding="utf-8")
sys.exit(0 if (out.get("ok") and xlsx_path) else 1)
