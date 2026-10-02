#!/usr/bin/env python3
"""
quant_chart.py — MOTOR QUANT. Genera un chart con CÓDIGO REAL ejecutándose
(matplotlib + mplfinance) sobre DATA REAL de yfinance, y exporta un PNG con savefig().

REGLA DURA (de la misión): el chart lo produce matplotlib corriendo, NO el modelo
dibujando un SVG. La salida es un raster PNG binario; el bridge verifica los magic
bytes. Si yfinance no trae data, REVIENTA — nada de números inventados.

Uso:
    python quant_chart.py AAPL /ruta/salida.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless: render a archivo, sin display
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import yfinance as yf


# [i18n-bi] Ola 1 — el raster se hornea al idioma del run (PUPPET_LANG, default es;
# no-op hasta que el runtime lo setee). Un PNG es horneado: el idioma queda fijo al
# generarlo (igual que el resto del contenido server-side). Los {} son posicionales
# (str.format); los números van pre-formateados para conservar el signo y 1 decimal.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
CHART_I18N = {
    "es": {
        "chart.title": "{} — velas diarias (6m) · Yahoo Finance",
        "chart.price_axis": "Precio (USD)",
        "chart.subtitle": "QUANT · {} | retorno 6m: {}% · vol. anualizada: {}%",
        "chart.equity_axis": "Capital (comprar y mantener, base 100)",
    },
    "en": {
        "chart.title": "{} — daily candles (6m) · Yahoo Finance",
        "chart.price_axis": "Price (USD)",
        "chart.subtitle": "QUANT · {} | 6m return: {}% · annualized vol: {}%",
        "chart.equity_axis": "Equity (buy & hold, base 100)",
    },
}
def _t(key):
    return CHART_I18N.get(PUPPET_LANG, {}).get(key) or CHART_I18N["es"].get(key) or key


def fetch_ohlcv(ticker: str, period: str = "6mo"):
    """Descarga OHLCV REAL de Yahoo Finance. Sin red/sin data → excepción."""
    df = yf.download(ticker, period=period, interval="1d",
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance no devolvió data para {ticker} (sin red o ticker inválido).")
    # yfinance a veces devuelve columnas MultiIndex (ticker en nivel 1): aplanar.
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df


def render_chart(ticker: str, out_png: str | Path) -> dict:
    df = fetch_ohlcv(ticker)
    closes = df["Close"].to_numpy(dtype=float)

    # Equity curve: buy & hold normalizado a 100 (cómputo real sobre los cierres reales).
    equity = 100.0 * closes / closes[0]
    daily_ret = np.diff(closes) / closes[:-1]
    total_ret = (closes[-1] / closes[0] - 1.0) * 100.0
    vol_annual = float(np.std(daily_ret) * np.sqrt(252) * 100.0)

    # Figura con 2 paneles: candlestick (mplfinance) arriba + equity curve abajo.
    fig = plt.figure(figsize=(11, 8), dpi=110)
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1, 0.9], hspace=0.32)

    ax_c = fig.add_subplot(gs[0:2, 0])
    ax_v = fig.add_subplot(gs[2, 0], sharex=ax_c)
    # mplfinance dibuja velas REALES en los axes que le paso.
    mpf.plot(df, type="candle", style="yahoo", ax=ax_c, volume=ax_v,
             show_nontrading=False, datetime_format="%b %d", xrotation=0)
    ax_c.set_title(_t("chart.title").format(ticker),
                   fontsize=13, fontweight="bold")
    ax_c.set_ylabel(_t("chart.price_axis"))

    # Equity curve en su propio eje (segunda figura compuesta abajo del volumen
    # no, mejor: superpuesta como twin). Mostramos retorno acumulado en panel aparte.
    fig.suptitle(
        _t("chart.subtitle").format(ticker, f"{total_ret:+.1f}", f"{vol_annual:.1f}"),
        fontsize=11, y=0.965, color="#333",
    )

    # Segundo PNG conceptual integrado: agregamos la equity curve como inset.
    ax_eq = ax_c.inset_axes([0.02, 0.02, 0.34, 0.28])
    ax_eq.plot(equity, color="#1f77b4", lw=1.6)
    ax_eq.fill_between(range(len(equity)), 100, equity,
                       color="#1f77b4", alpha=0.12)
    ax_eq.axhline(100, color="#888", lw=0.7, ls="--")
    ax_eq.set_title(_t("chart.equity_axis"), fontsize=8)
    ax_eq.tick_params(labelsize=6)

    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="png", bbox_inches="tight")  # ← PNG real, savefig
    plt.close(fig)

    return {
        "ticker": ticker, "rows": int(len(df)),
        "first_close": float(closes[0]), "last_close": float(closes[-1]),
        "total_return_pct": round(total_ret, 2), "vol_annual_pct": round(vol_annual, 2),
        "png": str(out),
    }


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    out = sys.argv[2] if len(sys.argv) > 2 else "quant_chart.png"
    import json
    print(json.dumps(render_chart(ticker, out), indent=2))
