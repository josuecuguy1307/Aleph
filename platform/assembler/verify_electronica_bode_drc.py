#!/usr/bin/env python3
"""
verify_electronica_bode_drc.py — verificación REAL del simulador Bode + DRC (1B-2).

  L1 · DATO REAL (runtime MCPServer)
      Arranca spice_server.py con el MISMO cliente MCP que usa :8080 y llama ac_sweep
      (ngspice headless) + build_filter_schematic + run_erc (kicad-cli headless).
      Imprime el -3dB MEDIDO crudo y demuestra el DRC de N errores → 0.

  L2 · EL LOOP POR OPUS (assemble_and_run + brain shim :8923)
      El puppet de electrónica corre por el path de PROD con el cerebro Opus real.
      Arranca FUERA de spec → el agente DECIDE el cambio de R él mismo (f_c=1/(2πRC))
      → converge a EN SPEC en ≤4 iteraciones. model_final=claude-code-opus-4.8 / null.

  L3 · CONVERGENCIA (executor) — _capture_rich_obra surfacea convergence.json (La Sala
      la rinde como UNA convergencia 1D: la curva deslizándose al target).

Uso:  product/backend/.venv/bin/python platform/assembler/verify_electronica_bode_drc.py
"""
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
os.environ["PUPPET_BRAIN_SHIM"] = "1"
os.environ["PUPPET_BRAIN_SHIM_MODEL"] = "claude-code-opus-4.8"
os.environ.setdefault("PUPPET_BELTS", str(_REPO / "product" / "belts"))

sys.path.insert(0, str(_HERE))
from assembler import MCPServer                      # noqa: E402
import recipe_assembler as ra                        # noqa: E402

_BELT = _REPO / "catalog" / "templates" / "electronica" / "belt-electronica.mcp.json"
_FRAMING = _REPO / "catalog" / "templates" / "electronica" / "framing-bode-loop.md"

_results = []


def check(label, cond, detail=""):
    _results.append((bool(cond), label, detail))
    print(f"  [{'VERDE' if cond else 'ROJO '}] {label}" + (f" — {detail}" if detail else ""))


def _mk_spice(workdir):
    import json
    belt = json.loads(_BELT.read_text(encoding="utf-8"))
    scfg = belt["mcpServers"]["spice"]
    env = dict(os.environ)
    env["PUPPET_WORKDIR"] = workdir
    env["PUPPET_BELTS"] = str(_REPO / "product" / "belts")
    command = scfg["command"]
    args = [a.replace("${PUPPET_BELTS}", env["PUPPET_BELTS"]) for a in scfg.get("args", [])]
    return MCPServer("spice", command, args, env=env)


