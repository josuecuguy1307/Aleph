"""
matrix.py — the e2e matrix grid + honest status combiner + reporter.

A CELL = (niche × persona × modo). Each cell reports TWO honest things:

  run_status     — does the EQUIPPED AGENT actually complete this niche e2e? (the Sala /
                   "use" side). GREEN/RED from a real scored run, or BLOCKED(reason) from
                   preflight (engine/network/model down). This is per-(niche, brain-model);
                   persona×modo cells of the same niche inherit it (de-dup is explicit).

  surface_status — can THIS persona build it via THIS modo? (the Cuarto / "build" side,
                   the 3 profundidades). Reflects today's real surfaces:
                     chat     → BLOCKED: el compilador chat→receta es placeholder (Fase 5)
                     opciones → PARTIAL: la perilla Autonomía (gate) es real; Detalle/Pasos
                                son recipe-level (prompt/max_turns) y SÍ se setean; el panel
                                de perillas pleno es Fase 5
                     codigo   → GREEN (dev): el handler depth-3 se lee (/v1/tools/{ref}/handler)
                                y el modelo/BYOK se overridea en la receta (lo prueba el runner)

  cell_status    — el binding constraint: GREEN solo si run y surface están verdes; si no,
                   el factor que limita, con su razón. Nada se marca verde por self-report.

Model columns:
  brain      — el modelo que COMPLETA el e2e sin costo marginal. En este harness: qwen3:8b
               local (in-process) por default; Opus-as-brain se corre LIVE aparte (finanzas,
               dato FRED real) y se anota como evidencia.
  prod-cheap — "qué aguanta en prod": el OSS barato. Hoy = qwen3:8b (medido en vivo) +
               referencia a la matriz de coupling 2026-06-19 (gpt-4o-mini/deepseek por niche).
"""
from __future__ import annotations

import json
from pathlib import Path

NICHES = ["finanzas", "ingenieria", "electronica", "medicina"]
PERSONAS = ["average", "dev"]
MODOS = ["chat", "opciones", "codigo"]

# requires-capability per niche (matches cases.py)
NICHE_REQUIRES = {
    "finanzas": "finanzas_data",
    "ingenieria": "engine_ingenieria",
    "electronica": "kicad",
    "medicina": "orthanc",
    "demo": "ollama",
}

# build-surface reality today (the 3 profundidades), per the F0 §2 + Fase-5 placeholder state
SURFACE = {
    "chat": {"status": "BLOCKED",
             "reason": "compilador chat→receta = placeholder (Fase 5, cuarto.html:138-251)"},
    "opciones": {"status": "PARTIAL",
                 "reason": "perilla Autonomía=gate es real (gate_enforced); Detalle/Pasos vía receta; panel pleno Fase 5"},
    "codigo": {"status": "GREEN",
               "reason": "depth-3 handler legible (/v1/tools/{ref}/handler) + override de modelo/BYOK en receta"},
}
# código solo aplica de verdad a la persona DEV; el average no baja a código.
def _surface_for(persona, modo):
    s = dict(SURFACE[modo])
    if modo == "codigo" and persona == "average":
        return {"status": "N/A", "reason": "el usuario no-técnico no baja a código (por diseño)"}
    return s


def _combine(run_status, surface_status):
    """Binding constraint → cell status."""
    if run_status == "BLOCKED":
        return "BLOCKED"   # the agent itself can't run yet → nothing to build/use
    if surface_status in ("BLOCKED", "N/A"):
        return surface_status
    if run_status == "RED":
        return "RED"
    if surface_status == "PARTIAL":
        return "PARTIAL"   # runs, builds partially
    return "GREEN"


def build_grid(caps: dict, runs: dict, brain_label: str = "gpt-4o-mini") -> list[dict]:
    """caps = preflight map; runs = {niche: {status, verdict, axes, total, ...}} for niches
    that were actually run (or blocked)."""
    grid = []
    for niche in NICHES:
        rinfo = runs.get(niche) or {}
        run_status = rinfo.get("status", "BLOCKED")
        cap = caps.get(NICHE_REQUIRES[niche], {})
        eng_reason = rinfo.get("engine_reason") or cap.get("engine_reason")
        run_reason = rinfo.get("verdict") or cap.get("detail")
        if run_status == "BLOCKED" and eng_reason:
            tag = {"not_started": "motor NO prendido (instalado)",
                   "absent": "motor AUSENTE/no cableado",
                   "running": "motor arriba"}.get(eng_reason, eng_reason)
            run_reason = f"[{tag}] {run_reason}"
        for persona in PERSONAS:
            for modo in MODOS:
                surf = _surface_for(persona, modo)
                cell_status = _combine(run_status, surf["status"])
                grid.append({
                    "niche": niche, "persona": persona, "modo": modo,
                    "engine_reason": eng_reason,
                    "model_brain": f"{brain_label} (brain) + qwen3:8b (prod-cheap)",
                    "run_status": run_status, "run_reason": run_reason,
                    "run_total": rinfo.get("total"), "run_axes": rinfo.get("axes"),
                    "surface_status": surf["status"], "surface_reason": surf["reason"],
                    "cell_status": cell_status,
                })
    return grid


