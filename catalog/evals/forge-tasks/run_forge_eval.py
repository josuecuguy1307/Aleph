#!/usr/bin/env python3
"""
run_forge_eval.py — EVAL de la FORJA (gate de la Fase 3).

Para cada caso de cases.json: POST /v1/forge {intent} → puntúa la propuesta contra el GOLD:
  · tool-F1 (servers; ok_extra no penaliza)   bar ≥ 0.80
  · zona (sobre los servers acertados)         bar ≥ 0.90
  · gate_recall (casos con gate money/send)    bar = 1.00
  · alucinación (server fuera del catálogo)    bar = 0
  · conexión (incluye el connector esperado)
  · caso canónico "Reportero financiero" PASA

Uso:  python3 catalog/evals/forge-tasks/run_forge_eval.py
Requiere el backend en :8080 (BASE override por env PUPPET_BASE).
Stdlib pura.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = os.environ.get("PUPPET_BASE", "http://127.0.0.1:8080")
HERE = Path(__file__).resolve().parent


def _post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode())


def score_servers(pred, gold):
    """F1 con servers requeridos + any_of (fuentes equivalentes: basta una del grupo) + ok_extra
    (no penaliza). Devuelve (f1, matched_set) — matched = servers de pred que cuentan (para zona)."""
    pred = set(pred)
    req = set(gold.get("servers", []))
    ok_extra = set(gold.get("ok_extra", []))
    any_of = gold.get("any_of", [])
    tp, fn, matched, anyof_members = 0, 0, set(), set()
    for s in req:
        if s in pred:
            tp += 1; matched.add(s)
        else:
            fn += 1
    for grp in any_of:
        anyof_members |= set(grp)
        hit = pred & set(grp)
        if hit:
            tp += 1; matched |= hit
        else:
            fn += 1
    fp = len(pred - req - anyof_members - ok_extra)
    p = tp / (tp + fp) if (tp + fp) else 1.0
    r = tp / (tp + fn) if (tp + fn) else 1.0
    return (2 * p * r / (p + r) if (p + r) else 0.0), matched


def main():
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    catalog_servers = {a["server"] for a in _get("/v1/atoms/catalog")["atoms"]}

    f1s, zone_ok, zone_tot = [], 0, 0
    gate_cases, gate_hit = 0, 0
    conn_cases, conn_hit = 0, 0
    halluc = 0
    canonical_ok = None
    rows = []

    for c in cases:
        g = c["gold"]
        try:
            out = _post("/v1/forge", {"intent": c["intent"]})
        except Exception as e:
            rows.append((c["id"], 0.0, "ERR " + str(e)[:40])); f1s.append(0.0); continue
        blocks = (out.get("proposal") or {}).get("blocks") or []
        pred_servers = [b.get("ref") for b in blocks if b.get("ref")]
        pred_zone = {b["ref"]: b["zone"] for b in blocks if b.get("ref")}
        gates = set(out.get("gates_surfaced") or [])
        conns = set(out.get("needs_connection") or [])

        # alucinación
        h = [s for s in pred_servers if s not in catalog_servers]
        halluc += len(h)

        # F1 (servers requeridos + any_of + ok_extra)
        sc, tp = score_servers(pred_servers, g)
        f1s.append(sc)

        # zona (sobre TP)
        zc = 0
        for s in tp:
            zone_tot += 1
            if pred_zone.get(s) in (g.get("zones", {}).get(s) or []):
                zone_ok += 1; zc += 1

        # gate recall
        gnote = ""
        if g.get("gate"):
            gate_cases += 1
            if gates & set(g.get("gate_servers") or []):
                gate_hit += 1; gnote = "gate✓"
            else:
                gnote = "gate✗"

        # conexión
        cnote = ""
        if g.get("connection"):
            conn_cases += 1
            if g["connection"] in conns:
                conn_hit += 1; cnote = "conn✓"
            else:
                cnote = "conn✗"

        note = f"pred={sorted(pred_servers)} z={zc}/{len(tp)} {gnote} {cnote}" + (" HALLUC=" + str(h) if h else "")
        rows.append((c["id"], sc, note))
        if c.get("canonical"):
            canonical_ok = (sc >= 0.5 and gates & set(g.get("gate_servers") or []) and g["connection"] in conns)

    mean_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    zone_acc = zone_ok / zone_tot if zone_tot else 1.0
    gate_recall = gate_hit / gate_cases if gate_cases else 1.0
    conn_acc = conn_hit / conn_cases if conn_cases else 1.0

    print("\n=== POR CASO ===")
    for cid, sc, note in rows:
        print(f"  {cid:22s} F1={sc:.2f}  {note}")

    print("\n=== RESUMEN ===")
    print(f"  tool-F1 (media)   {mean_f1:.3f}   bar≥0.80   {'OK' if mean_f1>=0.80 else 'FAIL'}")
    print(f"  zona (acc)        {zone_acc:.3f}   bar≥0.90   {'OK' if zone_acc>=0.90 else 'FAIL'}")
    print(f"  gate recall       {gate_recall:.3f}   bar=1.00   {'OK' if gate_recall>=1.0 else 'FAIL'}  ({gate_hit}/{gate_cases})")
    print(f"  alucinación       {halluc}       bar=0      {'OK' if halluc==0 else 'FAIL'}")
    print(f"  conexión (acc)    {conn_acc:.3f}              ({conn_hit}/{conn_cases})")
    print(f"  canónico Reportero {'OK' if canonical_ok else 'FAIL'}")

    passed = (mean_f1 >= 0.80 and zone_acc >= 0.90 and gate_recall >= 1.0 and halluc == 0 and bool(canonical_ok))
    print(f"\n  >>> EVAL {'PASS' if passed else 'FAIL'} <<<\n")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
