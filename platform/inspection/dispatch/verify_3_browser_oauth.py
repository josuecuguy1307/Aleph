#!/usr/bin/env python3
"""
verify_3_browser_oauth.py — DONE-BAR de la rama 3-browser-oauth-entrada (la CUARTA forma).

La forma "browser-OAuth": cuando el target exige OAuth+2FA, se abre un navegador INSTRUMENTADO
donde el HUMANO hace login + el segundo factor a mano; el sistema captura la sesión resultante
(cookies, cifradas) y el Motor B la REUSA para forjar el MCP — con el cerebro OPUS (shim :8923),
no Groq. LÍNEA ROJA §2: el 2FA lo hace el HUMANO; el motor NUNCA lo automatiza.

Levanta uvicorn (puerto propio, NO :8091) con PUPPET_BRAIN_SHIM=1 y SIN GROQ_API_KEY, y prueba:

  (a) CAPTURA → sesion.ok: el navegador instrumentado captura la sesión humana (login+2FA) →
      sesion.capturada con cookies reales + session_key + la marca de la línea roja.
  (b) FORJA con OPUS: con esa session_key, el pipeline corre IGUAL (observar→sintetizar→validar→
      emitir) reusando la sesión (la cookie capturada VIAJA al target) y forja con Opus → mcp.forjado.
  (c) FALLO HONESTO: si la sesión no se captura (humano cancela / nada que capturar) → error, sin
      session_key; y forjar con una session_key sin sesión → session.error, sin sesion.ok ni forja
      (NADA de sesión fantasma).
  (d) REGRESIÓN: las otras 3 formas (abierto/login/token) siguen forjando/acquiriendo.
  (e) CAPAS BASE intactas: cuarto.render.js y cuarto.forge.js byte-idénticos al fork; el modelo de
      relaciones del Cuarto sin mutar (sólo cambian los archivos esperados de esta ola).
  + UI e2e (Playwright): la nueva forma vive en la entrada, captura+forja por la UI, 0 errores de consola.

EL 2FA REAL EXIGE UN HUMANO (by design, línea roja) → NO se puede full-automatizar. Para el harness,
PUPPET_BROWSER_SESSION_FIXTURE inyecta el storage_state que un login humano DEJARÍA (el "punto de
pausa donde interviene el humano", marcado explícito); ese seam vive SOLO bajo la env (en producto
no existe → SIEMPRE se abre el navegador real y el humano se loguea de verdad). El lanzamiento del
navegador REAL se ejercita aparte con `session_browser.py --live` y con RUN_REAL_BROWSER_SMOKE=1.

Uso:
    PUPPET_BRAIN_SHIM=1 product/backend/.venv/bin/python \\
      platform/inspection/dispatch/verify_3_browser_oauth.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
import urllib.request
from pathlib import Path

# ── cerebro OPUS (shim :8923), NO Groq — fijado ANTES de cualquier import del motor/modelos ──
os.environ["PUPPET_BRAIN_SHIM"] = "1"
os.environ.setdefault("PUPPET_BRAIN_SHIM_MODEL", "claude-code-opus-4.8")
os.environ.pop("GROQ_API_KEY", None)                 # línea roja del run: nada de Groq
os.environ["PUPPET_FORGE_ALLOW_SEED_PROBES"] = "1"   # seam de verificación (cookie-en-tránsito)
os.environ.setdefault("PUPPET_WORKERS", "0")

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
_APP = _REPO_ROOT / "product" / "app"
for p in (str(_BACKEND), str(_PLATFORM), str(_APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

from inspection.dispatch.selftest_dispatch_order import (  # noqa: E402
    _boot_server, _free_port, _recover_tmdb_from_vault)
from inspection.dispatch.verify_integra_ola1 import _boot_frontend  # noqa: E402

FORK_BASE = "8306e20"   # integra-ola2-entrada (el fork de esta rama)
PUPPET = "cuarto-3-browser-oauth"

HTTPBIN = "https://httpbin.org"
POKE = "https://pokeapi.co/api/v2"
DUMMY = "https://dummyjson.com"
TMDB = "https://api.themoviedb.org/3"

# Opus es buen forjador; igual le damos la FORMA del target para que proponga lecturas estables.
_HTTPBIN_HINT = ("httpbin REST read-only (sin login; la cookie de sesión ya viaja inyectada). "
                 "Endpoints de LECTURA (GET): GET /headers → los headers de tu request (incluye Cookie); "
                 "GET /ip → tu IP; GET /uuid → un uuid; GET /user-agent → tu UA. "
                 "Proponé esas lecturas (sin path params).")
_POKE_HINT = ("PokéAPI REST read-only (sin login). GET /pokemon/{id} → un pokémon (sample id=1); "
              "GET /type/{id} → un tipo (sample id=1); GET /ability/{id} → una habilidad (sample id=1). "
              "Proponé esas lecturas con su sample id.")
_DUMMY_HINT = ("API detrás de un login (la sesión viaja en Authorization Bearer). "
               "GET /auth/me → el usuario actual {id, username, email}. Proponé esa lectura (sin path params).")
_TMDB_HINT = ("TMDB v3 (api_key en query). GET /movie/{movie_id} → detalles (sample movie_id=550); "
              "GET /configuration → config. Proponé esas lecturas con su sample id.")


# ── SSE crudo (POST → text/event-stream) ────────────────────────────────────────────────────
def _stream(port: int, path: str, payload: dict, *, timeout: float = 240.0, echo: bool = True) -> list[dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers={"content-type": "application/json"}, method="POST")
    events: list[dict] = []
    cur = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if line.startswith("event:"):
                    cur = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    blob = line[len("data:"):].strip()
                    try:
                        ev = json.loads(blob)
                    except json.JSONDecodeError:
                        ev = {"type": cur, "_raw": blob}
                    events.append(ev)
                    if echo:
                        tag = (ev.get("server") or ev.get("server_name") or ev.get("nombre")
                               or ev.get("fase") or ev.get("session_key") or ev.get("url") or "")
                        print(f"   ◂ {str(ev.get('type')):22s} {str(tag)[:60]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        events.append({"type": "http.error", "status": e.code, "body": body})
        if echo:
            print(f"   ◂ HTTP {e.code}: {body}")
    return events


def _post_status(port: int, path: str, payload: dict) -> int:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _count(evs, t):
    return sum(1 for e in evs if e.get("type") == t)


def _first(evs, t):
    return next((e for e in evs if e.get("type") == t), None)


# ── preflight: el shim Opus :8923 debe estar VIVO y EMITIR una propuesta ────────────────────
def _preflight_shim() -> tuple[bool, str]:
    sys_p = ('Sos un sintetizador. Respondé SÓLO un JSON {"tools":[{"name":...,"endpoint":...,'
             '"method":"GET","sample_call":{}}]}.')
    usr = "api_base httpbin. Proponé 1 tool de lectura GET /uuid."
    body = {"model": os.environ["PUPPET_BRAIN_SHIM_MODEL"],
            "messages": [{"role": "system", "content": sys_p}, {"role": "user", "content": usr}],
            "max_tokens": 300, "temperature": 0}
    req = urllib.request.Request("http://127.0.0.1:8923/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=90).read().decode())
        content = (((d.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        ok = ("tools" in content) or ("function" in content) or ("endpoint" in content)
        return ok, f"model={d.get('model')} · emitió={'sí' if ok else 'no'} · {content[:90]}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# ── (e) capas base + modelo del Cuarto ──────────────────────────────────────────────────────
def _git(*args) -> str:
    import subprocess
    return subprocess.run(["git", "-C", str(_REPO_ROOT), *args],
                          capture_output=True, text=True, timeout=30).stdout


def _base_files_intact() -> tuple[bool, list[str], list[str]]:
    """render.js y forge.js byte-idénticos al fork; lista de archivos cuarto/ cambiados (esperados)."""
    intact = []
    for f in ("cuarto.render.js", "cuarto.forge.js", "cuarto.models.js", "cuarto.scene.schema.js"):
        rel = f"product/app/design/cuarto/{f}"
        base = _git("show", f"{FORK_BASE}:{rel}")
        cur = (_REPO_ROOT / rel).read_text()
        intact.append((f, base == cur))
    changed = [ln.strip() for ln in _git("diff", "--name-only", FORK_BASE, "--",
                                         "product/app/design/cuarto").splitlines() if ln.strip()]
    ok = all(v for _, v in intact)
    return ok, [f for f, v in intact if not v], changed


# ── caso de forja por dispatch (regresión de las 3 formas) ──────────────────────────────────
def _forge_case(port, label, payload) -> tuple[bool, dict]:
    print(f"\n  ── {label} ──")
    evs = _stream(port, "/v1/inspect/dispatch", payload)
    forjado = _first(evs, "mcp.forjado")
    sesion = _first(evs, "sesion.ok")
    info = {"sesion_ok": _count(evs, "sesion.ok"), "forjado": _count(evs, "mcp.forjado"),
            "validadas": _count(evs, "tool.validada"),
            "auth_form": (sesion or {}).get("auth_form"),
            "tools": len((forjado or {}).get("tools") or []),
            "degraded": _count(evs, "error")}
    return evs, info


def main() -> int:
    from playwright.sync_api import sync_playwright

    print("═" * 78)
    print("  VERIFY 3-browser-oauth · la CUARTA forma (navegador · OAuth+2FA · 2FA = HUMANO)")
    print("═" * 78)

    ok_shim, shim_detail = _preflight_shim()
    print(f"  preflight shim Opus :8923 → {shim_detail}")
    if not ok_shim:
        print("  ❌ el shim Opus :8923 no respondió/emitió — abortando (la forja necesita Opus, no Groq).")
        return 2
    print(f"  cerebro: shim Opus :8923 ({os.environ['PUPPET_BRAIN_SHIM_MODEL']}) · GROQ_API_KEY="
          f"{'(unset ✓)' if not os.environ.get('GROQ_API_KEY') else 'PRESENTE ✗'}")

    tmdb_key = os.environ.get("FORGE_VERIFY_TMDB_KEY", "") or _recover_tmdb_from_vault()
    back_port, front_port = _free_port(), _free_port()
    print(f"  backend :{back_port} · front :{front_port}\n")
    server, _ = _boot_server(back_port)
    _front = _boot_frontend(front_port, back_port)

    R: dict = {}
    SECRET = "brsek_" + uuid.uuid4().hex                  # cookie de sesión "humana" (rastreable)
    # Target del camino feliz = PokéAPI (read-only, MUY estable; el cerebro Opus forja ~8 tools).
    # El cookie capturado lleva domain=pokeapi.co → el loop lo inyecta en cada request (PokéAPI lo
    # ignora pero VIAJA; la prueba determinística de que la cookie capturada LLEGA al loop es (b2),
    # in-process, sin depender de un echo público flaky).
    POKE_HOST = "pokeapi.co"
    FULL_STATE = {"cookies": [{"name": "session", "value": SECRET, "domain": POKE_HOST,
                               "path": "/", "httpOnly": True}],
                  "origins": [{"origin": "https://" + POKE_HOST, "localStorage": [{"name": "csrf", "value": "z"}]}]}
    EMPTY_STATE = {"cookies": [], "origins": []}

    try:
        # ══ (a) CAPTURA → sesion.ok (fixture seam = el login+2FA que hace el HUMANO) ═══════════
        print("─" * 78)
        print("  (a) CAPTURA · navegador instrumentado captura la sesión humana (login+2FA)")
        print("─" * 78)
        os.environ["PUPPET_BROWSER_SESSION_FIXTURE"] = json.dumps(FULL_STATE)
        cap = _stream(back_port, "/v1/inspect/session/browser",
                      {"url": POKE, "login_url": POKE + "/login", "ready_url": "/dashboard",
                       "puppet_id": PUPPET})
        captured = _first(cap, "sesion.capturada")
        phases = [e.get("fase") for e in cap if e.get("type") == "browser.fase"]
        session_key = (captured or {}).get("session_key")
        pa = bool(captured and captured.get("ok") and (captured.get("cookie_count") or 0) >= 1
                  and session_key and "human_authenticat" in str(captured.get("red_line", ""))
                  and "esperando_humano" in phases)   # la fase del 2FA humano REALMENTE ocurrió
        R["(a) navegador captura la sesión humana → sesion.ok (cookies + línea roja)"] = pa
        print(f"  → ok={(captured or {}).get('ok')} cookies={(captured or {}).get('cookie_count')} "
              f"fases={phases} session_key={'sí' if session_key else 'no'} "
              f"red_line={'sí' if captured and 'human' in str(captured.get('red_line','')) else 'no'} "
              f"→ {'✅' if pa else '❌'}")

        # ══ (b) FORJA con OPUS reusando la sesión + handoff de la cookie capturada ════════════
        print("\n" + "─" * 78)
        print("  (b) FORJA con OPUS · el pipeline corre IGUAL reusando la sesión capturada")
        print("─" * 78)
        fb = _stream(back_port, "/v1/inspect/dispatch",
                     {"service": POKE, "url": POKE, "forma": "browser-oauth",
                      "session_key": session_key, "synth_alias": "brain",
                      "validate_path": "/", "api_shape_hint": _POKE_HINT,
                      "max_rounds": 2, "max_calls": 12, "puppet_id": PUPPET})
        sesion = _first(fb, "sesion.ok")
        forjado = _first(fb, "mcp.forjado")
        # ¿Opus propuso? (las propuestas llevan el model del cerebro)
        opus_models = {str(e.get("model")) for e in fb if e.get("type") == "tool.propuesta"}
        opus_forged = any(("opus" in m.lower() or "claude" in m.lower()) for m in opus_models)
        pb_forge = bool(sesion and sesion.get("auth_form") == "human_session"
                        and sesion.get("reused_session") is True and (sesion.get("cookie_count") or 0) >= 1
                        and forjado and len(forjado.get("tools") or []) >= 1
                        and _count(fb, "tool.validada") >= 1 and opus_forged)
        print(f"  → sesion.ok(auth={sesion and sesion.get('auth_form')},reused={sesion and sesion.get('reused_session')},"
              f"cookies={sesion and sesion.get('cookie_count')}) forjado_tools={len((forjado or {}).get('tools') or [])} "
              f"validadas={_count(fb,'tool.validada')} opus={opus_forged}({opus_models}) → {'✅' if pb_forge else '❌'}")

        # (b2) HANDOFF determinístico (sin echo público): el MISMO provider reuse-only que arma el
        # Motor B carga, por su session_key, EXACTAMENTE la cookie humana capturada → eso es lo que
        # el loop consume e inyecta en cada request (LiveHTTP: `Cookie: session=…`). Cero-teatro.
        from inspection import contracts as C  # noqa: E402
        from inspection.loop.session_browser import HumanBrowserSession  # noqa: E402
        handoff_prov = HumanBrowserSession(POKE, C.Principal(anon_id="verify-b2"), "verify-b2",
                                           login_url=POKE, storage_key=session_key)
        try:
            hs = handoff_prov.acquire()
            pb_handoff = (hs.form is C.AuthForm.HUMAN_SESSION and hs.cookies.get("session") == SECRET
                          and hs.meta.get("reused_session") is True)
            print(f"  → handoff in-process: form={hs.form.value} cookie['session']=={'SECRET✓' if hs.cookies.get('session')==SECRET else hs.cookies} "
                  f"reused={hs.meta.get('reused_session')} → {'✅' if pb_handoff else '❌'}")
        except Exception as e:  # noqa: BLE001
            pb_handoff = False
            print(f"  → handoff in-process FALLÓ: {type(e).__name__}: {e} → ❌")
        pb = pb_forge and pb_handoff
        R["(b) reusa la sesión humana (cookie capturada) + forja con OPUS → mcp.forjado"] = pb

        # ══ (c) FALLO HONESTO · cancelar/sin-captura → sin sesión fantasma ════════════════════
        print("\n" + "─" * 78)
        print("  (c) FALLO HONESTO · sin sesión real no hay forja (cero-teatro)")
        print("─" * 78)
        # (c1) el humano cancela / nada que capturar → error, sin sesion.capturada
        os.environ["PUPPET_BROWSER_SESSION_FIXTURE"] = json.dumps(EMPTY_STATE)
        c1 = _stream(back_port, "/v1/inspect/session/browser",
                     {"url": HTTPBIN, "login_url": HTTPBIN + "/login", "ready_url": "/dashboard"})
        c1_err = _first(c1, "error")
        pc1 = bool(c1_err and not _first(c1, "sesion.capturada"))
        # (c2) forjar con una session_key SIN sesión guardada → session.error, sin sesion.ok ni forja
        os.environ.pop("PUPPET_BROWSER_SESSION_FIXTURE", None)   # nada de fixture: reuse-only puro
        c2 = _stream(back_port, "/v1/inspect/dispatch",
                     {"service": HTTPBIN, "url": HTTPBIN, "forma": "browser-oauth",
                      "session_key": f"browseroauth::httpbin::{uuid.uuid4().hex}",  # nunca capturada
                      "synth_alias": "brain", "validate_path": "/headers", "max_rounds": 1})
        pc2 = bool(_count(c2, "error") >= 1 and _count(c2, "sesion.ok") == 0
                   and _count(c2, "mcp.forjado") == 0)
        pc = pc1 and pc2
        R["(c) cancelar/sin-captura → fallo honesto, sin sesión fantasma (no forja)"] = pc
        print(f"  → (c1) captura vacía: error={bool(c1_err)} sin_captura={not _first(c1,'sesion.capturada')} "
              f"· (c2) forge sin sesión: error={_count(c2,'error')} sesion.ok={_count(c2,'sesion.ok')} "
              f"forjado={_count(c2,'mcp.forjado')} → {'✅' if pc else '❌'}")

        # ══ (d) REGRESIÓN · las otras 3 formas siguen andando ════════════════════════════════
        print("\n" + "─" * 78)
        print("  (d) REGRESIÓN · abierto / login / token siguen acquiriendo+forjando (con Opus)")
        print("─" * 78)
        # abierto · PokéAPI (sin cred) — forja completa
        _o, oinfo = _forge_case(back_port, "ABIERTO/PokéAPI", {
            "service": POKE, "url": POKE, "forma": "open", "validate_path": "/",
            "synth_alias": "brain", "api_shape_hint": _POKE_HINT, "max_rounds": 1, "max_calls": 10})
        p_open = (oinfo["sesion_ok"] >= 1 and oinfo["forjado"] >= 1 and oinfo["tools"] >= 1
                  and oinfo["auth_form"] == "open")
        print(f"     abierto → {oinfo} → {'✅' if p_open else '❌'}")
        # login · DummyJSON (login API real, sin 2FA) — al menos sesion.ok (provider POSTea+inyecta)
        _l, linfo = _forge_case(back_port, "LOGIN/DummyJSON", {
            "service": DUMMY, "url": DUMMY, "forma": "login", "login_path": "/auth/login",
            "login_credentials": {"username": "emilys", "password": "emilyspass"},
            "login_token_where": "json", "login_token_key": "accessToken",
            "login_inject_where": "header", "login_inject_name": "Authorization",
            "validate_path": "/auth/me", "synth_alias": "brain", "api_shape_hint": _DUMMY_HINT,
            "max_rounds": 1, "max_calls": 10})
        p_login = (linfo["sesion_ok"] >= 1 and linfo["auth_form"] in ("login_api", "login"))
        print(f"     login → {linfo} → {'✅' if p_login else '❌'}")
        # token · TMDB (regresión Forma 1) — sólo si hay key
        if tmdb_key:
            _t, tinfo = _forge_case(back_port, "TOKEN/TMDB", {
                "service": TMDB, "url": TMDB, "forma": "token", "credential": tmdb_key,
                "auth_in": "query", "auth_param": "api_key", "validate_path": "/configuration",
                "synth_alias": "brain", "api_shape_hint": _TMDB_HINT, "max_rounds": 1, "max_calls": 10})
            p_token = (tinfo["sesion_ok"] >= 1 and tinfo["auth_form"] == "token_query")
            print(f"     token → {tinfo} → {'✅' if p_token else '❌'}")
        else:
            p_token = True
            print("     token → SKIP (sin TMDB key en vault/env) — no es regresión de esta ola")
        pd = p_open and p_login and p_token
        R["(d) regresión: abierto+login+token siguen andando (sesion.ok + forja)"] = pd

        # ══ UI e2e · la nueva forma en la entrada, captura+forja por la UI, 0 consola ════════
        print("\n" + "─" * 78)
        print("  (UI) la CUARTA forma vive en la entrada · captura+forja por la UI · 0 consola")
        print("─" * 78)
        os.environ["PUPPET_BROWSER_SESSION_FIXTURE"] = json.dumps(FULL_STATE)   # seam del 2FA humano
        cuarto_url = f"http://127.0.0.1:{front_port}/cuarto/cuarto.pixi.html?puppet={PUPPET}"
        console_errors: list[str] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1320, "height": 880})
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.goto(cuarto_url, wait_until="load")
            page.wait_for_function("() => window.__cuarto && document.getElementById('inspectforma')",
                                   timeout=15000)
            page.wait_for_timeout(900)   # init async termina de attachear listeners

            # selector vivo: la 4ta forma está en barra + modal, HABILITADA
            ui = page.evaluate("""() => {
              const $ = (id) => document.getElementById(id);
              const bar = $("inspectforma");
              const barOpts = [...bar.options].map(o => ({v:o.value, disabled:o.disabled}));
              // barra → navegador hace handoff al modal "API cruda" preset a browser-oauth
              bar.value = "browser-oauth"; bar.dispatchEvent(new Event("change"));
              const handoffOpen = $("byoOverlay").classList.contains("open");
              const modalForma = $("byoFgForma").value;
              const browserWrapShown = !$("byoFgBrowserWrap").hidden;
              const modalOpts = [...$("byoFgForma").options].map(o => ({v:o.value, disabled:o.disabled}));
              return { barOpts, modalOpts, handoffOpen, modalForma, browserWrapShown };
            }""")
            has = lambda opts, v: any(o["v"] == v and not o["disabled"] for o in opts)
            ui_selector_ok = (has(ui["barOpts"], "browser-oauth") and has(ui["modalOpts"], "browser-oauth")
                              and ui["handoffOpen"] and ui["modalForma"] == "browser-oauth"
                              and ui["browserWrapShown"])
            print(f"     selector: barra/modal browser-oauth habilitado + handoff + campos = {ui_selector_ok}  {ui}")

            # captura+forja POR LA UI: llená el modal (ya abierto en browser-oauth) y dale al botón.
            res_ui = page.evaluate("""async (p) => {
              const $ = (id) => document.getElementById(id);
              $("byoFgUrl").value = p.url;
              $("byoFgLoginUrl").value = p.url + "/login";
              $("byoFgReadyKind").value = "url"; $("byoFgReady").value = "/dashboard";
              $("byoFgValidate").value = "/"; $("byoFgHint").value = p.hint;
              $("byoSubmit").click();
              // esperá hasta que el flujo (captura→forja) deje sus hooks de verificación
              const t0 = Date.now();
              while (Date.now() - t0 < 180000) {
                if (window.__lastForge) break;
                await new Promise(r => setTimeout(r, 400));
              }
              const placed = window.__cuarto.placedTiles();
              const forged = placed.find(t => t.forged) || null;
              return {
                cap: window.__lastCapture ? { ok: !!window.__lastCapture.ok,
                       session_key: !!window.__lastCapture.session_key,
                       cookies: window.__lastCapture.cookie_count } : null,
                forge: window.__lastForge ? { ok: !!window.__lastForge.ok, path: window.__lastForge.path,
                       server: window.__lastForge.server, tools: (window.__lastForge.tools||[]).length,
                       reason: window.__lastForge.reason } : null,
                forgedPiece: forged ? { server: forged.server, belt_ref: forged.belt_ref,
                       tools: forged.tools, forged: !!forged.forged } : null,
              };
            }""", {"url": POKE, "hint": _POKE_HINT})
            print(f"     UI captura={res_ui.get('cap')} forja={res_ui.get('forge')} pieza={res_ui.get('forgedPiece')}")
            fp = res_ui.get("forgedPiece") or {}
            forge_ui = res_ui.get("forge") or {}
            cap_ui = res_ui.get("cap") or {}
            ui_flow_ok = (bool(cap_ui.get("ok")) and bool(cap_ui.get("session_key"))
                          and bool(forge_ui.get("ok")) and forge_ui.get("path") == "forged"
                          and (forge_ui.get("tools") or 0) >= 1 and bool(fp.get("server")) and bool(fp.get("forged")))
            browser.close()
        ui_ok = ui_selector_ok and ui_flow_ok and not console_errors
        R["(UI) 4ta forma en la entrada + captura/forja por la UI + 0 errores de consola"] = ui_ok
        print(f"     selector_ok={ui_selector_ok} flujo_ok={ui_flow_ok} console_errors={console_errors[:3]} "
              f"→ {'✅' if ui_ok else '❌'}")

        # ══ (e) CAPAS BASE intactas + modelo del Cuarto sin mutar ═══════════════════════════
        print("\n" + "─" * 78)
        print("  (e) capas base byte-idénticas + modelo del Cuarto sin mutar")
        print("─" * 78)
        base_ok, mutated, changed = _base_files_intact()
        ALLOWED = {"product/app/design/cuarto/cuarto.inspect.js",
                   "product/app/design/cuarto/cuarto.browser.js",
                   "product/app/design/cuarto/cuarto.pixi.html"}
        only_expected = set(changed) <= ALLOWED
        pe = base_ok and only_expected
        R["(e) render.js/forge.js byte-idénticos + sólo cambian archivos esperados del Cuarto"] = pe
        print(f"  → base intactas={base_ok} (mutadas={mutated}) · cuarto/ cambiados={changed} "
              f"⊆ esperados={only_expected} → {'✅' if pe else '❌'}")

    finally:
        server.should_exit = True
        time.sleep(0.3)

    print("\n" + "═" * 78)
    allok = all(R.values())
    for k, v in R.items():
        print(f"   {'✅' if v else '❌'}  {k}")
    print("═" * 78)
    # [H3] La nota va ARRIBA del veredicto: la ÚLTIMA línea de una vara es lo que lee un
    # `tail -1` para decidir un merge.
    print("  NOTA: el 2FA real lo hace el HUMANO (línea roja §2). El seam de captura "
          "(PUPPET_BROWSER_SESSION_FIXTURE) marca ese punto; el navegador REAL se ejercita con "
          "`session_browser.py --live` y RUN_REAL_BROWSER_SMOKE=1.")
    print(f"  {'✅ TODO VERDE — la CUARTA forma (browser-OAuth) capturó+forjó con OPUS; 3 formas intactas' if allok else '❌ HAY ROJO'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