# ════════════════════════════════════════════════════════════════════════════
def level1_real():
    import json
    print("\n=== L1 · DATO REAL: ngspice AC sweep + kicad-cli ERC (runtime MCPServer) ===")
    workdir = tempfile.mkdtemp(prefix="verify-spice-")
    srv = _mk_spice(workdir)
    if not srv.start():
        check("S1 initialize handshake", False, "el server spice no inicializó")
        return
    check("S1 initialize handshake", True)
    tools = [t.get("name") for t in srv.list_tools()]
    check("S2 tools/list expone ac_sweep + build_filter_schematic + run_erc",
          {"ac_sweep", "build_filter_schematic", "run_erc"}.issubset(set(tools)), f"tools={tools}")

    # AC sweep de un filtro CONCRETO y NOMBRADO: RC lowpass R=10k C=100n (f_c teórico 159.15 Hz)
    raw = srv.call_tool("ac_sweep", {"filter_type": "rc_lowpass", "R_ohms": 10000,
                                     "C_farads": 100e-9, "target_fc_hz": 1000})
    d = json.loads(raw)
    print("\n  ── DATO CRUDO ac_sweep(rc_lowpass, R=10k, C=100n) ──")
    for k in ("theoretical_fc_hz", "measured_f3db_hz", "passband_db",
              "mag_db_at_target", "attenuation_at_target_db", "in_spec", "points"):
        print(f"     {k:24}= {d.get(k)}")
    fc = d.get("measured_f3db_hz")
    real_ok = (d.get("ok") and fc and abs(fc - 159.15) / 159.15 < 0.05
               and d.get("attenuation_at_target_db", 0) > 10 and d.get("in_spec") is False)
    check("S3 ac_sweep → -3dB REAL (≈159 Hz, ngspice)", real_ok,
          f"medido={fc} Hz vs teórico 159.15 Hz · att@1kHz={d.get('attenuation_at_target_db')} dB")

    # DRC N→0: esquemático con pines flotantes (errores) → cableado (0 errores)
    srv.call_tool("build_filter_schematic", {"R_ohms": 1600, "C_farads": 100e-9,
                                             "name": "drc_floating", "connect": False})
    erc_bad = json.loads(srv.call_tool("run_erc", {"schematic": "drc_floating"}))
    srv.call_tool("build_filter_schematic", {"R_ohms": 1600, "C_farads": 100e-9,
                                             "name": "drc_wired", "connect": True})
    erc_ok = json.loads(srv.call_tool("run_erc", {"schematic": "drc_wired"}))
    n_bad = erc_bad.get("error_count")
    n_ok = erc_ok.get("error_count")
    print(f"\n  ── DRC REAL (kicad-cli) ──  flotante: {n_bad} errores → cableado: {n_ok} errores")
    print("     violaciones (flotante):", [v["type"] for v in erc_bad.get("violations", [])])
    check("S4 DRC de N errores → 0 (kicad-cli real)",
          (n_bad and n_bad > 0 and n_ok == 0), f"{n_bad} → {n_ok}")
    srv.stop()


# ════════════════════════════════════════════════════════════════════════════
def _recipe():
    return {
        "schema_version": "v1",
        "meta": {"name": "Agente de Electrónica", "nicho": "electronica",
                 "descripcion": "Diseña y simula filtros (Bode) + DRC."},
        "belt": {
            "belt_ref": "catalog/templates/electronica/belt-electronica.mcp.json",
            "tool_filters": {"spice": ["ac_sweep", "build_filter_schematic", "run_erc"]},
        },
        "keys": {},
        "gates": {"send": "needs_ok", "money_touch": "needs_ok"},
        "model": {"alias": "brain", "max_turns": 14, "max_tokens": 2600, "temperature": 0},
        "framing": {"inline": _FRAMING.read_text(encoding="utf-8")},
        "rag": {"enabled": False},
    }


PROMPT = ("Diseñá el filtro RC pasa-bajos para la spec (dejar pasar 1000 Hz con ≤3 dB), "
          "iterando vos solo: simulá, leé el -3 dB real, ajustá R y re-simulá hasta cumplir. "
          "Después construí el esquemático y corré el DRC. Cerrá con el veredicto.")


