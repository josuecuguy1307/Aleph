#!/usr/bin/env python
"""P011 fixtures — datos sintéticos REALISTAS para el task-set finanzas (T1-T5).

Determinístico (seed=20260611). Re-correr regenera fixtures idénticos.
Genera además reference.json (totales canónicos T1) que vive en el task-set,
NUNCA en el workdir del modelo.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
TASKS = HERE.parent.parent.parent / "catalog" / "evals" / "finanzas-tasks"
rng = random.Random(20260611)
nprng = np.random.default_rng(20260611)

# ---------------------------------------------------------------- T1: xlsx sucio
VENDORS = {
    "Ventas": ["Cliente Andina SA", "Distribuidora Pichincha", "Retail Quito Norte",
               "Comercial Valle SA", "Mayorista Cumbayá", "Cliente Costa SRL"],
    "Otros ingresos": ["Interés cta ahorro", "Reembolso seguro", "Venta activo menor"],
    "Costo de ventas": ["Proveedor Textil Atuntaqui", "Importadora Guayas",
                        "Insumos Latacunga", "Flete DHL", "Aduana SENAE"],
    "Nómina": ["Rol de pagos", "IESS aporte patronal", "Décimo tercero provisión"],
    "Marketing": ["Meta Ads", "Google Ads", "Agencia Creativa Loop", "Feria expoFlor"],
    "Renta": ["Arriendo oficina Av. República", "Alícuota edificio"],
    "Servicios": ["CNT internet", "EEQ electricidad", "Agua EPMAPS", "Claro móvil"],
    "Software": ["Suscripción QuickBooks", "Google Workspace", "Zoom anual", "AWS"],
    "Viajes": ["Vuelo LATAM UIO-GYE", "Hotel Oro Verde", "Viáticos vendedor"],
    "Otros gastos": ["Notaría 12va", "Útiles oficina", "Mantenimiento impresora"],
}
# variantes sucias de categoría que el agente debe unificar
DIRTY = {
    "Ventas": ["Ventas", "ventas ", "VENTAS", "Venta"],
    "Otros ingresos": ["Otros ingresos", "Otros Ingresos", "otros ing."],
    "Costo de ventas": ["Costo de ventas", "COGS", "costo ventas", "Costo de Ventas "],
    "Nómina": ["Nómina", "nomina", "Nomina", "NÓMINA"],
    "Marketing": ["Marketing", "Mktg", "marketing", "MKT"],
    "Renta": ["Renta", "Arriendo", "renta "],
    "Servicios": ["Servicios", "Servicios básicos", "servicios"],
    "Software": ["Software", "SaaS", "software "],
    "Viajes": ["Viajes", "viajes", "Viáticos"],
    "Otros gastos": ["Otros gastos", "Otros", "otros gastos ", "Varios"],
}
SIGN = {"Ventas": 1, "Otros ingresos": 1}
RANGES = {
    "Ventas": (800, 9500), "Otros ingresos": (40, 600),
    "Costo de ventas": (400, 5200), "Nómina": (900, 4800),
    "Marketing": (120, 1800), "Renta": (1450, 1450), "Servicios": (35, 420),
    "Software": (12, 380), "Viajes": (90, 950), "Otros gastos": (15, 400),
}

def t1():
    rows = []
    start = date(2026, 5, 1)
    weights = {"Ventas": 30, "Costo de ventas": 22, "Nómina": 8, "Marketing": 9,
               "Servicios": 9, "Software": 7, "Viajes": 6, "Otros gastos": 9,
               "Otros ingresos": 4, "Renta": 4}
    cats = [c for c, w in weights.items() for _ in range(w)]
    for i in range(508):
        canon = rng.choice(cats)
        d = start + timedelta(days=rng.randint(0, 30))
        fmt = rng.choice(["iso", "lat", "short", "txt"])
        fecha = {"iso": d.isoformat(), "lat": d.strftime("%d/%m/%Y"),
                 "short": f"{d.day}/{d.month}/26",
                 "txt": d.strftime("%d-may-26")}[fmt]
        lo, hi = RANGES[canon]
        monto = round(rng.uniform(lo, hi), 2) * SIGN.get(canon, -1)
        rows.append([fecha, rng.choice(VENDORS[canon]), rng.choice(DIRTY[canon]),
                     monto, canon])
    dup_idx = rng.sample(range(len(rows)), 12)          # 12 duplicados exactos
    rows += [rows[i] for i in dup_idx]
    rng.shuffle(rows)

    wb = Workbook(); ws = wb.active; ws.title = "movimientos"
    ws.append(["Fecha", "Descripción", "Categoría", "Monto USD"])
    for r in rows:
        ws.append(r[:4])
    wb.save(HERE / "T1-transacciones-2026-05.xlsx")

    df = pd.DataFrame(rows, columns=["f", "d", "c", "m", "canon"]).drop_duplicates(
        subset=["f", "d", "c", "m"])
    tot = df.groupby("canon")["m"].sum().round(2).to_dict()
    ingresos = round(tot.get("Ventas", 0) + tot.get("Otros ingresos", 0), 2)
    ref = {"filas_unicas": int(len(df)), "totales_por_categoria": tot,
           "ingresos_totales": ingresos,
           "utilidad_bruta": round(ingresos + tot["Costo de ventas"], 2),
           "utilidad_neta": round(sum(tot.values()), 2)}
    (TASKS / "T1-reference.json").write_text(json.dumps(ref, indent=2))

# ------------------------------------------------------------- T2: panel firma-año
def t2():
    firms, years = 60, range(2018, 2026)
    alpha = nprng.normal(0.04, 0.03, firms)            # FE por firma
    rows = []
    beta_inv, beta_lev, beta_size = 0.35, -0.06, 0.008
    for i in range(firms):
        inv0 = abs(nprng.normal(0.05, 0.03))
        for t, y in enumerate(years):
            inv = max(0.001, inv0 + nprng.normal(0, 0.015))
            lev = min(0.95, max(0.02, nprng.normal(0.38, 0.14)))
            size = nprng.normal(12.5, 1.6)
            yr_shock = {2020: -0.035, 2021: 0.012}.get(y, 0.0)
            roa = (alpha[i] + beta_inv * inv + beta_lev * lev + beta_size * size
                   + yr_shock + nprng.normal(0, 0.018))
            rows.append([f"F{i+1:03d}", y, round(roa, 5), round(inv, 5),
                         round(lev, 4), round(size, 4)])
    pd.DataFrame(rows, columns=["firma_id", "anio", "roa", "inversion_id",
                                "apalancamiento", "log_activos"]
                 ).to_csv(HERE / "T2-panel-firmas.csv", index=False)

# ------------------------------------------------------ T3: comps fundamentals
def t3():
    data = [  # ticker, empresa, rev, ebitda, ni, acciones_m, precio, deuda, caja, filing
        ["NUVT", "Nuvotek Software Corp", 1840.2, 478.5, 231.4, 142.3, 58.40,
         620.0, 410.5, "10-K FY2025 (filed 2026-02-12)"],
        ["DTLK", "DataLink Systems Inc", 2310.7, 531.5, 198.7, 210.8, 41.15,
         980.3, 305.2, "10-K FY2025 (filed 2026-02-26)"],
        ["CLVR", "Clearvue Analytics", 925.4, 138.8, 41.6, 88.6, 71.20,
         150.0, 520.8, "10-Q Q1-2026 (filed 2026-05-07, LTM)"],
        ["OPSG", "OpSignal Holdings", 1512.9, 332.8, 121.0, 175.4, 33.60,
         710.5, 198.4, "10-K FY2025 (filed 2026-03-05)"],
        ["VRTX2", "Vertexa Cloud Group", 684.3, 61.6, -12.3, 96.2, 49.80,
         88.0, 350.1, "10-Q Q1-2026 (filed 2026-04-30, LTM)"],
    ]
    cols = ["ticker", "empresa", "revenue_ltm_musd", "ebitda_ltm_musd",
            "net_income_ltm_musd", "acciones_diluidas_m", "precio_usd",
            "deuda_total_musd", "caja_musd", "fuente_filing"]
    pd.DataFrame(data, columns=cols).to_csv(HERE / "T3-comps-fundamentals.csv",
                                            index=False)

# ------------------------------------------------------------ T4: series macro
def t4():
    months = pd.date_range("2010-01-01", "2026-05-01", freq="MS")
    cpi, rows = 216.7, []
    for d in months:
        y = d.year
        base = 0.0015 if y <= 2020 else (0.006 if y in (2021, 2022) else
                                         0.004 if y == 2023 else 0.0024)
        cpi *= 1 + base + float(nprng.normal(0, 0.0008))
        rows.append([d.date().isoformat(), "CPIAUCSL", round(cpi, 3)])
    un = 9.8
    for d in months:
        y = d.year
        if y < 2020: drift = -0.045
        elif d.year == 2020 and d.month == 4: un = 14.7; drift = 0
        elif y == 2020: drift = -0.7
        elif y <= 2022: drift = -0.18
        else: drift = 0.012
        un = max(3.4, un + drift + float(nprng.normal(0, 0.07)))
        rows.append([d.date().isoformat(), "UNRATE", round(un, 1)])
    ff_path = {2010: 0.15, 2015: 0.2, 2016: 0.45, 2017: 1.0, 2018: 1.9, 2019: 2.3,
               2020: 0.4, 2021: 0.08, 2022: 2.0, 2023: 5.1, 2024: 5.2, 2025: 4.1}
    for d in months:
        tgt = ff_path.get(d.year, 0.15 if d.year < 2015 else 3.6)
        rows.append([d.date().isoformat(), "FEDFUNDS",
                     round(max(0.04, tgt + float(nprng.normal(0, 0.05))), 2)])
    pd.DataFrame(rows, columns=["fecha", "serie", "valor"]).sort_values(
        ["serie", "fecha"]).to_csv(HERE / "T4-macro-series.csv", index=False)

# --------------------------------------------------- T5: budget vs actual xlsx
def t5():
    lineas = [("Ventas", "ingreso", 118000), ("Otros ingresos", "ingreso", 2400),
              ("Costo de ventas", "gasto", 51000), ("Nómina", "gasto", 24500),
              ("Marketing", "gasto", 8200), ("Renta", "gasto", 7250),
              ("Servicios", "gasto", 1900), ("Software", "gasto", 1450),
              ("Viajes", "gasto", 2600), ("Otros gastos", "gasto", 1300)]
    meses = ["Ene", "Feb", "Mar", "Abr", "May"]
    wb = Workbook()
    wsb = wb.active; wsb.title = "Presupuesto"
    wsa = wb.create_sheet("Real")
    for ws in (wsb, wsa):
        ws.append(["Línea", "Tipo"] + [f"{m} 2026" for m in meses])
    for nombre, tipo, base in lineas:
        bud = [round(base / 5 * rng.uniform(0.96, 1.04), 2) for _ in meses]
        # desviaciones reales: ventas -7% en Abr, marketing +28% en May, etc.
        act = [round(b * rng.uniform(0.88, 1.14), 2) for b in bud]
        wsb.append([nombre, tipo] + bud)
        wsa.append([nombre, tipo] + act)
    wb.save(HERE / "T5-presupuesto-vs-real-2026.xlsx")

if __name__ == "__main__":
    TASKS.mkdir(parents=True, exist_ok=True)
    t1(); t2(); t3(); t4(); t5()
    print("fixtures ok:", sorted(p.name for p in HERE.glob("T*")))
