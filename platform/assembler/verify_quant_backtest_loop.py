#!/usr/bin/env python3
"""
verify_quant_backtest_loop.py — verificación REAL del loop de optimización de cartera (Quant).

  L1 · DATO REAL (runtime MCPServer)
      Arranca backtest_server.py con el MISMO cliente MCP que usa :8080 y llama
      backtest_portfolio (yfinance real). Imprime el Sharpe CRUDO de una cartera
      concentrada (bajo) y una diversificada (alto) — el número sale del backtest, no de memoria.

  L2 · EL LOOP POR OPUS (assemble_and_run + brain shim :8923)
      El puppet de Quant corre por el path de PROD con el cerebro Opus real. Arranca con
      una cartera concentrada (Sharpe bajo) → el agente DECIDE la reasignación de pesos él
      mismo (diversificar para bajar la vol) → converge a Sharpe ≥ objetivo en ≤4 iteraciones.
      model_final=claude-code-opus-4.8 / degraded=null. tool_calls > 0 (NO un Sharpe inventado).

  L3 · CONVERGENCIA (executor) — _capture_rich_obra surfacea convergence.json (La Sala la
      rinde como UNA convergencia 1D: el Sharpe SUBIENDO y la curva de equity redibujándose).

Uso (desde el worktree):
  product/backend/.venv/bin/python platform/assembler/verify_quant_backtest_loop.py
  (o cualquier python con las deps del backend; el shim :8923 debe estar vivo)
"""
import os
import sys
import json
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

_BELT = _REPO / "catalog" / "templates" / "finanzas" / "belt-finanzas-markets.mcp.json"
_FRAMING = _REPO / "catalog" / "templates" / "finanzas" / "framing-backtest-loop.md"
_TICKERS = ["SPY", "QQQ", "NVDA", "TLT", "GLD"]
_TARGET = 1.2

_results = []


def check(label, cond, detail=""):
    _results.append((bool(cond), label, detail))
    print(f"  [{'VERDE' if cond else 'ROJO '}] {label}" + (f" — {detail}" if detail else ""))


def _mk_backtest(workdir):
    belt = json.loads(_BELT.read_text(encoding="utf-8"))
    scfg = belt["mcpServers"]["backtest"]
    env = dict(os.environ)
    env["PUPPET_WORKDIR"] = workdir
    env["PUPPET_BELTS"] = str(_REPO / "product" / "belts")
    command = scfg["command"]
    args = [a.replace("${PUPPET_BELTS}", env["PUPPET_BELTS"]) for a in scfg.get("args", [])]
    return MCPServer("backtest", command, args, env=env)


# ════════════════════════════════════════════════════════════════════════════
def level1_real():
    print("\n=== L1 · DATO REAL: backtest con precios de yfinance (runtime MCPServer) ===")
    workdir = tempfile.mkdtemp(prefix="verify-bt-")
    srv = _mk_backtest(workdir)
    if not srv.start():
        check("S1 initialize handshake", False, "el server backtest no inicializó")
        return
    check("S1 initialize handshake", True)
    tools = [t.get("name") for t in srv.list_tools()]
    check("S2 tools/list expone backtest_portfolio", "backtest_portfolio" in tools, f"tools={tools}")

    # cartera CONCENTRADA en tech (alta vol → Sharpe bajo)
    lo = json.loads(srv.call_tool("backtest_portfolio", {
        "tickers": _TICKERS, "weights": [0, 0.40, 0.60, 0, 0],
        "task_id": "L1", "lookback_years": 2, "target_sharpe": _TARGET}))
    print("\n  ── DATO CRUDO backtest(60% NVDA / 40% QQQ) ──")
    for k in ("sharpe", "ann_return_pct", "ann_vol_pct", "max_drawdown_pct", "n_trading_days", "verdict"):
        print(f"     {k:18}= {lo.get(k)}")
    check("S3 backtest concentrado → Sharpe REAL bajo (FALLA <1.2, datos reales)",
          lo.get("ok") and lo.get("sharpe") is not None and lo["sharpe"] < _TARGET
          and lo.get("n_trading_days", 0) > 200,
          f"Sharpe={lo.get('sharpe')} · vol={lo.get('ann_vol_pct')}% · {lo.get('n_trading_days')} días")

    # cartera DIVERSIFICADA (menor vol → Sharpe alto)
    hi = json.loads(srv.call_tool("backtest_portfolio", {
        "tickers": _TICKERS, "weights": [0.15, 0.15, 0.10, 0.30, 0.30],
        "task_id": "L1", "lookback_years": 2, "target_sharpe": _TARGET}))
    print("\n  ── DATO CRUDO backtest(diversificada 15/15/10/30/30) ──")
    for k in ("sharpe", "ann_return_pct", "ann_vol_pct", "max_drawdown_pct", "verdict"):
        print(f"     {k:18}= {hi.get(k)}")
    check("S4 diversificar SUBE el Sharpe (vol baja) → PASA ≥1.2",
          hi.get("ok") and hi.get("sharpe", 0) >= _TARGET and hi.get("ann_vol_pct", 99) < lo.get("ann_vol_pct", 0),
          f"Sharpe {lo.get('sharpe')}→{hi.get('sharpe')} · vol {lo.get('ann_vol_pct')}%→{hi.get('ann_vol_pct')}%")
    srv.stop()


# ════════════════════════════════════════════════════════════════════════════
def _recipe():
    return {
        "schema_version": "v1",
        "meta": {"name": "Quant", "nicho": "finanzas",
                 "descripcion": "Optimiza carteras: backtest real + Sharpe, iterando hasta converger."},
        "belt": {
            "belt_ref": "catalog/templates/finanzas/belt-finanzas-markets.mcp.json",
            "tool_filters": {"backtest": ["backtest_portfolio"]},
        },
        "keys": {},
        "gates": {"send": "needs_ok", "money_touch": "needs_ok"},
        "model": {"alias": "brain", "max_turns": 16, "max_tokens": 2800, "temperature": 0},
        "framing": {"inline": _FRAMING.read_text(encoding="utf-8")},
        "rag": {"enabled": False},
    }