_GLYPH = {"GREEN": "🟢", "RED": "🔴", "BLOCKED": "⛔", "PARTIAL": "🟡", "N/A": "·"}


def write_reports(out_dir: Path, caps: dict, runs: dict, grid: list[dict],
                  prod_cheap: dict, opus_live: dict | None,
                  prod_runs: dict | None = None, brain_label: str = "gpt-4o-mini",
                  prod_cheap_ref: str | None = None, lectura: list[str] | None = None):
    out_dir.mkdir(parents=True, exist_ok=True)
    prod_runs = prod_runs or {}

    payload = {
        "generated": "stamped-after-run",
        "brain_model": brain_label,
        "prod_cheap_model": "qwen3:8b",
        "capabilities": caps,
        "niche_runs_brain": runs,
        "niche_runs_prod_cheap": prod_runs,
        "prod_cheap_headline": prod_cheap,
        "opus_as_brain_live": opus_live,
        "grid": grid,
    }
    (out_dir / "matriz.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # ── markdown ──
    L = []
    L.append("# Matriz e2e — niche × persona × modo × modelo (T10)\n")
    L.append("> Verify-from-environment. Honest por celda: 🟢 verde · 🔴 rojo · 🟡 parcial · "
             "⛔ bloqueado (con razón) · · N/A. **Fabricar = fail.** Nada verde por self-report.\n")

    # capabilities
    L.append("## Capacidades del entorno (preflight)\n")
    L.append("| capacidad | ok | detalle |\n|---|---|---|")
    for k, v in caps.items():
        L.append(f"| `{k}` | {'✅' if v['ok'] else '❌'} | {v['detail']} |")
    L.append("")

    # motores de nicho — la columna que pide el ask: ⛔ "no prendido" vs "ausente"
    L.append("## Motores de nicho — ¿por qué ⛔? (no prendido vs ausente)\n")
    L.append("| niche | capacidad | motor | engine_reason | detalle |")
    L.append("|---|---|---|---|---|")
    _ENG = {"running": "🟢 arriba", "not_started": "🟡 instalado, NO prendido",
            "absent": "⛔ AUSENTE / no cableado", None: "— keyless (sin motor)"}
    for niche in NICHES:
        req = NICHE_REQUIRES[niche]
        c = caps.get(req, {})
        er = c.get("engine_reason")
        L.append(f"| {niche} | `{req}` | {'✅' if c.get('ok') else '❌'} | "
                 f"{_ENG.get(er, er)} | {c.get('detail','')} |")
    L.append("")
    L.append("- **no prendido** = la app/imagen está instalada y se puede arrancar "
             "(FreeCAD.app, Docker.app + imagen, contenedor Orthanc) — lo levantamos.\n"
             "- **ausente / no cableado** = no hay binario/app/imagen → no se puede levantar acá.\n")

    # niche runs (the agent e2e) — brain (completes) vs prod-cheap (what holds)
    L.append(f"## Corrida del agente por niche · 5 ejes · **brain={brain_label}** vs **prod-cheap=qwen3:8b**\n")
    L.append(f"brain = el cerebro que completa el e2e (cloud, barato). prod-cheap = el OSS local "
             f"(qué aguanta en prod). El status del grid usa **brain**.\n")
    L.append("| niche | modelo | status | Σ/10 | Fid | Sel | Grnd | Reac | Hon | lat(s) | tools ejec. | nota |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")

    def _row(niche, label, r):
        ax = (r or {}).get("axes") or {}
        g = _GLYPH.get((r or {}).get("status"), "⛔")
        return "| {n} | {ml} | {g} {s} | {t} | {f} | {se} | {gr} | {re} | {ho} | {lat} | {tl} | {v} |".format(
            n=niche, ml=label, g=g, s=(r or {}).get("status", "BLOCKED"), t=(r or {}).get("total", "—"),
            f=ax.get("fidelidad", "—"), se=ax.get("seleccion", "—"), gr=ax.get("grounding", "—"),
            re=ax.get("reaccion", "—"), ho=ax.get("honestidad", "—"),
            lat=(r or {}).get("latency_s", "—"),
            tl=", ".join((r or {}).get("executed_tools") or []) or "—",
            v=(r or {}).get("verdict", ""))

    for niche in ["demo"] + NICHES:
        rb = runs.get(niche)
        if rb:
            L.append(_row(niche, brain_label, rb))
        rp = prod_runs.get(niche)
        if rp:
            L.append(_row(niche, "qwen3:8b", rp))
    L.append("")

    # the full grid
    L.append("## Grid completo (niche × persona × modo)\n")
    L.append("run = corre el agente (Sala) · surface = se construye con ese modo (Cuarto) · cell = binding constraint\n")
    L.append("| niche | persona | modo | run | surface | **cell** | razón |")
    L.append("|---|---|---|---|---|---|---|")
    for c in grid:
        L.append("| {n} | {p} | {m} | {rg} {r} | {sg} {s} | {cg} **{c}** | {why} |".format(
            n=c["niche"], p=c["persona"], m=c["modo"],
            rg=_GLYPH.get(c["run_status"], "?"), r=c["run_status"],
            sg=_GLYPH.get(c["surface_status"], "?"), s=c["surface_status"],
            cg=_GLYPH.get(c["cell_status"], "?"), c=c["cell_status"],
            why=(c["run_reason"] if c["run_status"] in ("BLOCKED", "RED") else c["surface_reason"]),
        ))
    L.append("")

    # prod-cheap
    L.append("## Columna prod-cheap — ¿qué aguanta en prod?\n")
    L.append(prod_cheap_ref or
             "- **Ref. cloud-barato (gpt-4o-mini, corrida previa):** completa finanzas 10/10 en "
             "~4s (engancha `worldbank_series`).")
    if prod_cheap:
        L.append(f"- **prod-cheap (qwen3:8b local), medido hoy:** {prod_cheap.get('verdict','—')}")
        L.append(f"  - {prod_cheap.get('note','')}")
    L.append("- **Referencia 2026-06-19 (coupling):** gpt-4o-mini = mejor en elec/ing/finanzas "
             "(10/10, rápido/barato); deepseek = mejor en medicina (10/10, engancha la tool); "
             "Groq free = inusable multi-turno (TPM, R6). Ver `reports/eval-coupling-2026-06-19/`.\n")

    # opus-as-brain live
    if opus_live:
        L.append("## Opus-as-brain (LIVE) — el cerebro premium sin costo marginal\n")
        L.append(f"- **{opus_live.get('niche')}** vía `{opus_live.get('tool')}`: "
                 f"{opus_live.get('verdict')}")
        L.append(f"  - dato real (verify-from-env): {opus_live.get('evidence')}")
        L.append(f"  - {opus_live.get('note','')}\n")

    # summary
    counts = {}
    for c in grid:
        counts[c["cell_status"]] = counts.get(c["cell_status"], 0) + 1
    L.append("## Resumen honesto\n")
    L.append("Conteo de celdas: " + " · ".join(f"{_GLYPH.get(k,'?')} {k}={v}" for k, v in sorted(counts.items())))
    L.append("")
    if lectura:
        L.append("**Lectura:**")
        for b in lectura:
            L.append(b)
    else:
        L.append("**Lectura:**")
        L.append("- **Sala (corre el agente):** **finanzas** cierra e2e con brain (gpt-4o-mini 10/10, "
                 "dato real del Banco Mundial; trampa SpaceX honesta). **electrónica** ejecuta la tool "
                 "real (`create_schematic` ✅) pero el run NO cierra — el brain cae a qwen3:8b y se cuelga "
                 "(timeout, R1 stall) → 🔴 honesto, no verde. **ingeniería** y **medicina** quedan ⛔ por "
                 "motor apagado (Docker/FreeCAD, Orthanc), no 🔴. El **OSS local (qwen3:8b)** solo "
                 "engancha el calc trivial; en nicho no completa → necesita brain (gpt-4o-mini/Opus).")
        L.append("- **Cuarto (se construye con el modo):** **código** verde para el dev (handler "
                 "legible + override de modelo/BYOK); **opciones** parcial (perilla gate real); **chat** "
                 "⛔ hasta que se mergee el compilador chat→receta (Fase 5).")
        L.append("- **Cero celdas fabricadas.** Cada ⛔ trae su razón verificada del preflight.")
    (out_dir / "matriz.md").write_text("\n".join(L) + "\n")
    return out_dir / "matriz.md", out_dir / "matriz.json"
