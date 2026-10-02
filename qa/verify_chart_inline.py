#!/usr/bin/env python3
"""verify_chart_inline.py — spec de gráfico en la burbuja → SVG, no JSON crudo.

ROJO: marked deja ```json como <pre><code> y nadie llama renderInlineFigures.
VERDE: spec válida (raíz o Chart.js) se vuelve .sala-chart-fig; schema, python y
spec rota siguen siendo código.

    /opt/miniconda3/bin/python3.13 qa/verify_chart_inline.py
"""
from __future__ import annotations

import http.server
import os
import socket
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
DESIGN = RAIZ / "product" / "app" / "design"
SHOT = RAIZ / "product" / "app" / "design" / "sala-v2" / "verify" / "screenshots" / "chart-inline.png"

_fail = 0


def ok(cond, msg, extra=""):
    global _fail
    if cond:
        print("  OK  ", msg)
    else:
        _fail += 1
        print("  FAIL", msg, extra)


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DESIGN), **k)

    def log_message(self, *a):
        pass


def main() -> int:
    port = _port()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}/sala-v2/verify/chart-inline.html"
    print("\nverify_chart_inline ·", url)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 900, "height": 1400})
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window.__despues", timeout=20000)
        st = page.evaluate("({ mdOnly: window.__mdOnly, despues: window.__despues })")
        print("\nROJO (solo markdown, sin renderInlineFigures)")
        ok(st["mdOnly"]["figs"] == 0 and st["mdOnly"]["jsonVisible"],
           "sin figures: el JSON sigue en el DOM (el defecto)", st["mdOnly"])
        print("\nVERDE (después de renderInlineFigures)")
        ok(st["despues"]["figs"] == 2, "2 gráficos SVG (line raíz + bar Chart.js)", st["despues"])
        ok(st["despues"]["paths"] >= 1, "el line tiene path", st["despues"])
        ok(st["despues"]["python"], "el bloque python sigue siendo código")
        ok(st["despues"]["schema"], "JSON Schema {type:object} NO se dibuja como chart")
        ok(st["despues"]["specRotaComoCodigo"], "spec inválida queda como código, no rompe")
        ok(not st["despues"]["jsonLineVisible"],
           "el JSON interno del line no queda a la vista como spec")
        SHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT), full_page=True)
        print("\n  screenshot", SHOT)
        browser.close()
    srv.shutdown()
    print("\n" + ("VERDE" if _fail == 0 else f"ROJO ×{_fail}"))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
