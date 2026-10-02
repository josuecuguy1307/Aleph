#!/usr/bin/env python3
"""
verify_xlsx.py — GATE de Tier 1: número = fuente, nunca inventado.

Abre el .xlsx que produjo el run-executor y cruza CADA celda numérica contra la
VERDAD DE TIERRA recalculada de forma independiente:
  • World Bank: re-fetch en vivo de la API pública → set de (año, valor).
  • BCE: re-corre el ingestor determinista → set de valores con su procedencia.
Si una sola celda no traza a la fuente, o le falta procedencia, FALLA.
"""
import json, sys, urllib.request
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
INGESTOR = REPO / "platform" / "ingestor"

xlsx_path = (HERE / "_last_xlsx.txt").read_text().strip() if (HERE / "_last_xlsx.txt").exists() else ""
if len(sys.argv) > 1:
    xlsx_path = sys.argv[1]
if not xlsx_path or not Path(xlsx_path).exists():
    print(f"FAIL: no encuentro el xlsx ({xlsx_path!r})"); sys.exit(2)

print(f"verificando: {xlsx_path}\n")

# ── VERDAD DE TIERRA 1: World Bank en vivo ──────────────────────────────────────
WB_URL = ("https://api.worldbank.org/v2/country/EC/indicator/NY.GDP.MKTP.CD"
          "?format=json&date=2015:2023&per_page=1000")
req = urllib.request.Request(WB_URL, headers={"User-Agent": "verify/0.1"})
with urllib.request.urlopen(req, timeout=25) as r:
    wb = json.loads(r.read().decode())
wb_truth = {}  # año -> valor
for o in (wb[1] or []):
    if o.get("value") is not None:
        wb_truth[int(o["date"])] = float(o["value"])
print(f"World Bank verdad-de-tierra: {len(wb_truth)} obs (años {min(wb_truth)}-{max(wb_truth)})")

# ── VERDAD DE TIERRA 2: ingestor BCE determinista ───────────────────────────────
sys.path.insert(0, str(INGESTOR))
from runner import run_ingest_from_recipe_file  # type: ignore
res = run_ingest_from_recipe_file(
    str(INGESTOR / "fixtures" / "bce_estmacro012024.pdf"),
    str(INGESTOR / "recipes" / "bce-estmacro-comercializacion-derivados.json"))
bce_truth = set()  # valores numéricos legítimos
for d in res.data:
    if d.value is not None and isinstance(d.value, (int, float)):
        bce_truth.add(round(float(d.value), 4))
print(f"BCE verdad-de-tierra: {len(bce_truth)} valores numéricos del ingestor\n")

# ── recorrer el xlsx ────────────────────────────────────────────────────────────
wb_x = openpyxl.load_workbook(xlsx_path, data_only=True)
print(f"hojas: {wb_x.sheetnames}")

checked = 0
traced = 0
no_prov = 0
mismatches = []

def _col_idx(ws, header_label):
    for j, c in enumerate(ws[1], start=1):
        if c.value and header_label.lower() in str(c.value).lower():
            return j
    return None

for name in wb_x.sheetnames:
    if name == "PROCEDENCIA":
        continue
    ws = wb_x[name]
    val_col = _col_idx(ws, "valor") or _col_idx(ws, "GDP") or _col_idx(ws, "PIB")
    prov_col = _col_idx(ws, "procedencia")
    is_wb = "world" in name.lower() or "bank" in name.lower()
    anio_col = _col_idx(ws, "año") or _col_idx(ws, "anio")
    for row in ws.iter_rows(min_row=2):
        val = row[val_col - 1].value if val_col else None
        if not isinstance(val, (int, float)):
            continue
        checked += 1
        prov = row[prov_col - 1].value if prov_col else None
        if not (prov and str(prov).strip()):
            no_prov += 1
        # cruce contra la fuente
        if is_wb:
            anio = row[anio_col - 1].value if anio_col else None
            ok = anio in wb_truth and abs(wb_truth[anio] - float(val)) < 0.5
        else:
            ok = round(float(val), 4) in bce_truth
        if ok:
            traced += 1
        else:
            mismatches.append((name, val, "no traza a la fuente"))

print(f"\n=== RESULTADO ===")
print(f"celdas numéricas revisadas : {checked}")
print(f"trazadas a su fuente        : {traced}")
print(f"sin procedencia             : {no_prov}")
print(f"NO trazadas (inventadas?)   : {len(mismatches)}")
for m in mismatches[:10]:
    print(f"   ✗ {m}")

ok = (checked > 0 and traced == checked and no_prov == 0 and not mismatches)
print(f"\n{'✅ VERDE — número = fuente, cero inventados, cero sin-procedencia' if ok else '❌ ROJO — hay celdas sin trazar o sin procedencia'}")
sys.exit(0 if ok else 1)
