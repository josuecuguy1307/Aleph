"""
honest_opus_report.py — reconstruye matriz.md/json para el re-run "con Opus 4.8" SIN
fingir nada, a partir de la evidencia real ya capturada (runs.jsonl, runs *@opus*).

Verdad verificada (2026-06-22):
  - Opus 4.8 SOLO está cableado vía OpenRouter (no hay Anthropic key en infra/.env).
  - OpenRouter free-tier devuelve **HTTP 402** en CUALQUIER llamada real de Opus
    ("requested up to N tokens, can only afford 20"). El probe de 20 tokens pasa; un run
    agéntico (>20 tok) NO.
  - Por eso el assembler cayó al safety-net OSS local: **model_final = qwen3:8b** en TODOS
    los runs @opus. Esos resultados son del fallback, NO de Opus → no se etiquetan como Opus.

Reporte honesto:
  - model:opus = ⛔ (402) → cada celda de niche = ⛔ a nivel MODELO (no de engine).
  - los ENGINES están todos 🟢 arriba (FreeCAD, Docker+openfoam, Orthanc) — la parte del
    ask sobre engines está cumplida; ninguno ausente, todos arrancados.
  - el fallback qwen3:8b se muestra aparte (qué completó / qué no), con su model_final real.
  - Opus-as-brain LIVE (esta sesión = Opus 4.8, costo marginal cero) sí cierra finanzas con
    dato real (FRED) — la única ruta a Opus que funciona hoy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import preflight as pf   # noqa
import matrix as mx      # noqa

OPUS_FAMILY = ("opus", "anthropic/claude-opus")
OPUS_402 = ("Opus 4.8 ⛔ no corrió: OpenRouter free-tier sin crédito (HTTP 402 en cualquier "
            "llamada real >20 tok); no hay Anthropic key → única ruta = OpenRouter")


def _is_opus(m):
    m = (m or "").lower()
    return any(t in m for t in OPUS_FAMILY)


def main():
    caps = pf.probe()

    # leer la evidencia real del último run @opus
    by_case = {}
    f = HERE / "report" / "runs.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            d = json.loads(line)
            by_case[d["case"]] = d

    niche_cases = {"finanzas": "finanzas@opus", "electronica": "electronica@opus",
                   "ingenieria": "ingenieria@opus", "medicina": "medicina@opus"}

    runs = {}        # columna "opus" — honesta: ⛔ 402 (no corrió Opus)
    fallback = {}    # columna real del fallback qwen3:8b

    # demo
    dd = by_case.get("demo@opus")
    if dd:
        runs["demo"] = {"status": "BLOCKED", "verdict": OPUS_402, "axes": None,
                        "total": None, "executed_tools": [], "latency_s": None}
        s, r = dd["score"], dd["result"]
        fallback["demo"] = {**s, "model_final": r.get("model_final"), "latency_s": r.get("latency_s")}

    for niche, case in niche_cases.items():
        cap = caps.get(mx.NICHE_REQUIRES[niche], {})
        runs[niche] = {"status": "BLOCKED", "verdict": OPUS_402,
                       "engine_reason": cap.get("engine_reason"),
                       "axes": None, "total": None, "executed_tools": [], "latency_s": None}
        d = by_case.get(case)
        if d:
            s, r = d["score"], d["result"]
            mf = r.get("model_final")
            # sanity: confirmá que NO fue Opus (si algún día hay crédito, esto cambia)
            note = "" if not _is_opus(mf) else " (¡corrió Opus!)"
            fallback[niche] = {**s, "model_final": mf, "latency_s": r.get("latency_s"),
                               "verdict": (s.get("verdict", "") + note)}

    prod_cheap = {
        "verdict": "fallback qwen3:8b (OSS local) — lo que el safety-net del assembler hizo cuando Opus 402'd",
        "note": "demo ✅ y electrónica ✅ (10/10, 145s) los completó el fallback; finanzas/ingeniería/"
                "medicina el fallback NO los completó (timeout, 0 tool-calls). Nada de esto es Opus.",
    }
    opus_live = {
        "niche": "finanzas",
        "tool": "feedoracle-macro · fed_rates (cloud, keyless, FRED)",
        "verdict": "GREEN — Opus 4.8 (esta sesión, costo marginal cero) SÍ cierra el e2e con dato real",
        "evidence": "fed_funds_rate = 3.63% (data_source: Federal Reserve / FRED), 2026-06-22",
        "note": "Única ruta a Opus que funciona hoy: el cerebro de la sesión (Claude Code), no la API "
                "(402). Cuando OpenRouter tenga crédito —o haya Anthropic key— el re-run automático con "
                "Opus es 1 línea (model='opus' ya cableado en isolated_runner).",
    }

    lectura = [
        "- **Modelo pedido (Opus 4.8): ⛔ 402.** OpenRouter free-tier no tiene crédito para una "
        "llamada real de Opus (puede pagar ~20 tok; un run agéntico pide >1000) y no hay Anthropic "
        "key en `infra/.env`. El assembler cae al safety-net OSS (`model_final=qwen3:8b`) → esos "
        "resultados **no son Opus** y no se cuentan como verde de Opus. **24/24 celdas ⛔ a nivel modelo.**",
        "- **Engines: TODOS 🟢 arriba — ninguno ausente.** Levanté Docker (openfoam/MP), FreeCAD "
        "(RPC :9875) y Orthanc PACS (con 1 estudio CT real). La clasificación pedida: **ningún ⛔ es "
        "'engine ausente'** — los que estaban ⛔ eran 'engine no prendido' (app/imagen instalada) y se "
        "arrancaron. El ⛔ de hoy es del **modelo**, no del engine.",
        "- **Qué hizo el fallback qwen3:8b (no es Opus):** completó demo (10/10) y **electrónica "
        "(10/10, e2e completo: create_schematic+add_component+list_components, 145s)**; NO completó "
        "finanzas/ingeniería/medicina (timeout, 0 tool-calls). Útil como piso OSS, no como Opus.",
        "- **Opus que SÍ corre hoy:** el cerebro de esta sesión (Claude Code = Opus 4.8), costo "
        "marginal cero — cerró finanzas con dato real FRED (fed_funds 3.63%). El re-run automático "
        "con Opus queda a 1 línea (`model='opus'` ya cableado) en cuanto haya crédito/Anthropic key.",
        "- **Cero celdas fabricadas.** Cada ⛔ trae su razón verificada (model:opus 402 + engine_reason).",
    ]
    prod_cheap_ref = ("- **Ref. cloud-barato (gpt-4o-mini, corrida previa con créditos):** completa "
                      "finanzas 10/10 en ~4s. Hoy gpt-4o-mini free-tier sigue ok; Opus no (402).")

    grid = mx.build_grid(caps, runs, brain_label="opus (402→fallback)")
    md, js = mx.write_reports(HERE / "report", caps, runs, grid, prod_cheap, opus_live,
                              prod_runs=fallback, brain_label="opus",
                              prod_cheap_ref=prod_cheap_ref, lectura=lectura)
    print("regenerado honesto:", md)
    # resumen
    from collections import Counter
    c = Counter(x["cell_status"] for x in grid)
    print("celdas:", dict(c))
    print("model:opus ok =", caps.get("model:opus", {}).get("ok"), "·", caps.get("model:opus", {}).get("detail"))


if __name__ == "__main__":
    main()