PROMPT = ("Optimizá la cartera para maximizar el Sharpe ratio, iterando vos solo: corré el "
          "backtest, leé el Sharpe real, reasigná los pesos razonando y volvé a correr hasta "
          "llegar a Sharpe ≥ 1.2 (o 4 iteraciones). Cerrá con el veredicto: pesos finales y Sharpe.")


def _args_of(c):
    a = c.get("args", {})
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except Exception:
            a = {}
    return a or {}


def _res_of(c):
    r = c.get("result", "")
    try:
        return json.loads(r) if isinstance(r, str) else (r or {})
    except Exception:
        return {}


def level2_opus_loop():
    print("\n=== L2 · EL LOOP POR OPUS (assemble_and_run + brain shim :8923) ===")
    workdir = tempfile.mkdtemp(prefix="verify-bt-e2e-")
    rec = ra.assemble_and_run(_recipe(), PROMPT, repo_root=_REPO, deadline_s=400.0, workdir=workdir)
    model_final = rec.get("model_final")
    degraded = rec.get("degraded")
    tool_calls = rec.get("tool_calls", []) or []
    bts = [c for c in tool_calls if c.get("tool") == "backtest_portfolio"]

    print(f"\n  model_final = {model_final}")
    print(f"  degraded    = {degraded}")
    print(f"  tool_calls  = {[c.get('tool') for c in tool_calls]}")
    print(f"\n  ── RAZONAMIENTO DE OPUS por iteración (eligió los pesos SOLO) ──")
    sharpes = []
    for i, c in enumerate(bts, 1):
        a = _args_of(c)
        rj = _res_of(c)
        if rj.get("sharpe") is not None:
            sharpes.append(rj.get("sharpe"))
        w = a.get("weights")
        print(f"   it.{i}: weights={w} → Sharpe={rj.get('sharpe')} "
              f"vol={rj.get('ann_vol_pct')}% ret={rj.get('ann_return_pct')}% verdict={rj.get('verdict')}")
    print("\n  ── RESPUESTA / VEREDICTO del agente (su razonamiento) ──")
    print("   " + (rec.get("answer", "") or "").replace("\n", "\n   ")[:1800])

    conv_path = Path(workdir) / "convergence.json"
    conv = json.loads(conv_path.read_text()) if conv_path.exists() else None
    iters = (conv or {}).get("iterations", [])
    vals = [it.get("value") for it in iters]
    first_s = vals[0] if vals else None
    last_s = vals[-1] if vals else None

    # tool EJECUTADA, con resultado real (anti-Sharpe-fabricado)
    executed = [c for c in bts if _res_of(c).get("ok") and _res_of(c).get("sharpe") is not None]
    check("E1 el run terminó OK", rec.get("ok"), rec.get("error") or "")
    check("E2 el agente EJECUTÓ backtest_portfolio ≥2 veces (loop real, Sharpe NO fabricado)",
          len(executed) >= 2, f"{len(executed)} backtests con resultado real")
    check("E3 arrancó con Sharpe bajo (it.1 < 1.2)",
          bool(vals) and first_s is not None and first_s < _TARGET, f"it.1 Sharpe={first_s}")
    check("E4 convergió a Sharpe ≥1.2 en ≤4 iteraciones (y SUBIÓ vs it.1)",
          bool(vals) and len(iters) <= 4 and last_s is not None and last_s >= _TARGET and last_s > first_s,
          f"{len(iters)} iters, Sharpe {first_s}→{last_s}")
    check("E5 model_final = claude-code-opus-4.8", model_final == "claude-code-opus-4.8", str(model_final))
    check("E6 degraded = null (Opus real, sin fallback)", degraded is None, str(degraded))
    return workdir


# ════════════════════════════════════════════════════════════════════════════
def level3_capture(workdir):
    print("\n=== L3 · CONVERGENCIA capturada por el executor (La Sala la rinde) ===")
    if not workdir:
        check("C1 _capture_rich_obra → convergence", False, "no hubo workdir del L2")
        return
    sys.path.insert(0, str(_REPO / "product" / "backend"))
    from app.phase1.executor import _capture_rich_obra
    obra = _capture_rich_obra(workdir)
    vals = [it.get("value") for it in (obra or {}).get("iterations", [])]
    has_curve = bool(obra and obra.get("iterations") and obra["iterations"][0].get("curve"))
    goal_max = bool(obra and obra.get("metric", {}).get("goal") == "max")
    rising = bool(len(vals) >= 2 and vals[-1] > vals[0])
    ok = bool(obra and obra.get("type") == "convergence"
              and isinstance(obra.get("iterations"), list) and len(obra["iterations"]) >= 2)
    check("C1 _capture_rich_obra → obra convergence (Sharpe subiendo, curva de equity)",
          ok and goal_max and has_curve and rising,
          f"iters={len(vals)} Sharpe/it={vals} goal=max:{goal_max} curve:{has_curve}")
    # persistir la obra para la verificación visual del display (Playwright)
    try:
        outp = Path(tempfile.gettempdir()) / "quant_convergence_obra.json"
        outp.write_text(json.dumps(obra, ensure_ascii=False))
        print(f"\n  obra de convergencia escrita en {outp} (para el render de La Sala)")
    except Exception:
        pass


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
    print("Loop Quant verificado: backtest yfinance real + loop Opus autónomo (reasigna pesos) + convergencia del Sharpe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
