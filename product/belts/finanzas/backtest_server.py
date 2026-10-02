#!/usr/bin/env python3
"""backtest_server.py — MCP stdio server: BACKTEST de cartera con datos REALES.

Tool `backtest_portfolio`: dada una cartera (pesos sobre un set de tickers), descarga
precios históricos REALES de Yahoo Finance (yfinance) y computa el Sharpe ratio anualizado
(+ retorno, volatilidad, max drawdown y la curva de equity). El número sale del backtest
real, nunca de memoria.

Patrón gemelo del FEM headless (product/belts/ingenieria/fem_server.py): JSON-RPC por stdin/
stdout, una tool de cómputo pesado, y ACUMULA cada llamada (mismo task_id/workdir) en
`convergence.json` dentro de ${PUPPET_WORKDIR} → el executor la surfacea como una obra
`convergence` y La Sala la rinde con el display 1D (it.1 → it.N, el Sharpe SUBIENDO y la
curva de equity redibujándose).

Spawned vía `uv run --with yfinance --with numpy` (el belt declara el command), así corre
en un entorno con yfinance+numpy sin tocar el venv del backend. yfinance se importa LAZY
(dentro de la tool) para que el server arranque rápido y responda initialize/tools/list al
toque; la descarga + cómputo ocurren solo en la llamada.

Simplificaciones honestas del backtest (las declara la tool): rebalanceo diario a los pesos
objetivo, tasa libre de riesgo = 0, BRUTO de costos de transacción y slippage. Es un punto
de partida para comparar carteras, no una validación de producción.
"""
import os
import sys
import json
import math

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "TLT", "GLD"]
_TRADING_DAYS = 252

# [i18n-bi] bilingüe server-side (PUPPET_LANG, default es; no-op hasta que el runtime lo
# setee). Mismo patrón que fem_server.py: lo que RENDERIZA La Sala (descripción de la tool,
# título/verdict de la convergencia, nota, errores honestos) sale en el idioma del usuario.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
BT_I18N = {
    "es": {
        "tool.desc": (
            "Corre un BACKTEST REAL de una cartera con precios históricos de Yahoo Finance "
            "(yfinance). Dado un set de tickers y sus pesos, descarga los cierres ajustados, "
            "calcula los retornos diarios de la cartera (rebalanceo diario a los pesos), y "
            "devuelve el Sharpe ratio anualizado, el retorno y la volatilidad anualizados, el "
            "max drawdown y la curva de equity. Úsalo para evaluar y OPTIMIZAR una cartera: "
            "corre, lee el Sharpe, reasigna pesos y vuelve a correr. Pasa SIEMPRE el mismo "
            "task_id en cada iteración (así La Sala agrupa el loop como una sola convergencia). "
            "Todo número sale del backtest real, nunca de memoria."
        ),
        "param.tickers": "Lista de tickers (ej. ['SPY','QQQ','NVDA','TLT','GLD']).",
        "param.weights": "Pesos por ticker, mismo orden y largo que tickers. Se normalizan a suma 1.",
        "param.task_id": "Id del loop de optimización. MISMO valor en todas las iteraciones para agrupar la convergencia.",
        "param.lookback": "Años de histórico para el backtest (default 2).",
        "param.target_sharpe": "Sharpe objetivo del loop (default 1.2). Marca PASA/FALLA y el límite del display.",
        "err.tickers_empty": "tickers debe ser una lista no vacía",
        "err.weights_len": "weights debe tener el mismo largo que tickers (%d)",
        "err.numpy": "numpy no disponible: %s",
        "err.weights_sum": "la suma de los pesos debe ser > 0",
        "err.yfinance": "yfinance no disponible: %s",
        "err.download": "fallo la descarga de yfinance: %s",
        "err.tickers_no_data": "tickers sin datos: %s",
        "err.parse_prices": "no pude parsear los precios: %s",
        "err.too_few": "muy pocos datos (%d filas) para un backtest",
        "conv.title": "Optimización de cartera — Sharpe ratio",
        "metric.name": "Sharpe ratio",
        "verdict.pass": "PASA", "verdict.fail": "FALLA",
        "note": ("Backtest real con precios de Yahoo Finance (yfinance). Rebalanceo diario a los "
                 "pesos, tasa libre de riesgo = 0, BRUTO de costos/slippage. La decisión de qué "
                 "pesos probar después es tuya."),
    },
    "en": {
        "tool.desc": (
            "Run a REAL portfolio BACKTEST with historical prices from Yahoo Finance "
            "(yfinance). Given a set of tickers and their weights, it downloads the adjusted "
            "closes, computes the portfolio's daily returns (daily rebalance to the weights), "
            "and returns the annualized Sharpe ratio, the annualized return and volatility, the "
            "max drawdown and the equity curve. Use it to evaluate and OPTIMIZE a portfolio: "
            "run, read the Sharpe, reassign weights and run again. ALWAYS pass the same task_id "
            "on each iteration (so The Room groups the loop as a single convergence). Every "
            "number comes from the real backtest, never from memory."
        ),
        "param.tickers": "List of tickers (e.g. ['SPY','QQQ','NVDA','TLT','GLD']).",
        "param.weights": "Weights per ticker, same order and length as tickers. Normalized to sum 1.",
        "param.task_id": "Optimization loop id. SAME value on every iteration to group the convergence.",
        "param.lookback": "Years of history for the backtest (default 2).",
        "param.target_sharpe": "Target Sharpe of the loop (default 1.2). Marks PASS/FAIL and the display limit.",
        "err.tickers_empty": "tickers must be a non-empty list",
        "err.weights_len": "weights must have the same length as tickers (%d)",
        "err.numpy": "numpy not available: %s",
        "err.weights_sum": "the sum of the weights must be > 0",
        "err.yfinance": "yfinance not available: %s",
        "err.download": "yfinance download failed: %s",
        "err.tickers_no_data": "tickers with no data: %s",
        "err.parse_prices": "could not parse the prices: %s",
        "err.too_few": "too little data (%d rows) for a backtest",
        "conv.title": "Portfolio optimization — Sharpe ratio",
        "metric.name": "Sharpe ratio",
        "verdict.pass": "PASS", "verdict.fail": "FAIL",
        "note": ("Real backtest with Yahoo Finance prices (yfinance). Daily rebalance to the "
                 "weights, risk-free rate = 0, GROSS of costs/slippage. Which weights to try "
                 "next is your call."),
    },
}