def level2_opus_loop():
    import json
    print("\n=== L2 · EL LOOP POR OPUS (assemble_and_run + brain shim :8923) ===")
    workdir = tempfile.mkdtemp(prefix="verify-spice-e2e-")
    rec = ra.assemble_and_run(_recipe(), PROMPT, repo_root=_REPO, deadline_s=350.0, workdir=workdir)
    model_final = rec.get("model_final")
    degraded = rec.get("degraded")
    tool_calls = rec.get("tool_calls", []) or []
    sweeps = [c for c in tool_calls if c.get("tool") == "ac_sweep"]
    ercs = [c for c in tool_calls if c.get("tool") == "run_erc"]

    print(f"\n  model_final = {model_final}")
    print(f"  degraded    = {degraded}")
    print(f"  tool_calls  = {[c.get('tool') for c in tool_calls]}")
    print(f"\n  ── RAZONAMIENTO DE OPUS por iteración (prueba de que decidió SOLO) ──")
    for i, c in enumerate(sweeps, 1):
        args = c.get("args", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        res = c.get("result", "")
        try:
            rj = json.loads(res) if isinstance(res, str) else res
        except Exception:
            rj = {}
        note = args.get("iteration_note", "")
        print(f"   it.{i}: R={args.get('R_ohms')}Ω C={args.get('C_farads')}F → "
              f"-3dB medido={rj.get('measured_f3db_hz')}Hz att@1k={rj.get('attenuation_at_target_db')}dB "
              f"in_spec={rj.get('in_spec')}")
        if note:
            print(f"          «{note}»")
    print("\n  ── RESPUESTA / VEREDICTO del agente ──")
    print("   " + (rec.get("answer", "") or "").replace("\n", "\n   ")[:1600])

    # leer la convergencia para el veredicto in-spec final
    conv_path = Path(workdir) / "convergence.json"
    conv = json.loads(conv_path.read_text()) if conv_path.exists() else None
    iters = (conv or {}).get("iterations", [])
    last_att = iters[-1]["value"] if iters else None

    check("E1 el run terminó OK", rec.get("ok"), rec.get("error") or "")
    check("E2 el agente LLAMÓ ac_sweep varias veces (loop real, no 1 shot)", len(sweeps) >= 2,
          f"{len(sweeps)} barridos")
    check("E3 arrancó FUERA de spec (it.1 att@1k > 3 dB)",
          bool(iters) and iters[0]["value"] > 3.0, f"it.1 att={iters[0]['value'] if iters else None} dB")
    check("E4 convergió a EN SPEC en ≤4 iteraciones (att final ≤ 3 dB)",
          bool(iters) and len(iters) <= 4 and last_att is not None and last_att <= 3.0,
          f"{len(iters)} iters, att final={last_att} dB")
    check("E5 model_final = claude-code-opus-4.8", model_final == "claude-code-opus-4.8", str(model_final))
    check("E6 degraded = null (Opus real, sin fallback)", degraded is None, str(degraded))
    if ercs:
        last_erc = ercs[-1].get("result", "")
        try:
            ej = json.loads(last_erc) if isinstance(last_erc, str) else last_erc
            print(f"\n  DRC del agente: {ej.get('error_count')} errores (clean={ej.get('clean')})")
        except Exception:
            pass
    return workdir


# ════════════════════════════════════════════════════════════════════════════
def level3_capture(workdir):
    import json
    print("\n=== L3 · CONVERGENCIA capturada por el executor (La Sala la rinde) ===")
    if not workdir:
        check("C1 _capture_rich_obra → convergence", False, "no hubo workdir del L2")
        return
    sys.path.insert(0, str(_REPO / "product" / "backend"))
    from app.phase1.executor import _capture_rich_obra
    obra = _capture_rich_obra(workdir)
    ok = bool(obra and obra.get("type") == "convergence"
              and isinstance(obra.get("iterations"), list) and len(obra["iterations"]) >= 2)
    vals = [it.get("value") for it in (obra or {}).get("iterations", [])]
    has_grid = bool(obra and obra["iterations"] and obra["iterations"][0].get("grid"))
    check("C1 _capture_rich_obra → obra convergence (curva deslizándose al target)", ok and has_grid,
          f"iters={len(obra.get('iterations', [])) if obra else 0} att@1k por it={vals} grid={has_grid}")


def main():
    level1_real()
    wd = level2_opus_loop()
    level3_capture(wd)
    passed = sum(1 for ok, _, _ in _results if ok)
    total = len(_results)
    print(f"\n=== RESULTADO: {passed}/{total} VERDE ===")
    if passed != total:
        print("ROJO en:", [lbl for ok, lbl, _ in _results if not ok])
        return 1
    print("Simulador Bode + DRC verificado: ngspice real + loop Opus autónomo + DRC N→0 + convergencia.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
