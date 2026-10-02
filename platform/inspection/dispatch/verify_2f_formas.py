#!/usr/bin/env python3
"""
verify_2f_formas.py — DONE-BAR de la rama 2f-formas (las 2 formas de sesión que faltaban),
DESDE LA UI del Cuarto, con Playwright, en puertos propios (NO :8091), Groq, 0 errores de consola.

La tesis de 2f-formas: la FORMA de sesión que el usuario elige en la entrada de "Inspeccionar"
rutea al SessionProvider del Motor B (que YA implementa las 4 formas). Ola 0 dejó "token"
andando; esta ola suma "abierto" y "login". El navegador/OAuth+2FA = Ola 3 (queda marcado, NO
implementado: el motor NUNCA resuelve 2FA — línea roja §2).

Cero-teatro: una sesión está "ok" SÓLO si el SessionProvider la confirma (sesion.ok) y SÓLO se
afirma "forja" si hay mcp.forjado con ≥1 tool verificada VIVA. Las 3 formas se forjan contra
targets REALES y PÚBLICOS (el guard SSRF de producción los aprueba — sin aflojar nada):

  (a) ABIERTO  → PokéAPI (https://pokeapi.co/api/v2) · self-describe, SIN credencial.
  (b) LOGIN    → DummyJSON (https://dummyjson.com) · POST /auth/login {username,password} →
                 accessToken → header Bearer → /auth/me 200 (sin token: 401 — login REAL, sin 2FA).
  (c) TOKEN    → TMDB (https://api.themoviedb.org/3) · REGRESIÓN de la forma de Ola 0.

Asserts:
  (a) forma=abierto → sesion.ok + mcp.forjado (≥1 tool, pieza real).
  (b) forma=login   → sesion.ok + mcp.forjado (≥1 tool, pieza real, sesión por login API).
  (c) forma=token   → sesion.ok + mcp.forjado (regresión).
  (d) modelo del Cuarto SIN mutar (git: sólo cambian cuarto.pixi.html + cuarto.inspect.js).
  (e) el SELECTOR de forma vive en la entrada (barra + modal "API cruda") y conmuta los campos;
      browser-OAuth está MARCADO pero deshabilitado (Ola 3).
  (f) el backend RECHAZA forma=browser (501 · hueco marcado, no implementado).
  (g) consola: 0 errores.

Las forjas van por el consumidor UNIFICADO (window.__inspectAndEquip → /v1/inspect/dispatch) con
`seedCandidates: []` → fuerza resolver-MISS sin pegarle al registry vivo → Motor B + Groq.

Uso:
    GROQ_API_KEY=… product/backend/.venv/bin/python \\
      platform/inspection/dispatch/verify_2f_formas.py
"""
from __future__ import annotations