def _t(key):
    return BT_I18N.get(PUPPET_LANG, {}).get(key) or BT_I18N["es"].get(key) or key


TOOLS = [
    {
        "name": "backtest_portfolio",
        "description": _t("tool.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array", "items": {"type": "string"},
                    "description": _t("param.tickers"),
                },
                "weights": {
                    "type": "array", "items": {"type": "number"},
                    "description": _t("param.weights"),
                },
                "task_id": {
                    "type": "string",
                    "description": _t("param.task_id"),
                },
                "lookback_years": {
                    "type": "number",
                    "description": _t("param.lookback"),
                },
                "target_sharpe": {
                    "type": "number",
                    "description": _t("param.target_sharpe"),
                },
            },
            "required": ["tickers", "weights"],
        },
    },
]


def _run_backtest(args: dict) -> dict:
    tickers = args.get("tickers") or DEFAULT_TICKERS
    weights = args.get("weights")
    task_id = args.get("task_id") or "backtest"
    lookback_years = float(args.get("lookback_years", 2) or 2)
    target_sharpe = float(args.get("target_sharpe", 1.2) or 1.2)

    if not isinstance(tickers, list) or not tickers:
        return {"ok": False, "error": _t("err.tickers_empty")}
    tickers = [str(t).strip().upper() for t in tickers]
    if weights is None:
        weights = [1.0 / len(tickers)] * len(tickers)
    if not isinstance(weights, list) or len(weights) != len(tickers):
        return {"ok": False, "error": _t("err.weights_len") % len(tickers)}

    try:
        import numpy as np
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": _t("err.numpy") % e}

    w = np.array([float(x) for x in weights], dtype=float)
    if w.sum() <= 0:
        return {"ok": False, "error": _t("err.weights_sum")}
    w = w / w.sum()  # normalizar a suma 1

    # ── DATOS REALES: cierres ajustados de Yahoo Finance (yfinance) ──────────────
    try:
        import yfinance as yf
    except Exception as e:
        return {"ok": False, "error": _t("err.yfinance") % e}

    period = "%dy" % max(1, int(round(lookback_years)))
    try:
        raw = yf.download(tickers, period=period, interval="1d",
                          auto_adjust=True, progress=False, threads=True)
    except Exception as e:
        return {"ok": False, "error": _t("err.download") % e}

    # yfinance: con varios tickers devuelve columnas MultiIndex (campo, ticker).
    try:
        close = raw["Close"] if "Close" in raw else raw
        # ordenar columnas según `tickers` (yfinance las alfabetiza)
        if hasattr(close, "columns"):
            cols = [t for t in tickers if t in list(close.columns)]
            if len(cols) != len(tickers):
                missing = [t for t in tickers if t not in cols]
                return {"ok": False, "error": _t("err.tickers_no_data") % ", ".join(missing)}
            close = close[tickers]
            prices = close.dropna().values
        else:  # un solo ticker → Series
            prices = close.dropna().values.reshape(-1, 1)
    except Exception as e:
        return {"ok": False, "error": _t("err.parse_prices") % e}

    if prices.shape[0] < 30:
        return {"ok": False, "error": _t("err.too_few") % prices.shape[0]}

    # ── BACKTEST: retornos diarios de la cartera (rebalanceo diario a pesos w) ────
    rets = prices[1:] / prices[:-1] - 1.0           # retornos diarios por activo
    port = rets @ w                                  # retorno diario de la cartera
    n_days = int(port.shape[0])

    mu_d = float(port.mean())
    sd_d = float(port.std(ddof=1))
    ann_return = mu_d * _TRADING_DAYS
    ann_vol = sd_d * math.sqrt(_TRADING_DAYS)
    sharpe = (ann_return / ann_vol) if ann_vol > 0 else 0.0

    # curva de equity (base 1.0) + max drawdown
    equity = np.cumprod(1.0 + port)
    running_max = np.maximum.accumulate(equity)
    drawdown = equity / running_max - 1.0
    max_dd = float(drawdown.min())

    # downsample la curva de equity a ~120 puntos para el display (la curva redibujándose)
    m = equity.shape[0]
    step = max(1, m // 120)
    curve = [round(float(x), 4) for x in equity[::step].tolist()]
    if curve and curve[-1] != round(float(equity[-1]), 4):
        curve.append(round(float(equity[-1]), 4))

    passed = sharpe >= target_sharpe
    weights_pct = {tickers[i]: round(float(w[i]) * 100, 1) for i in range(len(tickers))}

    # ── ACUMULAR la iteración en convergence.json (la PROGRESIÓN del loop) ────────
    # cada llamada con el mismo task_id/workdir agrega un paso → el executor la surfacea como
    # UNA obra `convergence` → La Sala la rinde con el display 1D (Sharpe subiendo, curva
    # redibujándose, it.1 FALLA rojo → it.N PASA verde). Mismo patrón que el FEM/Bode.
    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    iteration_n = 1
    try:
        cpath = os.path.join(workdir, "convergence.json")
        conv = None
        if os.path.exists(cpath):
            with open(cpath) as f:
                conv = json.load(f)
        if not (isinstance(conv, dict) and isinstance(conv.get("iterations"), list)
                and conv.get("task_id") == task_id):
            conv = {
                "type": "convergence",
                "title": _t("conv.title"),
                "task_id": task_id,
                "metric": {"name": _t("metric.name"), "unit": "", "goal": "max", "limit": target_sharpe},
                "limit": target_sharpe,
                "iterations": [],
            }
        conv["limit"] = target_sharpe
        conv["metric"]["limit"] = target_sharpe
        iteration_n = len(conv["iterations"]) + 1
        conv["iterations"].append({
            "n": iteration_n,
            "value": round(sharpe, 3),
            "curve": curve,
            "weights_pct": weights_pct,
            "ann_return_pct": round(ann_return * 100, 2),
            "ann_vol_pct": round(ann_vol * 100, 2),
            "passed": passed,
        })
        with open(cpath, "w") as f:
            json.dump(conv, f, ensure_ascii=False)
    except Exception:
        pass

    # los HECHOS del backtest para el cerebro. QUÉ pesos probar después es DECISIÓN del agente
    # (este server mide, no propone reasignaciones).
    return {
        "ok": True,
        "iteration": iteration_n,
        "tickers": tickers,
        "weights_pct": weights_pct,
        "sharpe": round(sharpe, 3),
        "target_sharpe": target_sharpe,
        "meets_target": passed,
        "verdict": (_t("verdict.pass") if passed else _t("verdict.fail")),
        "ann_return_pct": round(ann_return * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "n_trading_days": n_days,
        "lookback_years": lookback_years,
        "note": _t("note"),
    }


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})
    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "backtest-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "backtest_portfolio":
                val = _run_backtest(args)
            else:
                raise ValueError("unknown tool %s" % name)
            is_err = not val.get("ok", True)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": is_err}})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": "error: %s" % exc}], "isError": True}})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": "Method not found: %s" % method}})


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
