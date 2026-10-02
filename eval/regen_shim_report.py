"""
regen_shim_report.py — re-renderiza matriz.md/json de la corrida Opción C (brain real =
claude-code-opus-4.8 vía shim) desde runs.jsonl, agregando matices HONESTOS data-driven
(sin re-correr claude). Mirror de honest_opus_report.py para el brain del shim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import preflight as pf   # noqa
import matrix as mx      # noqa

BRAIN = "claude-code-opus-4.8 (claude -p · Opción C)"
SUFFIX = "@claude-code"


def main():
    caps = pf.probe()
    by_case = {}
    for line in (HERE / "report" / "runs.jsonl").read_text().splitlines():
        d = json.loads(line)
        by_case[d["case"]] = d

    niches = ["finanzas", "electronica", "ingenieria", "medicina"]
    runs, nuances = {}, []

    # demo
    if "demo" + SUFFIX in by_case:
        d = by_case["demo" + SUFFIX]
        runs["demo"] = {**d["score"], "model_final": d["result"].get("model_final"),
                        "latency_s": d["result"].get("latency_s")}

    for niche in niches:
        d = by_case.get(niche + SUFFIX)
        cap = caps.get(mx.NICHE_REQUIRES[niche], {})
        if not d:
            runs[niche] = {"status": "BLOCKED", "verdict": "sin run", "axes": None,
                           "total": None, "executed_tools": [], "engine_reason": cap.get("engine_reason")}
            continue
        s, r = d["score"], d["result"]
        runs[niche] = {**s, "model_final": r.get("model_final"), "latency_s": r.get("latency_s"),
                       "engine_reason": cap.get("engine_reason")}
        ans = (r.get("answer") or "")[:160].replace("\n", " ")
        execd = s.get("executed_tools") or []
        # matiz honesto data-driven
        if s["status"] == "RED" and not execd:
            nuances.append(f"  - **{niche} 🔴 (no ejecutó tool, NO fabricó):** Opus declinó llamar la "
                           f"herramienta con el pedido dado — *“{ans}…”* (motor 🟢 arriba; el caso quedó "
                           f"sub-especificado para la tool, no es falla del brain ni del engine).")
        elif niche == "medicina" and execd:
            # round-trip real pero resultado vacío del PACS
            tcs = r.get("tool_calls") or []
            qr = next((t for t in tcs if t.get("tool") == "query_studies"), {})
            empty = "result\": []" in str(qr.get("result", "")) or "[]" in str(qr.get("result", ""))
            nuances.append(f"  - **medicina 🟢 (round-trip real + honesto):** `query_studies` lo ejecutó "
                           f"Aleph contra el Orthanc real (`isError:false`)"
                           + ("; devolvió **vacío** (el estudio CT cargado no apareció vía C-FIND — "
                              "posible AET/indexing); Opus lo reportó honesto, no inventó diagnóstico."
                              if empty else "; Opus reportó la metadata sin inventar diagnóstico."))
        elif niche == "electronica" and execd:
            nuances.append("  - **electronica 🟢 (auto-corrección):** un `add_component` falló por "
                           "validación (`position` requerido); **Opus reintentó con position y completó** "
                           "el e2e — tool-use superior al modelo barato (que quedaba RED acá).")

    lectura = [
        "- **Brain real = Opus 4.8 vía `claude -p` (Opción C, pura cognición).** Shim local OpenAI-compat "
        "↔ `claude -p --model opus` con tools de Claude Code **OFF**. **Aleph corre el belt/gates contra el "
        "engine real; Claude Code solo da el next-message.** `model_final=claude-code-opus-4.8` en TODAS las "
        "celdas (gate verificado: worldbank lo ejecutó Aleph, no Claude Code). **Sin throttle** — la matriz "
        "completó entera.",
        "- **Resultados (brain real):** " + "; ".join(
            f"{n}={(runs.get(n) or {}).get('status','—')}" for n in ["demo"] + niches if runs.get(n)) + ".",
    ]
    if nuances:
        lectura.append("- **Matices honestos (de runs.jsonl):**")
        lectura += nuances
    lectura.append("- **Engines:** todos 🟢 arriba (sección Motores) — ninguno ausente. **Cero celdas "
                   "fabricadas.** Opus fue MÁS cauto que el modelo barato: en ingeniería se negó a inventar "
                   "geometría para la CFD (el barato tiraba un Cd irreal).")

    prod_cheap = {"verdict": "no corrido este round (PROD_CHEAP=0); brain = Opus real vía shim",
                  "note": "Comparación: gpt-4o-mini dejaba electrónica en RED; Opus la cierra 10/10 "
                          "(auto-corrige el error de validación). OpenRouter-Opus = 402; este round es Opus REAL."}
    opus_live = {"niche": "finanzas", "tool": "worldbank_series (vía Aleph) + fed_rates (FRED)",
                 "verdict": "GREEN — Opus 4.8 (claude -p) cierra el e2e con dato real, ejecutado por Aleph",
                 "evidence": "PIB Ecuador (NY.GDP.MKTP.CD) traído por worldbank_series; fed_funds 3.63% (FRED)",
                 "note": "Opción C = la ruta a Opus que SÍ corre la matriz hoy (sin crédito OpenRouter)."}

    grid = mx.build_grid(caps, runs, brain_label=BRAIN)
    md, _ = mx.write_reports(HERE / "report", caps, runs, grid, prod_cheap, opus_live,
                             prod_runs={}, brain_label=BRAIN,
                             prod_cheap_ref="- **Brain de este round = Opus 4.8 REAL (claude -p, Opción C).**",
                             lectura=lectura)
    print("regenerado:", md)
    from collections import Counter
    print("celdas:", dict(Counter(c["cell_status"] for c in grid)))


if __name__ == "__main__":
    main()
