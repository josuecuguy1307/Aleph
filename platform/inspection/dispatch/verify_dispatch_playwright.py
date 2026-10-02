#!/usr/bin/env python3
"""
verify_dispatch_playwright.py — VERIFY del DESPACHADOR §0.5 DESDE LA UI con Playwright, en
puertos propios (NO :8091), 0 errores de consola.

Levanta el backend (uvicorn, con el gate de verificación) + el dev server serve.py (que sirve
dispatch.dc.html y proxya /v1 con passthrough SSE), abre la página real en un browser headless
y maneja `window.runDispatch(...)` para los 4 asserts del contrato:

  (a) target con MCP verificado en registry → la UI muestra "✓ Encontrado en el registry",
      equipa (pieza real) y el Motor B NO corre (cero eventos de forja).
  (b) target sin MCP → "✦ Forjado nuevo (Motor B)": el resolver da miss y se dispara la forja.
  (c) impostor DNS → la UI muestra "impostor rechazado" y NO equipa.
  (d) ambos caminos terminan en pieza real (tools reales en cada panel).

Uso:
    GROQ_API_KEY=… product/backend/.venv/bin/python \\
      platform/inspection/dispatch/verify_dispatch_playwright.py
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

from inspection.dispatch.selftest_dispatch_order import (  # noqa: E402
    _boot_server, _free_port, _fake_spec, _cand, _recover_tmdb_from_vault)


def _boot_frontend(front_port: int, back_port: int):
    """serve.py en un thread, sirviendo MI worktree design/ + proxy al backend de este run."""
    os.environ["ALEPH_FRONT_PORT"] = str(front_port)
    os.environ["ALEPH_BACKEND"] = f"http://127.0.0.1:{back_port}"
    import importlib
    serve = importlib.import_module("serve")          # product/app/serve.py
    importlib.reload(serve)                            # re-lee PORT/BACK del env
    srv = serve.ThreadingHTTP(("", front_port), serve.H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    import urllib.request
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{front_port}/dispatch.dc.html", timeout=1) as r:
                if r.status == 200:
                    return srv
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("serve.py no sirvió dispatch.dc.html a tiempo")


def main() -> int:
    from playwright.sync_api import sync_playwright

    tmdb_key = os.environ.get("FORGE_VERIFY_TMDB_KEY", "") or _recover_tmdb_from_vault()
    have_forge = bool(tmdb_key) and bool(os.environ.get("GROQ_API_KEY"))

    back_port, front_port = _free_port(), _free_port()
    print("═" * 72)
    print(f"  VERIFY UI DESPACHADOR · backend :{back_port} · front :{front_port}")
    print(f"  forja-en-vivo (b/d): {'SÍ (TMDB+Groq)' if have_forge else 'OMITIDA'}")
    print("═" * 72)

    server, _ = _boot_server(back_port)
    _front = _boot_frontend(front_port, back_port)
    tmp = Path(tempfile.mkdtemp(prefix="disp-ui-"))

    # ── fixtures: candidatos (arbitrados por el matcher REAL) + spec del MCP local real ──
    fake = _fake_spec(tmp, tools=["get_account", "list_charges"], server_name="stripe-local")
    verified = _cand("com.stripe/mcp", "com.stripe", "stripe", "dns", "Stripe",
                     "Stripe payments MCP", "https://mcp.stripe.com")
    impostor = _cand("io.github.evil/stripe-mcp", "io.github.evil", "evil", "github_org",
                     "Stripe (unofficial)", "stripe-like community fork", "https://evil.example/mcp")

    console_errors: list[str] = []
    results = {}
    base = f"http://127.0.0.1:{front_port}/dispatch.dc.html"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
            page.goto(base, wait_until="networkidle")

            # ── (a) FOUND → equip 1-B, sin forja ──────────────────────────────────────
            a = page.evaluate(
                """async (p) => await window.runDispatch(
                    {service:'stripe', credential:null, url:null,
                     seed_candidates:[p.cand], seed_spec:p.spec})""",
                {"cand": verified, "spec": fake})
            reg_visible = not page.locator("#resRegistry").is_hidden()
            forge_visible_a = not page.locator("#resForged").is_hidden()
            no_forge = not any(t in (a.get("events") or []) for t in
                               ("forge.iniciado", "dispatch.forjando", "mcp.forjado", "observando"))
            a_ok = (a.get("origin") == "registry" and a.get("path") == "registry"
                    and bool(a.get("tools")) and reg_visible and not forge_visible_a and no_forge)
            results["(a) found→equip · sin forja"] = a_ok
            print(f"  (a) origin={a.get('origin')} tools={a.get('tools')} "
                  f"registry_panel={reg_visible} forge_corrio={not no_forge} → {'✅' if a_ok else '❌'}")
            a_tools = a.get("tools") or []

            # ── (c) IMPOSTOR → rechazado, sin equip ───────────────────────────────────
            page.goto(base, wait_until="networkidle")
            c = page.evaluate(
                """async (cand) => await window.runDispatch(
                    {service:'stripe', credential:null, url:null, seed_candidates:[cand]})""",
                impostor)
            reg_visible_c = not page.locator("#resRegistry").is_hidden()
            estado_c = page.locator("#estado").inner_text()
            c_ok = ("resolver.miss" in (c.get("events") or [])
                    and bool(c.get("rejected_impostor"))
                    and "mcp.equipado" not in (c.get("events") or [])
                    and "resolver.encontrado" not in (c.get("events") or [])
                    and not reg_visible_c and "impostor" in estado_c.lower())
            results["(c) impostor rechazado"] = c_ok
            print(f"  (c) rejected_impostor={c.get('rejected_impostor')} eventos={c.get('events')} "
                  f"estado={estado_c[:46]!r} equip_panel={reg_visible_c} → {'✅' if c_ok else '❌'}")

            # ── (b)+(d-forjado) MISS → Motor B forja pieza real ───────────────────────
            b_tools = []
            if have_forge:
                page.goto(base, wait_until="networkidle")
                b = page.evaluate(
                    """async (p) => await window.runDispatch(
                        {service:p.url, url:p.url, credential:p.key, forma:'token',
                         synth_alias:'oss', max_rounds:2, seed_candidates:[]})""",
                    {"url": "https://api.themoviedb.org/3", "key": tmdb_key})
                forge_visible = not page.locator("#resForged").is_hidden()
                evs = b.get("events") or []
                b_ok = (b.get("origin") == "forged" and "resolver.miss" in evs
                        and "dispatch.forjando" in evs and "mcp.forjado" in evs
                        and bool(b.get("tools")) and forge_visible)
                results["(b) miss→forja Motor B"] = b_ok
                b_tools = b.get("tools") or []
                print(f"  (b) origin={b.get('origin')} server={b.get('server')} "
                      f"tools={len(b_tools)} forge_panel={forge_visible} → {'✅' if b_ok else '❌'}")
            else:
                print("  ⚠ (b)/(d-forjado) OMITIDO: falta GROQ_API_KEY o TMDB key.")

            browser.close()

        # ── (d) ambos caminos terminan en pieza real ──────────────────────────────────
        d_ok = bool(a_tools) and (bool(b_tools) if have_forge else True)
        results["(d) ambos pieza real"] = d_ok
        print(f"  (d) found_tools={len(a_tools)} forged_tools={len(b_tools)} → {'✅' if d_ok else '❌'}")
    finally:
        server.should_exit = True
        time.sleep(0.3)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "─" * 72)
    print(f"  errores de consola: {len(console_errors)}")
    for e in console_errors:
        print(f"    ✗ {e}")
    console_ok = not console_errors
    results["consola 0 errores"] = console_ok

    print("═" * 72)
    for k, v in results.items():
        print(f"  {k:30s}: {'✅ VERDE' if v else '❌ ROJO'}")
    if not have_forge:
        print("  (b)/(d-forjado) no evaluados (forja en vivo omitida)")
    allok = all(results.values())
    print("═" * 72 + f"\n  TOTAL: {'✅ TODO VERDE' if allok else '❌ HAY ROJO'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