# ── [Step 5 · P7] OPT-OUT del muro de construcción ────────────────────────────
# Desde P7 el muro premium está ACTIVO POR DEFAULT (antes era staged-off, lo que
# dejaba builds públicos sin muro). Este verificador ejercita el MOTOR, no la
# frontera de tier, y corre con cuentas de prueba sin plan pago: sin este opt-out
# recibiría 402 y probaría otra cosa. La frontera premium tiene sus propios tests
# (test_construction_premium_gate.py, test_muros_default_on.py).
import os as _os
_os.environ.setdefault("PUPPET_ENFORCE_MCP_CONSTRUCTION", "0")

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
_APP = _REPO_ROOT / "product" / "app"
for p in (str(_BACKEND), str(_PLATFORM), str(_APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("PUPPET_WORKERS", "0")

from inspection.dispatch.selftest_dispatch_order import (  # noqa: E402
    _boot_server, _free_port, _recover_tmdb_from_vault)
from inspection.dispatch.verify_integra_ola1 import _boot_frontend  # noqa: E402

FORK_BASE = "9e0d7dd"
PUPPET = "cuarto-2f-formas"
CUARTO_PATH = f"/cuarto/cuarto.pixi.html?puppet={PUPPET}"
# Groq gpt-oss-120b free-tier TPM es por-minuto: forjas back-to-back agotan la ventana (el synth
# de la 2da degrada). Cada forja sola entra cómoda; basta espaciarlas para que arranquen en ventana
# fresca. 45s + maxRounds=1 (1 ronda alcanza ≥1 tool en los 3 targets) mantienen el costo y el TPM bajos.
INTER_FORGE_DELAY_S = int(os.environ.get("FORMAS_FORGE_DELAY_S", "45") or "0")

# ── JS: una forja por el consumidor UNIFICADO → resumen serializable (no el payload crudo) ──
_INSPECT_JS = """
async (p) => {
  // [identidad visual 6/6] la revisión antes de equipar ya no cuelga de un modo: aparece
  // SIEMPRE y espera un toque. `autoSeal` da ESE toque (sin destildar nada) para que un
  // verificador headless recorra el MISMO panel real que ve una persona, sin colgarse.
  window.__manual && window.__manual.configure({ autoSeal: true });
  const res = await window.__inspectAndEquip(p.args);
  const placed = window.__cuarto.placedTiles();
  const forged = placed.find(t => t.forged) || null;
  const counts = {};
  for (const e of (res.events||[])) counts[e.type] = (counts[e.type]||0) + 1;
  const slim = (t) => t ? { server:t.server, belt_ref:t.belt_ref, tools:t.tools, forged:!!t.forged } : null;
  return {
    ok: !!res.ok, path: res.path||null, server: res.server||null, tools: res.tools||[],
    reason: res.reason||null, eventCounts: counts, forgedPiece: slim(forged),
    sesionOk: (counts["sesion.ok"]||0), forjado: (counts["mcp.forjado"]||0),
    validadas: (counts["tool.validada"]||0),
  };
}
"""

# ── JS: maneja los SELECTORES de forma (barra + modal) — sin forjar, sólo wiring de UI ──
_UI_SELECTOR_JS = """
() => {
  const $ = (id) => document.getElementById(id);
  const out = {};
  const bar = $("inspectforma");
  out.bar_options = [...bar.options].map(o => ({v:o.value, disabled:o.disabled}));
  bar.value = "open"; bar.dispatchEvent(new Event("change"));
  out.open_hides_token = ($("inspecttoken").style.display === "none");
  bar.value = "token"; bar.dispatchEvent(new Event("change"));
  out.token_shows_token = ($("inspecttoken").style.display !== "none");
  // login en la barra → handoff: abre el modal "API cruda" preset a login + resetea la barra a token
  bar.value = "login"; bar.dispatchEvent(new Event("change"));
  out.login_handoff_open = $("byoOverlay").classList.contains("open");
  out.login_handoff_forma = $("byoFgForma").value;
  out.bar_reset_token = (bar.value === "token");
  // modal "API cruda": el selector conmuta los campos de cada forma
  const seg = [...$("byoTransport").children].find(b => b.dataset.v === "forge"); seg.click();
  $("byoFgForma").value = "open"; $("byoFgForma").dispatchEvent(new Event("change"));
  out.open_hides_wraps = $("byoFgTokenWrap").hidden && $("byoFgLoginWrap").hidden;
  $("byoFgForma").value = "login"; $("byoFgForma").dispatchEvent(new Event("change"));
  out.login_shows_loginwrap = (!$("byoFgLoginWrap").hidden) && $("byoFgTokenWrap").hidden;
  $("byoFgForma").value = "token"; $("byoFgForma").dispatchEvent(new Event("change"));
  out.token_shows_tokenwrap = (!$("byoFgTokenWrap").hidden) && $("byoFgLoginWrap").hidden;
  out.modal_options = [...$("byoFgForma").options].map(o => ({v:o.value, disabled:o.disabled}));
  $("byoClose").click();
  out.placed_is_array = Array.isArray(window.__cuarto.placedTiles());
  return out;
}
"""

_POKE_HINT = ("PokéAPI REST read-only (sin login). Endpoints de LECTURA (GET): "
              "GET /pokemon/{id} → un pokémon {id,name,height,weight} (sample id=1); "
              "GET /type/{id} → un tipo {id,name} (sample id=1); "
              "GET /ability/{id} → una habilidad (sample id=1). Proponé esas lecturas con su sample id.")
_DUMMY_HINT = ("API detrás de un login (la sesión ya viaja en el header Authorization Bearer). "
               "Endpoint de LECTURA (GET): GET /auth/me → el usuario actual {id, username, email, firstName}. "
               "Proponé esa tool de lectura (sin path params).")
_TMDB_HINT = ("TMDB v3 (api_key en query). GET /movie/{movie_id} → detalles de una película "
              "{title, runtime} (sample movie_id=550); GET /configuration → config del API. "
              "Proponé esas lecturas con su sample id.")


def _has(opts, value, disabled):
    return any(o.get("v") == value and bool(o.get("disabled")) == disabled for o in (opts or []))


def _post_forma_browser(back_port: int) -> int:
    """Golpea /v1/inspect/forge con forma=browser-oauth SIN session_key → debe ser 400 (necesita
    capturar la sesión primero). [3-browser-oauth] reemplazó el 501 que dejó 2f-formas: la Forma 3
    YA está implementada (el HUMANO hace login+2FA en /v1/inspect/session/browser y el forge reusa)."""
    data = json.dumps({"url": "https://example.com", "forma": "browser-oauth"}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{back_port}/v1/inspect/forge", data=data,
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _cuarto_diff() -> list[str]:
    """Archivos del Cuarto que cambiaron vs el fork base — para (d) modelo sin mutar."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "diff", "--name-only", FORK_BASE, "--",
             "product/app/design/cuarto"],
            capture_output=True, text=True, timeout=20)
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception as e:  # noqa: BLE001
        return [f"<git error: {e}>"]


def main() -> int:
    from playwright.sync_api import sync_playwright

    have_groq = bool(os.environ.get("GROQ_API_KEY"))
    tmdb_key = os.environ.get("FORGE_VERIFY_TMDB_KEY", "") or _recover_tmdb_from_vault()

    back_port, front_port = _free_port(), _free_port()
    print("═" * 72)
    print(f"  VERIFY 2f-formas (Cuarto) · backend :{back_port} · front :{front_port}")
    print(f"  Groq: {'SÍ' if have_groq else 'NO (forjas omitidas)'} · TMDB key (regresión token): "
          f"{'SÍ' if tmdb_key else 'NO'}")
    print("═" * 72)

    server, _ = _boot_server(back_port)
    _front = _boot_frontend(front_port, back_port)

    # ── (f) backend: forma=browser-oauth SIN session_key → 400 (Forma 3 implementada en Ola 3) ─
    browser_status = _post_forma_browser(back_port)
    pf = (browser_status == 400)
    print(f"  (f) POST /v1/inspect/forge forma=browser-oauth (sin session_key) → HTTP {browser_status} "
          f"(espera 400 · ya no 501; Forma 3 implementada) → {'✅' if pf else '❌'}")

    console_errors: list[str] = []
    R: dict = {}
    base = f"http://127.0.0.1:{front_port}"
    cuarto_url = base + CUARTO_PATH

    def forge_case(page, name, args, *, need_key=False):
        if not have_groq or (need_key and not tmdb_key):
            print(f"  ⚠ {name}: OMITIDO (falta GROQ_API_KEY o TMDB key)")
            return None
        page.goto(cuarto_url, wait_until="load")
        page.wait_for_function("() => window.__cuarto && window.__inspectAndEquip", timeout=15000)
        print(f"  · forjando {name} en vivo (dispatch MISS → Motor B + Groq)… ~20-120s")
        return page.evaluate(_INSPECT_JS, {"args": args})

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1320, "height": 880})
            page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

            # ── (a) ABIERTO · PokéAPI (sin credencial) ───────────────────────────────────
            a = forge_case(page, "ABIERTO/PokéAPI", {
                "service": "https://pokeapi.co/api/v2", "url": "https://pokeapi.co/api/v2",
                "forma": "open", "cred": None, "validatePath": "/",
                "apiShapeHint": _POKE_HINT, "maxRounds": 1, "seedCandidates": [], "synthAlias": "oss"})
            if a is not None:
                fp = a.get("forgedPiece") or {}
                pa = (a.get("ok") is True and a.get("path") == "forged"
                      and a.get("sesionOk", 0) >= 1 and a.get("forjado", 0) >= 1
                      and len(a.get("tools") or []) >= 1 and bool(fp.get("server")) and bool(fp.get("belt_ref")))
                R["(a) abierto → sesion.ok + forja (PokéAPI, sin cred)"] = pa
                print(f"    (a) ok={a.get('ok')} path={a.get('path')} sesion.ok={a.get('sesionOk')} "
                      f"forjado={a.get('forjado')} tools={len(a.get('tools') or [])} "
                      f"server={fp.get('server')} → {'✅' if pa else '❌'}")
                if not pa:
                    print(f"        reason={a.get('reason')!r} counts={a.get('eventCounts')}")
                if INTER_FORGE_DELAY_S:
                    time.sleep(INTER_FORGE_DELAY_S)

            # ── (b) LOGIN · DummyJSON (login real, sin 2FA) ──────────────────────────────
            b = forge_case(page, "LOGIN/DummyJSON", {
                "service": "https://dummyjson.com", "url": "https://dummyjson.com",
                "forma": "login", "loginPath": "/auth/login",
                "loginCredentials": {"username": "emilys", "password": "emilyspass"},
                "loginTokenWhere": "json", "loginTokenKey": "accessToken",
                "loginInjectWhere": "header", "loginInjectName": "Authorization",
                "validatePath": "/auth/me", "apiShapeHint": _DUMMY_HINT,
                "maxRounds": 1, "seedCandidates": [], "synthAlias": "oss"})
            if b is not None:
                fp = b.get("forgedPiece") or {}
                pb = (b.get("ok") is True and b.get("path") == "forged"
                      and b.get("sesionOk", 0) >= 1 and b.get("forjado", 0) >= 1
                      and len(b.get("tools") or []) >= 1 and bool(fp.get("server")) and bool(fp.get("belt_ref")))
                R["(b) login → sesion.ok + forja (DummyJSON, login API)"] = pb
                print(f"    (b) ok={b.get('ok')} path={b.get('path')} sesion.ok={b.get('sesionOk')} "
                      f"forjado={b.get('forjado')} tools={len(b.get('tools') or [])} "
                      f"server={fp.get('server')} → {'✅' if pb else '❌'}")
                if not pb:
                    print(f"        reason={b.get('reason')!r} counts={b.get('eventCounts')}")
                if INTER_FORGE_DELAY_S:
                    time.sleep(INTER_FORGE_DELAY_S)

            # ── (c) TOKEN · TMDB (REGRESIÓN de la forma de Ola 0) ────────────────────────
            c = forge_case(page, "TOKEN/TMDB", {
                "service": "https://api.themoviedb.org/3", "url": "https://api.themoviedb.org/3",
                "forma": "token", "cred": tmdb_key, "authIn": "query", "authParam": "api_key",
                "validatePath": "/configuration", "apiShapeHint": _TMDB_HINT,
                "maxRounds": 1, "seedCandidates": [], "synthAlias": "oss"}, need_key=True)
            if c is not None:
                fp = c.get("forgedPiece") or {}
                pc = (c.get("ok") is True and c.get("path") == "forged"
                      and c.get("sesionOk", 0) >= 1 and c.get("forjado", 0) >= 1
                      and len(c.get("tools") or []) >= 1 and bool(fp.get("server")))
                R["(c) token → sesion.ok + forja (TMDB · regresión)"] = pc
                print(f"    (c) ok={c.get('ok')} path={c.get('path')} sesion.ok={c.get('sesionOk')} "
                      f"forjado={c.get('forjado')} tools={len(c.get('tools') or [])} → {'✅' if pc else '❌'}")
                if not pc:
                    print(f"        reason={c.get('reason')!r} counts={c.get('eventCounts')}")

            # ── (e) los SELECTORES de forma (barra + modal) conmutan; browser deshabilitado ─
            page.goto(cuarto_url, wait_until="load")
            page.wait_for_function("() => window.__cuarto && document.getElementById('inspectforma')",
                                   timeout=15000)
            page.wait_for_timeout(1000)  # deja que el módulo termine de attachear los listeners (init async)
            ui = page.evaluate(_UI_SELECTOR_JS)
            bar_ok = (_has(ui["bar_options"], "open", False) and _has(ui["bar_options"], "token", False)
                      and _has(ui["bar_options"], "login", False) and _has(ui["bar_options"], "browser-oauth", False))
            modal_ok = (_has(ui["modal_options"], "open", False) and _has(ui["modal_options"], "token", False)
                        and _has(ui["modal_options"], "login", False) and _has(ui["modal_options"], "browser-oauth", False))
            pe = (bar_ok and modal_ok and ui["open_hides_token"] and ui["token_shows_token"]
                  and ui["login_handoff_open"] and ui["login_handoff_forma"] == "login" and ui["bar_reset_token"]
                  and ui["open_hides_wraps"] and ui["login_shows_loginwrap"] and ui["token_shows_tokenwrap"]
                  and ui["placed_is_array"])
            R["(e) selector de forma vivo (barra+modal); browser=Ola 3 (disabled)"] = pe
            print(f"  (e) barra={bar_ok} modal={modal_ok} open→token oculto={ui['open_hides_token']} "
                  f"login→handoff={ui['login_handoff_open']}/{ui['login_handoff_forma']} "
                  f"campos conmutan(open/login/token)={ui['open_hides_wraps']}/{ui['login_shows_loginwrap']}"
                  f"/{ui['token_shows_tokenwrap']} → {'✅' if pe else '❌'}")

            browser.close()
    finally:
        server.should_exit = True
        time.sleep(0.3)

    R["(f) browser-oauth sin session_key → 400 (Forma 3 implementada, ya no 501)"] = pf

    print("\n" + "─" * 72)
    print(f"  errores de consola: {len(console_errors)}")
    for e in console_errors:
        print(f"    ✗ {e}")
    R["(g) consola 0 errores"] = not console_errors

    # ── (d) modelo del Cuarto SIN mutar (sólo UI + consumidor cambiaron) ─────────────────
    diff = _cuarto_diff()
    allowed = {"product/app/design/cuarto/cuarto.pixi.html",
               "product/app/design/cuarto/cuarto.inspect.js"}
    untouched = set(diff) <= allowed
    R["(d) modelo del Cuarto sin mutar (render/models/scene intactos)"] = untouched
    print(f"  (d) cuarto/ cambiados vs {FORK_BASE}: {diff or '∅'} → {'✅' if untouched else '❌'}")

    print("═" * 72)
    for k, v in R.items():
        print(f"  {k:54s}: {'✅ VERDE' if v else '❌ ROJO'}")
    forges_present = all(k in R for k in (
        "(a) abierto → sesion.ok + forja (PokéAPI, sin cred)",
        "(b) login → sesion.ok + forja (DummyJSON, login API)",
        "(c) token → sesion.ok + forja (TMDB · regresión)"))
    allok = all(R.values()) and forges_present
    print("═" * 72)
    print(f"  TOTAL: {'✅ TODO VERDE — abierto + login + token vivas; browser=Ola 3 marcado' if allok else '❌ HAY ROJO o forja omitida'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
