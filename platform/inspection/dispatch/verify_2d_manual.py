#!/usr/bin/env python3
"""
verify_2d_manual.py — DONE-BAR de LA REVISIÓN ANTES DE EQUIPAR (2d), DESDE LA UI del Cuarto, con
Playwright, en puertos propios (NO :8091), 0 errores de consola, forja real Groq+TMDB.

Mismo principio que el gate de F5: lo automático corre solo, el humano decide en el punto que importa.
Antes los puntos eran DOS y colgaban de un interruptor ("Modo técnico", default OFF). El interruptor
MURIÓ (identidad visual 6/6) y con él el punto 1 (descartar propuestas a mitad de vuelo). Queda UNO,
y ya no hay modo que encender:

   REVISAR ANTES DE EQUIPAR — el panel muestra las tools REALES del emit, TODAS MARCADAS.
   [Continuar] sin tocar nada equipa exactamente lo forjado; destildar es opcional.

Los 4 asserts:
  (a) SIEMPRE VISIBLE, NUNCA BLOQUEA → sin encender nada, el panel aparece con TODAS las casillas
      marcadas y [Continuar] habilitado; un solo toque equipa TODAS las tools forjadas. Es la
      regresión del viejo flujo automático: mismo resultado, ahora a la vista. Y no queda ni rastro
      del toggle en el DOM (#manualBtn / #manualState).
  (b) DESTILDAR una tool real (p2_genres) por el panel (clic DOM real) → el MCP sellado no la tiene;
      otra tool (k3_movie) sobrevive y SÍ queda. Cero-teatro: el panel lista las tools REALES del emit.
  (c) El modelo de relaciones del Cuarto NO se muta: estructura idéntica entre el camino por-default
      y el camino con destilde (la revisión sólo modula `tools[]`, no agrega piezas ni relaciones).
  (d) El detalle crudo NO se perdió con el modo: vive plegado detrás del "?" del panel (#msealDetail
      arranca oculto y el "?" lo abre) — "más/?/evidencia", nunca un modo previo.

Determinismo: se SIEMBRAN 3 sondas reales (PUPPET_FORGE_ALLOW_SEED_PROBES=1) con nombres conocidos
que validan contra TMDB (200), para nombrar exactamente qué se destilda y qué sobrevive. El destilde
es un clic DOM real sobre el panel.

Uso:
    GROQ_API_KEY=… product/backend/.venv/bin/python \\
      platform/inspection/dispatch/verify_2d_manual.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
_APP = _REPO_ROOT / "product" / "app"
for p in (str(_BACKEND), str(_PLATFORM), str(_APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

# el gate de seed-probes tiene que estar ANTES de que el backend atienda el primer request.
os.environ["PUPPET_FORGE_ALLOW_SEED_PROBES"] = "1"
os.environ.setdefault("PUPPET_HTTP_TIMEOUT", "150")

from inspection.dispatch.selftest_dispatch_order import (  # noqa: E402
    _boot_server, _free_port, _recover_tmdb_from_vault)

PUPPET = "cuarto-2d-manual"
CUARTO_PATH = f"/cuarto/cuarto.pixi.html?puppet={PUPPET}"
SHOTS = _REPO_ROOT / "product" / "app" / "design" / "cuarto" / "screenshots"

# sondas REALES (TMDB · Forma 1 token-en-query). Nombres conocidos → asserts determinísticos.
P1 = "p1_config"        # /configuration         → 200 · testigo: sobrevive el camino por-default
P2 = "p2_genres"        # /genre/movie/list      → 200 · se DESTILDA en la revisión
K3 = "k3_movie"         # /movie/550             → 200 · SOBREVIVE siempre (queda en el MCP)
SEED_PROBES = [
    {"name": P1, "endpoint": "/configuration", "method": "GET", "kind": "read"},
    {"name": P2, "endpoint": "/genre/movie/list", "method": "GET", "kind": "read"},
    {"name": K3, "endpoint": "/movie/{movie_id}", "method": "GET",
     "path_params": {"movie_id": "550"}, "kind": "read"},
]


def _boot_frontend(front_port: int, back_port: int):
    """serve.py en un thread, sirviendo MI worktree design/ + proxy SSE al backend de este run."""
    os.environ["ALEPH_FRONT_PORT"] = str(front_port)
    os.environ["ALEPH_BACKEND"] = f"http://127.0.0.1:{back_port}"
    import importlib
    serve = importlib.import_module("serve")          # product/app/serve.py
    importlib.reload(serve)
    srv = serve.ThreadingHTTP(("", front_port), serve.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import urllib.request
    for _ in range(100):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{front_port}/cuarto/cuarto.pixi.html", timeout=1) as r:
                if r.status == 200:
                    return srv
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("serve.py no sirvió cuarto.pixi.html a tiempo")


# ── dispara el run SIN await: el panel de revisión queda VIVO para clics DOM + capturas ──
# No hay `setEnabled`: no hay modo que encender. La revisión sale sola.
_FIRE_JS = """
(p) => {
  window.__manual.configure({ autoSeal: false });   // el sello lo da un clic DOM real
  window.__mres = null;
  window.__mpending = window.__inspectAndEquip(p.args).then(r => { window.__mres = r; });
  return true;
}
"""

# el panel tal como lo ve una persona: qué lista, qué viene marcado, qué dice el botón.
_PANEL_JS = """
() => {
  const $ = (i) => document.getElementById(i);
  const rows = [...document.querySelectorAll("#msealbar .srow")];
  const ok = $("msealConfirm");
  return {
    hidden: !!($("msealbar") || {}).hidden,
    names: rows.map(r => r.querySelector(".sname").textContent),
    checked: rows.map(r => r.querySelector(".schk").checked),
    count: ($("msealCount") || {}).textContent || "",
    confirmLabel: (ok ? ok.textContent : "").trim(),
    confirmDisabled: !!(ok && ok.disabled),
    // el modo no dejó rastro en el DOM
    noToggle: !$("manualBtn") && !$("manualState") && !$("mpropbar"),
    // el detalle crudo arranca PLEGADO detrás del "?" (no encima de quien no lo pidió)
    detailHidden: !!($("msealDetail") || {}).hidden,
    hasWhy: !!$("msealWhy"),
  };
}
"""

_COLLECT_JS = """
() => {
  const res = window.__mres || {};
  const placed = window.__cuarto.placedTiles();
  const fp = placed.find(t => t.forged) || null;
  const evs = res.events || [];
  const model = window.__cuarto.relationModel();
  const recipe = window.__lastRecipe || {};
  const tf = (recipe.belt && recipe.belt.tool_filters) || {};
  const filterTools = [].concat(...Object.values(tf));
  return {
    ok: !!res.ok, path: res.path || null,
    pieceTools: fp ? fp.tools : null,
    backendValidated: evs.filter(e => e.type === "tool.validada").map(e => e.nombre),
    forjadoTools: (evs.find(e => e.type === "mcp.forjado") || {}).tools || [],
    lastRun: window.__manual.lastRun(),
    model: { pieces: model.pieces.map(x => x.type),
             rels: model.relationships.map(r => r.kind).sort() },
    filterTools,
  };
}
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    tmdb_key = os.environ.get("FORGE_VERIFY_TMDB_KEY", "") or _recover_tmdb_from_vault()
    have_forge = bool(tmdb_key) and bool(os.environ.get("GROQ_API_KEY"))

    back_port, front_port = _free_port(), _free_port()
    print("═" * 74)
    print(f"  VERIFY 2d · revisión antes de equipar (Cuarto) · backend :{back_port} · front :{front_port}")
    print(f"  forja-en-vivo (TMDB+Groq): {'SÍ' if have_forge else 'OMITIDA (falta key)'}")
    print("═" * 74)
    if not have_forge:
        print("  ⚠ falta GROQ_API_KEY o TMDB key — no se puede verificar la forja real. ABORTO.")
        return 1

    server, _ = _boot_server(back_port)
    _front = _boot_frontend(front_port, back_port)
    SHOTS.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="2d-manual-"))

    # maxRounds=1 → UNA sola síntesis Groq por forja (4 → 2 llamadas) para no agotar el TPM free; las
    # 3 sondas reales bastan para los asserts aunque Groq proponga poco. La forja igual EXIGE que la
    # síntesis de la ronda 1 no degrade (si degrada, el motor corta antes de sembrar/forjar).
    args = {"service": "https://api.themoviedb.org/3", "url": "https://api.themoviedb.org/3",
            "cred": tmdb_key, "maxRounds": 1, "seedCandidates": [], "seedProbes": SEED_PROBES,
            "synthAlias": "oss"}   # pin: este verify mide el camino Groq (el default del cliente ahora es brain)

    console_errors: list[str] = []
    R: dict[str, bool] = {}
    base = f"http://127.0.0.1:{front_port}"
    cuarto_url = base + CUARTO_PATH
    auto = manual = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1360, "height": 900})
            page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

            def open_cuarto():
                page.goto(cuarto_url, wait_until="load")
                page.wait_for_function(
                    "() => window.__cuarto && window.__inspectAndEquip && window.__manual",
                    timeout=15000)

            def wait_panel():
                page.wait_for_selector("#msealbar:not([hidden]) .srow", timeout=180000)
                return page.evaluate(_PANEL_JS)

            # ── (a) POR DEFAULT · aparece solo, todo marcado, un toque ────────────────
            print("  · (a) forjando TMDB y continuando SIN tocar nada… ~30-120s")
            open_cuarto()
            page.evaluate(_FIRE_JS, {"args": args})
            pan_a = wait_panel()
            page.screenshot(path=str(SHOTS / "2d-revision-default.png"))
            page.click("#msealConfirm")
            page.wait_for_function("() => window.__mres !== null", timeout=60000)
            auto = page.evaluate(_COLLECT_JS)

            forj = auto.get("forjadoTools") or []
            ptools = auto.get("pieceTools") or []
            pa = (auto.get("ok") is True and auto.get("path") == "forged"
                  and pan_a.get("hidden") is False                       # el panel apareció SOLO
                  and pan_a.get("noToggle") is True                      # sin rastro del modo
                  and len(pan_a.get("names") or []) >= 3
                  and all(pan_a.get("checked") or [False])               # TODAS marcadas
                  and pan_a.get("confirmDisabled") is False              # nunca bloquea
                  and len(ptools) >= 3 and set(ptools) == set(forj)      # equipa EXACTAMENTE lo forjado
                  and P1 in ptools and P2 in ptools and K3 in ptools)    # cero pérdida
            R["(a) sale sola · todo marcado · un toque equipa todo"] = pa
            print(f"      panel={not pan_a.get('hidden')} marcadas={pan_a.get('count')} "
                  f"botón='{pan_a.get('confirmLabel')}' sin_toggle={pan_a.get('noToggle')} "
                  f"forjadas={len(forj)} pieza={len(ptools)} p1∈={P1 in ptools} p2∈={P2 in ptools} "
                  f"k3∈={K3 in ptools} → {'✅' if pa else '❌'}")

            det_pre = pan_a.get("detailHidden")   # (d) · se cierra en la 2da corrida, con el panel vivo

            # ── (b)(c)(d) · destildar una tool real por el panel ──────────────────────
            page.wait_for_timeout(4000)   # dejá respirar el TPM de Groq antes de la 2da forja
            print("  · (b)(c)(d) forjando TMDB y DESTILDANDO una tool por el panel… ~30-120s")
            open_cuarto()
            page.evaluate(_FIRE_JS, {"args": args})
            pan_b = wait_panel()
            seal_names = pan_b.get("names") or []
            page.screenshot(path=str(SHOTS / "2d-revision-lista.png"))

            # (d) el "?" abre el detalle crudo — lo que era el modo, ahora un pliegue
            det_open = None
            if pan_b.get("hasWhy"):
                page.click("#msealWhy")
                det_open = page.evaluate("() => document.getElementById('msealDetail').hidden")
            pdd = (pan_b.get("hasWhy") is True and pan_b.get("detailHidden") is True
                   and det_pre is True and det_open is False)
            R["(d) el detalle crudo vive detrás del ? (no de un modo)"] = pdd
            print(f"      (d) ? presente={pan_b.get('hasWhy')} arranca_plegado={pan_b.get('detailHidden')} "
                  f"el_? _lo_abre={det_open is False} → {'✅' if pdd else '❌'}")

            drop = P2 if P2 in seal_names else (seal_names[0] if seal_names else None)
            if drop:
                page.click(f'#msealbar .srow[data-name="{drop}"] .schk')
            page.screenshot(path=str(SHOTS / "2d-revision-destildada.png"))
            page.click("#msealConfirm")
            page.wait_for_function("() => window.__mres !== null", timeout=60000)
            manual = page.evaluate(_COLLECT_JS)

            mp = manual.get("pieceTools") or []
            lr = manual.get("lastRun") or {}
            bval = manual.get("backendValidated") or []
            ftools = manual.get("filterTools") or []

            # (b) destildar antes de equipar
            pb = (drop == P2 and P2 in (lr.get("surviving") or [])  # listada REAL en el panel
                  and P2 not in (lr.get("kept") or [])              # destildada
                  and P2 not in mp and P2 not in ftools             # el MCP sellado NO la tiene
                  and K3 in mp and K3 in ftools                     # k3 sobrevivió → SÍ está
                  and len(mp) >= 1)
            R["(b) destildar → la tool quitada no queda en el MCP"] = pb
            print(f"      (b) destildada={drop} listada_real={P2 in (lr.get('surviving') or [])} "
                  f"∉kept={P2 not in (lr.get('kept') or [])} ∉pieza={P2 not in mp} ∉belt={P2 not in ftools} "
                  f"k3∈pieza={K3 in mp} → {'✅' if pb else '❌'}")

            # (c) modelo sin mutar (estructura idéntica entre los dos caminos)
            pc = (manual.get("model") == auto.get("model")
                  and manual.get("model", {}).get("pieces") == ["nucleo", "tool"]
                  and manual.get("model", {}).get("rels") == ["eco", "ida"])
            R["(c) modelo del Cuarto sin mutar (destilde == default)"] = pc
            print(f"      (c) model_destilde={manual.get('model')} == model_default={auto.get('model')} "
                  f"→ {'✅' if pc else '❌'}")

            # cero-teatro: el panel mostró tools REALES (subconjunto de las validadas)
            real_panel = bool(seal_names) and all(n in bval for n in seal_names)
            R["(cero-teatro) el panel = tools reales del emit"] = real_panel
            print(f"      cero-teatro: panel⊆validadas={real_panel}")

            browser.close()
    finally:
        server.should_exit = True
        time.sleep(0.3)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "─" * 74)
    print(f"  errores de consola: {len(console_errors)}")
    for e in console_errors:
        print(f"    ✗ {e}")
    R["consola 0 errores"] = not console_errors

    print("═" * 74)
    for k, v in R.items():
        print(f"  {k:52s}: {'✅ VERDE' if v else '❌ ROJO'}")
    allok = all(R.values())
    print("═" * 74)
    print(f"  capturas: {SHOTS}/2d-revision-default.png · 2d-revision-lista.png · 2d-revision-destildada.png")
    print(f"  TOTAL: {'✅ TODO VERDE — la revisión siempre visible y nunca bloqueante' if allok else '❌ HAY ROJO'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
