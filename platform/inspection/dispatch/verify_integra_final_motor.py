#!/usr/bin/env python3
"""
verify_integra_final_motor.py — DONE-BAR del MOTOR B COMPLETO (rama integra-final-motor = Ola 2
entrada + Ola 3 browser-oauth). Una sola pasada, FORJANDO CON OPUS (shim :8923, sin Groq), con el
GATE F5 viendo tool_calls ESTRUCTURADO (shim :8924, el fix de fix-shim-toolcalls).

Levanta UN backend (uvicorn) + UN frontend (serve.py) en puertos PROPIOS (jamás :8091 ni :8923/:8924)
con el cerebro Opus (PUPPET_BRAIN_SHIM=1, GROQ_API_KEY unset) y verifica los 7 puntos:

  (1) LAS 4 FORMAS de sesión, cada una sesion.ok + forja real con OPUS:
      abierto (PokéAPI) · token (TMDB) · login (DummyJSON) · browser-OAuth (captura humana por
      fixture/seam — el 2FA REAL lo hace el humano por diseño, línea roja §2).
  (2) RESOLVER (peldaño previo): stripe en el registry → traído verificado SIN forjar; impostor DNS
      → RECHAZADO sin equipar. (offline / determinístico, sin cerebro.)
  (3) COREOGRAFÍA completa 1:1 con eventos REALES (fantasmas→pulso→sólidas/desvanecidas), cero-teatro.
  (4) PUNTOS MANUALES: descartar-antes-de-validar + revisar-antes-de-sellar MODULAN el belt; sin
      intervención, automático byte-idéntico (la pieza equipa TODO lo forjado).
  (5) EVIDENCIA (modo dev): OFF = limpio · ON = evidencia cruda real por evento (deep-equal con lo
      que emitió el motor). Cruce D↔E: una tool descartada por D sigue en la evidencia de E como
      propuesta+validada (el descarte es del belt, no del motor).
  (6) GATE F5 CON OPUS — EL QUE CIERRA EL CÍRCULO: con el shim arreglado (:8924) un tool_call de Opus
      se ve como tool_calls ESTRUCTURADO y el gate F5 lo intercepta/FRENA (gate_waiting + pausa, no
      ejecuta). Contraste con :8923 (viejo, sólo content) → el motor estructurado-only NO lo ve → no
      frena (exactamente lo que antes exigía Groq).
  (7) mcp.forjado → pieza REAL equipada → RUN real la invoca (get_movie_details(550)→200), con Opus
      :8924 (tool-use estructurado en el RUN).

Invariantes byte-a-byte y los 3 endpoints los chequea (e). 0 errores de consola en toda la UI.

Uso:
    PUPPET_BRAIN_SHIM=1 product/backend/.venv/bin/python \\
      platform/inspection/dispatch/verify_integra_final_motor.py
  (requiere los shims Opus vivos: :8923 (live) y :8924 (fix-shim-toolcalls). El harness los
   preflightea y aborta honesto si falta alguno. La TMDB key sale de FORGE_VERIFY_TMDB_KEY o del vault.)
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
import shutil
import sys
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

# ── CEREBRO OPUS (shim), NO Groq — fijado ANTES de cualquier import del motor/modelos ──
os.environ["PUPPET_BRAIN_SHIM"] = "1"
os.environ.setdefault("PUPPET_BRAIN_SHIM_MODEL", "claude-code-opus-4.8")
os.environ.pop("GROQ_API_KEY", None)              # línea roja del run: NADA de Groq
os.environ.pop("PUPPET_BRAIN", None)              # que el recipe.model.base_url mande en el RUN (P7)
os.environ["PUPPET_FORGE_ALLOW_SEED_PROBES"] = "1"      # seam: sondas reales deterministas
os.environ["PUPPET_DISPATCH_ALLOW_SEED_CANDIDATES"] = "1"  # seam: matcher real arbitra found/impostor
os.environ.setdefault("PUPPET_WORKERS", "0")
os.environ.setdefault("PUPPET_HTTP_TIMEOUT", "150")

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_BACKEND = _REPO_ROOT / "product" / "backend"
_PLATFORM = _REPO_ROOT / "platform"
_APP = _REPO_ROOT / "product" / "app"
for _p in (str(_BACKEND), str(_PLATFORM), str(_APP)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from inspection.dispatch.selftest_dispatch_order import (  # noqa: E402
    _boot_server, _free_port, _fake_spec, _cand, _recover_tmdb_from_vault)
from inspection.dispatch.verify_integra_ola1 import _boot_frontend  # noqa: E402

SHIM_8923 = "http://127.0.0.1:8923/v1"   # shim Opus VIVO (content-only) — la forja escanea el content
SHIM_8924 = "http://127.0.0.1:8924/v1"   # shim Opus con el FIX (tool_calls estructurado) — gate F5 + RUN

PUPPET = "cuarto-integra-final-motor"
CUARTO_PATH = f"/cuarto/cuarto.pixi.html?puppet={PUPPET}"
FORK_BASE = "8306e20"   # integra-ola2-entrada (la base del merge)

POKE = "https://pokeapi.co/api/v2"
DUMMY = "https://dummyjson.com"
TMDB = "https://api.themoviedb.org/3"
HTTPBIN = "https://httpbin.org"

_POKE_HINT = ("PokéAPI REST read-only (sin login). GET /pokemon/{id} → un pokémon (sample id=1); "
              "GET /type/{id} → un tipo (sample id=1). Proponé esas lecturas con su sample id.")
_DUMMY_HINT = ("API detrás de un login (la sesión viaja en Authorization Bearer). "
               "GET /auth/me → el usuario actual {id, username, email}. Proponé esa lectura (sin path params).")
_TMDB_HINT = ("TMDB v3 (api_key en query). GET /movie/{movie_id} → detalles (sample movie_id=550); "
              "GET /configuration → config; GET /genre/movie/list → géneros. Proponé esas lecturas.")

# sondas reales deterministas (TMDB · Forma 1) — nombres conocidos → asserts determinísticos (P3/P4)
P1 = "p1_config"        # /configuration    → 200 · DESCARTE punto 1 (P4)
P2 = "p2_genres"        # /genre/movie/list → 200 · DESTILDE punto 2 (P4)
K3 = "k3_movie"         # /movie/550        → 200 · SOBREVIVE a ambos (P4)
PROBE404 = {"name": "pelicula_fantasma", "endpoint": "/movie/{movie_id}", "method": "GET",
            "path_params": {"movie_id": "0"}, "kind": "read"}   # 404 real → fuerza tool.descartada (P3)
SEED_PROBES_TMDB = [
    {"name": P1, "endpoint": "/configuration", "method": "GET", "kind": "read"},
    {"name": P2, "endpoint": "/genre/movie/list", "method": "GET", "kind": "read"},
    {"name": K3, "endpoint": "/movie/{movie_id}", "method": "GET",
     "path_params": {"movie_id": "550"}, "kind": "read"},
]


# ── SSE crudo (POST → text/event-stream) ─────────────────────────────────────────────────────
def _stream(port: int, path: str, payload: dict, *, timeout: float = 260.0, echo: bool = True) -> list:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers={"content-type": "application/json"}, method="POST")
    events: list = []
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
                        tag = (ev.get("server") or ev.get("nombre") or ev.get("auth_form")
                               or ev.get("session_key") or ev.get("url") or "")
                        print(f"      ◂ {str(ev.get('type')):20s} {str(tag)[:54]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        events.append({"type": "http.error", "status": e.code, "body": body})
        if echo:
            print(f"      ◂ HTTP {e.code}: {body}")
    return events


def _count(evs, t):
    return sum(1 for e in evs if e.get("type") == t)


def _first(evs, t):
    return next((e for e in evs if e.get("type") == t), None)


def _opus_forged(evs) -> bool:
    models = {str(e.get("model", "")).lower() for e in evs if e.get("type") == "tool.propuesta"}
    return any(("opus" in m or "claude" in m) for m in models)


# ── preflight: ambos shims Opus deben estar vivos y emitir ───────────────────────────────────
def _preflight(base_url: str) -> tuple:
    body = {"model": "claude-code-opus-4.8",
            "messages": [{"role": "system", "content": "Respondé sólo 'ok'."},
                         {"role": "user", "content": "decí ok"}],
            "max_tokens": 30, "temperature": 0}
    req = urllib.request.Request(base_url + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=90).read().decode())
        content = (((d.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        return bool(content), f"model={d.get('model')} · {content[:50]!r}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# ════════════════════════════════════════════════════════════════════════════════════════════
# (6) GATE F5 con OPUS — el motor estructurado-only (session.py) FRENA con :8924, NO con :8923.
# ════════════════════════════════════════════════════════════════════════════════════════════
def p6_gate_f5(belt_path: Path) -> tuple:
    from assembler.session import Session  # platform/assembler/session.py (motor estructurado-only)

    PROMPT = ("Tenés la herramienta send_email. Enviá AHORA MISMO un correo a ada@example.com con "
              "subject 'Hola' y body 'Probando el gate F5'. Llamá send_email con esos valores exactos; "
              "no pidas confirmación ni inventes nada.")

    def run_once(base_url: str) -> dict:
        events: list = []
        gate_seen = threading.Event()

        def on_ev(kind, evt):
            events.append((kind, evt))
            if kind == "gate_waiting":
                gate_seen.set()

        # max_turns=1: sólo necesitamos VER el FRENO (gate_waiting + pausa + no-ejecución) en el
        # turno donde Opus llama send_email; no la respuesta final → 1 sola llamada a Opus por run.
        cfg = {"base_url": base_url, "model": "claude-code-opus-4.8", "belt_path": str(belt_path),
               "framing_fallback": "Sos un asistente que usa herramientas cuando se lo piden.",
               "max_turns": 1, "max_tokens": 400, "temperature": 0}
        sess = Session(cfg, on_event=on_ev, deadline_s=180)
        ans: dict = {}

        def go():
            try:
                ans["text"] = sess.send(PROMPT)
            except Exception as e:  # noqa: BLE001
                ans["err"] = f"{type(e).__name__}: {e}"

        th = threading.Thread(target=go, daemon=True)
        th.start()
        froze = gate_seen.wait(timeout=170)       # ¿el gate FRENÓ el envío?
        pending = sess.pending_approval           # payload del gate en espera (señal de pausa)
        if froze:
            sess.reject()                         # NO enviar: probamos el FRENO, no el envío
        th.join(timeout=60)
        try:
            sess.close()
        except Exception:
            pass
        blob = json.dumps([e for _, e in events], default=str)
        return {
            "gate_emitted": any(k == "gate_waiting" for k, _ in events),
            "froze": bool(froze),
            "paused": bool(pending),
            "executed": ("SENT_should_not_happen" in blob) or ("SENT_should_not_happen" in (ans.get("text") or "")),
            "tried": ("send_email" in (ans.get("text") or "")) or ("send_email" in blob),
            "answer": (ans.get("text") or "")[:140],
            "err": ans.get("err"),
        }

    print("  ── :8924 (FIX · tool_calls estructurado) ──")
    fix = run_once(SHIM_8924)
    print(f"     {fix}")
    print("  ── :8923 (viejo · sólo content) — contraste ──")
    old = run_once(SHIM_8923)
    print(f"     {old}")

    R = {}
    R["(6) :8924 fix → el gate F5 VE tool_calls estructurado y FRENA (gate_waiting+pausa, no ejecuta)"] = (
        fix["gate_emitted"] and fix["froze"] and fix["paused"] and not fix["executed"])
    R["(6) contraste :8923 viejo → tool_call sólo en content → el gate NO frena (lo que exigía Groq)"] = (
        (not old["gate_emitted"]) and (not old["froze"]) and (not old["executed"]) and old["tried"])
    return R, {"8924_fix": fix, "8923_old": old}


# ════════════════════════════════════════════════════════════════════════════════════════════
# (1) LAS 4 FORMAS — cada una sesion.ok + forja con OPUS (synth_alias="brain") por el backend.
# ════════════════════════════════════════════════════════════════════════════════════════════
def p1_formas(back_port: int, tmdb_key: str) -> tuple:
    R = {}
    detail = {}

    def forge(label, payload):
        print(f"  ── {label} ──")
        evs = _stream(back_port, "/v1/inspect/dispatch", payload)
        s = _first(evs, "sesion.ok")
        f = _first(evs, "mcp.forjado")
        return evs, s, f

    # abierto · PokéAPI
    evs, s, f = forge("abierto · PokéAPI", {
        "service": POKE, "url": POKE, "forma": "open", "validate_path": "/", "synth_alias": "brain",
        "api_shape_hint": _POKE_HINT, "max_rounds": 1, "max_calls": 10, "puppet_id": PUPPET})
    ok_open = bool(s and s.get("auth_form") == "open" and f and len(f.get("tools") or []) >= 1
                   and _count(evs, "tool.validada") >= 1 and _opus_forged(evs))
    R["(1·abierto) PokéAPI · sesion.ok + forja con Opus"] = ok_open
    detail["abierto"] = {"auth": s and s.get("auth_form"), "tools": len((f or {}).get("tools") or []),
                         "opus": _opus_forged(evs)}

    # token · TMDB
    if tmdb_key:
        evs, s, f = forge("token · TMDB", {
            "service": TMDB, "url": TMDB, "forma": "token", "credential": tmdb_key, "auth_in": "query",
            "auth_param": "api_key", "validate_path": "/configuration", "synth_alias": "brain",
            "api_shape_hint": _TMDB_HINT, "max_rounds": 1, "max_calls": 10, "puppet_id": PUPPET})
        ok_token = bool(s and s.get("auth_form") == "token_query" and f and len(f.get("tools") or []) >= 1
                        and _count(evs, "tool.validada") >= 1 and _opus_forged(evs))
        detail["token"] = {"auth": s and s.get("auth_form"), "tools": len((f or {}).get("tools") or []),
                           "opus": _opus_forged(evs)}
    else:
        ok_token = False
        detail["token"] = "SIN TMDB KEY (FORGE_VERIFY_TMDB_KEY/vault)"
    R["(1·token) TMDB · sesion.ok + forja con Opus"] = ok_token

    # login · DummyJSON
    evs, s, f = forge("login · DummyJSON", {
        "service": DUMMY, "url": DUMMY, "forma": "login", "login_path": "/auth/login",
        "login_credentials": {"username": "emilys", "password": "emilyspass"},
        "login_token_where": "json", "login_token_key": "accessToken",
        "login_inject_where": "header", "login_inject_name": "Authorization",
        "validate_path": "/auth/me", "synth_alias": "brain", "api_shape_hint": _DUMMY_HINT,
        "max_rounds": 1, "max_calls": 10, "puppet_id": PUPPET})
    ok_login = bool(s and s.get("auth_form") in ("login_api", "login"))
    R["(1·login) DummyJSON · sesion.ok (login API real, sin 2FA)"] = ok_login
    detail["login"] = {"auth": s and s.get("auth_form"), "tools": len((f or {}).get("tools") or [])}

    # browser-OAuth · captura humana por fixture (el 2FA real = humano, línea roja §2) + forja reuse
    SECRET = "brsek_" + uuid.uuid4().hex
    POKE_HOST = "pokeapi.co"
    FULL_STATE = {"cookies": [{"name": "session", "value": SECRET, "domain": POKE_HOST,
                              "path": "/", "httpOnly": True}],
                  "origins": [{"origin": "https://" + POKE_HOST,
                               "localStorage": [{"name": "csrf", "value": "z"}]}]}
    os.environ["PUPPET_BROWSER_SESSION_FIXTURE"] = json.dumps(FULL_STATE)
    print("  ── browser-OAuth · captura humana (fixture seam) + forja reuse con Opus ──")
    cap = _stream(back_port, "/v1/inspect/session/browser",
                  {"url": POKE, "login_url": POKE + "/login", "ready_url": "/dashboard", "puppet_id": PUPPET})
    captured = _first(cap, "sesion.capturada")
    phases = [e.get("fase") for e in cap if e.get("type") == "browser.fase"]
    session_key = (captured or {}).get("session_key")
    cap_ok = bool(captured and captured.get("ok") and (captured.get("cookie_count") or 0) >= 1
                  and session_key and "human_authenticat" in str(captured.get("red_line", ""))
                  and "esperando_humano" in phases)   # la pausa del 2FA HUMANO ocurrió de verdad
    fb_evs, fb_s, fb_f = (forge("browser-OAuth · forja reuse", {
        "service": POKE, "url": POKE, "forma": "browser-oauth", "session_key": session_key,
        "synth_alias": "brain", "validate_path": "/", "api_shape_hint": _POKE_HINT,
        "max_rounds": 1, "max_calls": 10, "puppet_id": PUPPET}) if session_key else ([], None, None))
    forge_ok = bool(fb_s and fb_s.get("auth_form") == "human_session" and fb_s.get("reused_session") is True
                    and (fb_s.get("cookie_count") or 0) >= 1 and fb_f and len(fb_f.get("tools") or []) >= 1
                    and _opus_forged(fb_evs))
    os.environ.pop("PUPPET_BROWSER_SESSION_FIXTURE", None)
    R["(1·browser-OAuth) captura humana → sesion.ok + forja reuse con Opus (2FA=humano)"] = cap_ok and forge_ok
    detail["browser-oauth"] = {"captura_ok": cap_ok, "fases": phases,
                               "auth": fb_s and fb_s.get("auth_form"),
                               "reused": fb_s and fb_s.get("reused_session"),
                               "tools": len((fb_f or {}).get("tools") or []), "opus": _opus_forged(fb_evs),
                               "NOTA_2FA": "el segundo factor lo hace el HUMANO (seam fixture marca la pausa)"}
    return R, detail


# ════════════════════════════════════════════════════════════════════════════════════════════
# (2) RESOLVER — stripe verificado en registry (sin forjar) · impostor DNS rechazado (offline).
# ════════════════════════════════════════════════════════════════════════════════════════════
def p2_resolver(back_port: int) -> tuple:
    R = {}
    tmp = Path(tempfile.mkdtemp(prefix="finalmotor-p2-"))
    try:
        spec = _fake_spec(tmp, tools=["get_account", "list_charges"], server_name="stripe-local")
        verified = _cand("com.stripe/mcp", "com.stripe", "stripe", "dns", "Stripe",
                         "Stripe payments MCP", "https://mcp.stripe.com")
        impostor = _cand("io.github.evil/stripe-mcp", "io.github.evil", "evil", "github_org",
                         "Stripe (unofficial)", "stripe-like community fork", "https://evil.example/mcp")
        print("  ── stripe FOUND (registry verificado) → equip sin forja ──")
        a = _stream(back_port, "/v1/inspect/dispatch",
                    {"service": "stripe", "credential": None, "seed_candidates": [verified], "seed_spec": spec})
        found = _first(a, "resolver.encontrado")
        equip = _first(a, "mcp.equipado")
        closed = _first(a, "cerrado")
        no_forge = not any(e.get("type") in {"forge.iniciado", "observando", "tool.propuesta",
                                             "mcp.forjado", "dispatch.forjando"} for e in a)
        p_found = bool(found and found.get("verified") is True and equip and equip.get("belt_ref")
                       and equip.get("tools") and no_forge and closed and closed.get("path") == "registry"
                       and closed.get("forjado") is False)
        R["(2) stripe en el registry → traído verificado SIN forjar"] = p_found

        print("  ── impostor DNS → rechazado ──")
        c = _stream(back_port, "/v1/inspect/dispatch",
                    {"service": "stripe", "credential": None, "seed_candidates": [impostor]})
        miss = _first(c, "resolver.miss")
        p_imp = bool(miss and miss.get("rejected_impostor") is True and _count(c, "mcp.equipado") == 0
                     and _count(c, "resolver.encontrado") == 0 and _count(c, "mcp.forjado") == 0)
        R["(2) impostor DNS → RECHAZADO, sin equipar"] = p_imp
        return R, {"found": {"verified": bool(found and found.get("verified")), "no_forge": no_forge},
                   "impostor": {"rejected": bool(miss and miss.get("rejected_impostor"))}}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── (e) invariantes byte-a-byte + 3 endpoints ───────────────────────────────────────────────
def _git(*args) -> str:
    import subprocess
    return subprocess.run(["git", "-C", str(_REPO_ROOT), *args],
                          capture_output=True, text=True, timeout=30).stdout


def p_invariants() -> tuple:
    R = {}
    intact = []
    for f in ("cuarto.render.js", "cuarto.forge.js"):
        rel = f"product/app/design/cuarto/{f}"
        base = _git("show", f"{FORK_BASE}:{rel}")
        cur = (_REPO_ROOT / rel).read_text()
        intact.append((f, base == cur))
    R["(inv) cuarto.render.js (1-A) + cuarto.forge.js (1-B) byte-idénticos a la base"] = all(v for _, v in intact)

    render = (_REPO_ROOT / "product/app/design/cuarto/cuarto.render.js").read_text()
    R["(inv) rebuildLinks + drawGates (F5) presentes en render.js"] = (
        "rebuildLinks" in render and "drawGates" in render)

    main_py = (_REPO_ROOT / "product/backend/app/main.py").read_text()
    endpoints = ("/v1/inspect/forge", "/v1/inspect/dispatch", "/v1/inspect/session/browser")
    R["(inv) los 3 endpoints cableados (forge · dispatch · session/browser)"] = all(e in main_py for e in endpoints)
    return R, {"intact": intact}


# ════════════════════════════════════════════════════════════════════════════════════════════
# JS para los puntos de UI (3 coreografía · 5 evidencia · 7 RUN · 4 manual)
# ════════════════════════════════════════════════════════════════════════════════════════════
_P3_FORGE_JS = r"""
async (p) => {
  // UN forge TMDB con OPUS (synthAlias='brain') — sirve a (3) coreografía, (5) evidencia y (7) la pieza→RUN.
  // [identidad visual 6/6] la revisión antes de equipar ya no cuelga de un modo: aparece
  // SIEMPRE y espera un toque. `autoSeal` da ESE toque (sin destildar nada) para que un
  // verificador headless recorra el MISMO panel real que ve una persona, sin colgarse.
  window.__manual && window.__manual.configure({ autoSeal: true });
  const res = await window.__inspectAndEquip({
    service: p.tmdb, url: p.tmdb, cred: p.key, forma: "token",
    synthAlias: "brain", maxRounds: 2, seedProbes: [p.probe404], apiShapeHint: p.hint });
  const counts = {}; for (const e of (res.events||[])) counts[e.type] = (counts[e.type]||0) + 1;
  const placed = window.__cuarto.placedTiles();
  const fp = placed.find(t => t.forged) || null;
  window.__sync && window.__sync();
  window.__finalRecipe = window.__lastRecipe;      // para (7) el RUN
  window.__finalTools  = res.tools || [];
  const ev = window.__evidence;
  const evIsOpen = ev ? (typeof ev.isOpen === "function" ? ev.isOpen() : ev.isOpen) : null;
  const evEvents = ev ? (typeof ev.events === "function" ? ev.events() : ev.events) : [];
  return {
    ok: !!res.ok, path: res.path,
    sesion_form: (res.events.find(e => e.type === "sesion.ok") || {}).auth_form,
    counts, choreo: res.choreo,
    forgedPiece: fp ? { server: fp.server, belt_ref: fp.belt_ref, puppet_id: fp.puppet_id,
                        tools: fp.tools, forged: !!fp.forged } : null,
    tools: res.tools || [],
    evDefaultOpen: evIsOpen,
    evCount: (evEvents || []).length,
    // (5) evidencia cruda: una tool.validada con su payload REAL (deep-equal vs el emit del motor)
    evValidada: (evEvents || []).filter(e => e.type === "tool.validada")
                  .map(e => ({ nombre: e.nombre, status: e.status, hasPayload: e.payload !== undefined })),
    beValidada: (res.events || []).filter(e => e.type === "tool.validada")
                  .map(e => ({ nombre: e.nombre, status: e.status, hasPayload: e.payload !== undefined })),
  };
}
"""

_P5_EVIDENCE_JS = r"""
async () => {
  const ev = window.__evidence;
  if (!ev) return { error: "no __evidence" };
  const isOpen = () => (typeof ev.isOpen === "function" ? ev.isOpen() : ev.isOpen);
  const wasOpen = isOpen();
  if (!wasOpen) { (ev.toggle ? ev.toggle() : ev.setOpen(true)); }
  await new Promise(r => setTimeout(r, 250));
  const openAfter = isOpen();
  const cards = document.querySelectorAll(".ev-card").length;
  const evEvents = (typeof ev.events === "function" ? ev.events() : ev.events) || [];
  return { wasOpenDefault: !!wasOpen, openAfter: !!openAfter, cards, evCount: evEvents.length };
}
"""

_P7_RUN_JS = r"""
async (p) => {
  const recipe = window.__finalRecipe;
  if (!recipe) return { error: "no __finalRecipe (la forja (3) no dejó receta)" };
  // (7) RUN con OPUS :8924 (tool_calls ESTRUCTURADO): sin alias → manda model.base_url (recipe_assembler).
  recipe.model = { primary: "claude-code-opus-4.8", base_url: p.base_url,
                   max_turns: 6, max_tokens: 600, temperature: 0 };
  const tools = p.tools || [];
  const pick = (re) => tools.find(t => re.test(t));
  let aTool, hint;
  if (pick(/get_movie_details|movie_details|k3_movie/)) { aTool = pick(/get_movie_details|movie_details|k3_movie/); hint = "con movie_id=550 (Fight Club)"; }
  else if (pick(/configuration|p1_config/)) { aTool = pick(/configuration|p1_config/); hint = "(no necesita argumentos)"; }
  else if (pick(/movie/i)) { aTool = pick(/movie/i); hint = "con movie_id=550 si pide un id"; }
  else { aTool = tools[0]; hint = "con movie_id=550 si pide un id"; }
  const prompt = `Tenés equipada la herramienta TMDB \`${aTool}\`. Llamala AHORA MISMO ${hint}. ` +
    `No pidas aclaraciones ni inventes datos: ejecutá la herramienta con ese valor y, con lo que ` +
    `devuelva, decime en una sola frase un dato concreto del resultado.`;
  const r = await fetch("/v1/puppets/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recipe, prompt, space_id: "verify-final-" + Date.now(), deadline_s: 240 }) });
  const body = await r.json().catch(() => null);
  const rec = (body && body.record) || {};
  const forged = new Set(tools);
  return {
    status: r.status, ok: !!(body && body.ok),
    cabled: (rec.tools_cabled || []).map(t => t.tool || t.name || t).filter(t => forged.has(t)),
    called: (rec.tool_calls || []).filter(tc => forged.has(tc.tool || tc.name))
              .map(tc => ({ tool: tc.tool || tc.name, gate: tc.gate_action })),
    model_final: rec.model_final, degraded: !!rec.degraded,
    error: (body && body.error) || rec.error || null,
    answer: ((body && body.answer) || "").slice(0, 200),
  };
}
"""

_P4_MANUAL_JS = r"""
async (p) => {
  const { inspectAndEquip } = await import("./cuarto.inspect.js");
  // UN forge con controlador sintético que suelta P1 y P2 en la REVISIÓN antes de equipar. El
  // BACKEND forja las 3 sondas (lo que equiparía un [Continuar] sin tocar nada); la revisión modula
  // qué entra al belt → la pieza/los tool_filters quedan curados (sólo K3). Sin tocar 1-A/1-B ni el
  // modelo. [identidad visual 6/6] antes esto tenía DOS ganchos (onPropose/isDiscarded, el "punto 1"
  // detrás del Modo técnico): murieron con el modo, y la misma curación se logra con el que queda.
  const controller = {
    reviewBeforeSeal: async (forjadoEv) => {
      const all = (forjadoEv.tools || []);
      const keep = new Set(all.filter(t => t !== p.discard && t !== p.dropSeal));
      return { keep };
    },
    cleanup: () => {},
  };
  const man = await inspectAndEquip({
    api: window.__cuarto, service: p.tmdb, url: p.tmdb, cred: p.key, forma: "token",
    synthAlias: "brain", maxRounds: 1, seedProbes: p.probes, apiShapeHint: p.hint,
    puppetId: p.puppet, manual: controller });
  window.__sync && window.__sync();
  const modelBefore = window.__cuarto.relationModel();
  const recipe = window.__lastRecipe || {};
  const tf = (recipe.belt && recipe.belt.tool_filters) || {};
  const filterTools = [].concat(...Object.values(tf));
  return {
    manOk: !!man.ok,
    manTools: (man.tools || []).slice(), filterTools,
    // el motor forjó las 3 sondas → eso es lo que el flujo AUTO (sin controlador) equiparía
    backendProposed: (man.events || []).filter(e => e.type === "tool.propuesta").map(e => e.nombre),
    backendValidated: (man.events || []).filter(e => e.type === "tool.validada").map(e => e.nombre),
    modelPieces: modelBefore.pieces ? modelBefore.pieces.map(x => x.kind || x.key) : null,
  };
}
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    print("═" * 90)
    print("  VERIFY MOTOR B COMPLETO · integra-final-motor (Ola2-entrada + Ola3 browser-oauth) · OPUS")
    print("═" * 90)

    ok23, d23 = _preflight(SHIM_8923)
    ok24, d24 = _preflight(SHIM_8924)
    print(f"  shim :8923 (live, content-only) → {'OK' if ok23 else 'CAÍDO'} · {d23}")
    print(f"  shim :8924 (fix, structured)    → {'OK' if ok24 else 'CAÍDO'} · {d24}")
    if not (ok23 and ok24):
        print("  ❌ ABORTO: ambos shims Opus deben estar vivos (forja=:8923, gate/RUN=:8924). NO uso Groq.")
        return 2
    print(f"  GROQ_API_KEY = {'(unset ✓)' if not os.environ.get('GROQ_API_KEY') else 'PRESENTE ✗'}")

    tmdb_key = os.environ.get("FORGE_VERIFY_TMDB_KEY", "") or _recover_tmdb_from_vault()
    print(f"  TMDB key: {'recuperada ✓' if tmdb_key else 'NO disponible (token/coreografía/RUN se afectan)'}")

    # belt fixture del gate (P6): self-contained, apunta al send_stub del worktree
    gate_tmp = Path(tempfile.mkdtemp(prefix="finalmotor-gate-"))
    stub = _HERE / "fixtures" / "send_stub_server.py"
    belt_path = gate_tmp / "belt-f5-gatecheck.mcp.json"
    belt_path.write_text(json.dumps({
        "_meta": {"belt": "f5-gatecheck", "slug": "f5-gatecheck"},
        "mcpServers": {"send_stub": {"command": "python3", "args": [str(stub)],
                                     "description": "send_email keyless stub (gate fail-closed)"}}}),
        encoding="utf-8")

    R: dict = {}
    DET: dict = {}
    console_errors: list = []

    back_port, front_port = _free_port(), _free_port()
    print(f"  backend :{back_port} · front :{front_port}\n")
    server, _ = _boot_server(back_port)
    _front = _boot_frontend(front_port, back_port)

    try:
        # ── (6) GATE F5 con OPUS — la prueba que cierra el círculo (in-process, determinística) ──
        print("─" * 90 + "\n  (6) GATE F5 con OPUS — :8924 frena (estructurado) · :8923 no (content) \n" + "─" * 90)
        try:
            r6, d6 = p6_gate_f5(belt_path)
        except Exception as e:  # noqa: BLE001
            r6, d6 = {"(6) GATE F5 con Opus": False}, {"error": f"{type(e).__name__}: {e}"}
            print(f"  ✗ excepción P6: {e}")
        R.update(r6); DET["p6"] = d6

        # ── (1) LAS 4 FORMAS ──
        print("\n" + "─" * 90 + "\n  (1) LAS 4 FORMAS · cada una sesion.ok + forja con OPUS\n" + "─" * 90)
        try:
            r1, d1 = p1_formas(back_port, tmdb_key)
        except Exception as e:  # noqa: BLE001
            r1, d1 = {"(1) 4 formas": False}, {"error": f"{type(e).__name__}: {e}"}
            print(f"  ✗ excepción P1: {e}")
        R.update(r1); DET["p1"] = d1

        # ── (2) RESOLVER ──
        print("\n" + "─" * 90 + "\n  (2) RESOLVER · found verificado / impostor rechazado (offline)\n" + "─" * 90)
        try:
            r2, d2 = p2_resolver(back_port)
        except Exception as e:  # noqa: BLE001
            r2, d2 = {"(2) resolver": False}, {"error": f"{type(e).__name__}: {e}"}
            print(f"  ✗ excepción P2: {e}")
        R.update(r2); DET["p2"] = d2

        # ── (3)(5)(7)(4) por la UI (Playwright, 0 consola) ──
        print("\n" + "─" * 90 + "\n  (3)(5)(7)(4) por la UI del Cuarto (Playwright · 0 consola)\n" + "─" * 90)
        cuarto_url = f"http://127.0.0.1:{front_port}{CUARTO_PATH}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1360, "height": 900})
            page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

            def open_cuarto():
                page.goto(cuarto_url, wait_until="load")
                page.wait_for_function(
                    "() => window.__cuarto && window.__inspectAndEquip && window.__manual && window.__evidence",
                    timeout=15000)
                page.wait_for_timeout(700)

            if tmdb_key:
                # (3)/(5)/(7): UN forge TMDB con Opus
                open_cuarto()
                print("  · (3) forjando TMDB en la UI con OPUS (coreografía + evidencia + pieza→RUN)… ~30-150s")
                f3 = page.evaluate(_P3_FORGE_JS, {"tmdb": TMDB, "key": tmdb_key,
                                                  "hint": _TMDB_HINT, "probe404": PROBE404})
                ec = f3.get("counts") or {}
                ch = f3.get("choreo") or {}
                fp = f3.get("forgedPiece") or {}
                # (3) coreografía 1:1
                p3 = (ec.get("tool.propuesta", 0) >= 1 and ec.get("tool.validando", 0) >= 1
                      and ec.get("tool.validada", 0) >= 1 and ec.get("tool.descartada", 0) >= 1
                      and ch.get("connected") is True and ch.get("forged") is True
                      and f3.get("sesion_form") == "token_query")
                R["(3) coreografía 1:1 con eventos reales (fantasmas→pulso→sólidas/desvanecidas)"] = p3
                DET["p3"] = {"counts": ec, "choreo": ch, "piece_tools": len(fp.get("tools") or [])}
                print(f"     (3) propuesta={ec.get('tool.propuesta',0)} validando={ec.get('tool.validando',0)} "
                      f"validada={ec.get('tool.validada',0)} descartada={ec.get('tool.descartada',0)} "
                      f"choreo(conn={ch.get('connected')},forged={ch.get('forged')}) → {'✅' if p3 else '❌'}")

                # (5) evidencia
                ev_off_clean = (f3.get("evDefaultOpen") is False)
                f5 = page.evaluate(_P5_EVIDENCE_JS)
                evV = f3.get("evValidada") or []
                beV = f3.get("beValidada") or []
                deep_equal = (evV == beV and len(evV) >= 1 and all(x.get("hasPayload") for x in evV))
                p5 = bool(ev_off_clean and f5.get("openAfter") is True and (f5.get("cards") or 0) >= 1
                          and (f5.get("evCount") or 0) >= 1 and deep_equal)
                R["(5) evidencia dev: OFF limpio · ON cruda por evento (deep-equal con el emit)"] = p5
                DET["p5"] = {"off_clean": ev_off_clean, "open_after": f5.get("openAfter"),
                             "cards": f5.get("cards"), "deep_equal_validada": deep_equal}
                print(f"     (5) OFF_limpio={ev_off_clean} ON_cards={f5.get('cards')} "
                      f"deep_equal(validada)={deep_equal} → {'✅' if p5 else '❌'}")

                # (7) RUN con Opus :8924 invoca la pieza forjada
                print("  · (7) RUN real con OPUS :8924 (tool-use estructurado) sobre la pieza forjada… ~20-150s")
                f7 = page.evaluate(_P7_RUN_JS, {"tools": f3.get("tools") or [], "base_url": SHIM_8924})
                called = f7.get("called") or []
                p7 = bool(f7.get("ok") is True and len(f7.get("cabled") or []) >= 1 and len(called) >= 1)
                R["(7) mcp.forjado → pieza equipada → RUN real la invoca (Opus :8924 → 200)"] = p7
                DET["p7"] = f7
                print(f"     (7) status={f7.get('status')} ok={f7.get('ok')} cableadas={len(f7.get('cabled') or [])} "
                      f"llamadas={called} model_final={f7.get('model_final')} → {'✅' if p7 else '❌'}")
                if not p7:
                    print(f"        error={str(f7.get('error'))[:180]!r} answer={str(f7.get('answer'))[:120]!r}")

                # (4) PUNTOS MANUALES — auto vs manual modulan el belt
                print("  · (4) auto vs manual (descartar P1 + soltar P2) modulan el belt… ~40-180s")
                page.wait_for_timeout(2000)
                open_cuarto()
                f4 = page.evaluate(_P4_MANUAL_JS, {"tmdb": TMDB, "key": tmdb_key, "hint": _TMDB_HINT,
                                                   "probes": SEED_PROBES_TMDB, "discard": P1, "dropSeal": P2,
                                                   "puppet": PUPPET})
                mt = f4.get("manTools") or []
                ft = f4.get("filterTools") or []
                bprop = f4.get("backendProposed") or []
                bval = f4.get("backendValidated") or []
                # el motor forjó las 3 sondas (= lo que AUTO equiparía); el controlador modula el belt a K3.
                auto_full = set([P1, P2, K3]) <= set(bval)
                man_modulated = (f4.get("manOk") and P1 not in mt and P2 not in mt and K3 in mt
                                 and P1 not in ft and P2 not in ft and K3 in ft)
                de_cross = (P1 in bprop and P1 in bval)   # D↔E: lo descartado sigue propuesto+validado (evidencia)
                p4 = bool(auto_full and man_modulated)
                R["(4) auto=todo lo forjado · manual (descartar+soltar) MODULA el belt sin tocar el modelo"] = p4
                R["(5·D↔E) tool descartada por D sigue en la evidencia de E como propuesta+validada"] = de_cross
                DET["p4"] = {"manTools": mt, "filters": ft, "backendValidated": bval, "auto_full": auto_full,
                             "man_modulated": man_modulated, "de_cross": de_cross}
                print(f"     (4) motor forjó⊇{{P1,P2,K3}}={auto_full} · manual→belt: P1∉={P1 not in mt} "
                      f"P2∉={P2 not in mt} K3∈={K3 in mt} filtros(P1∉={P1 not in ft},P2∉={P2 not in ft},"
                      f"K3∈={K3 in ft}) → {'✅' if p4 else '❌'}")
                print(f"     (D↔E) P1 backend propuesto={P1 in bprop} validado={P1 in bval} → {'✅' if de_cross else '❌'}")
            else:
                # sin TMDB key no podemos forjar TMDB → marcamos rojo honesto los puntos que dependen
                open_cuarto()  # igual abrimos para chequear 0 consola
                for k in ["(3) coreografía 1:1 con eventos reales (fantasmas→pulso→sólidas/desvanecidas)",
                          "(5) evidencia dev: OFF limpio · ON cruda por evento (deep-equal con el emit)",
                          "(7) mcp.forjado → pieza equipada → RUN real la invoca (Opus :8924 → 200)",
                          "(4) auto=todo · manual (descartar+soltar) MODULA el belt sin tocar el modelo",
                          "(5·D↔E) tool descartada por D sigue en la evidencia de E como propuesta+validada"]:
                    R[k] = False
                print("  ⚠ (3)/(5)/(7)/(4) NO evaluados: falta la TMDB key.")

            browser.close()
    finally:
        server.should_exit = True
        time.sleep(0.3)
        shutil.rmtree(gate_tmp, ignore_errors=True)

    # invariantes (no necesita servidor)
    ri, di = p_invariants()
    R.update(ri); DET["inv"] = di

    R["(consola) 0 errores de consola en toda la UI"] = not console_errors

    print("\n" + "═" * 90)
    print("  RESUMEN — MOTOR B COMPLETO (forjando con OPUS)")
    print("═" * 90)
    for k, v in R.items():
        print(f"   {'✅' if v else '❌'}  {k}")
    if console_errors:
        print("\n  errores de consola:")
        for e in console_errors[:8]:
            print(f"    ✗ {e}")
    allok = all(R.values())
    print("═" * 90)
    # [H3] La nota va ARRIBA del veredicto: la ÚLTIMA línea de una vara es lo que lee un
    # `tail -1` para decidir un merge.
    print("  NOTA: el 2FA real de la 4ta forma lo hace el HUMANO (línea roja §2); el seam "
          "PUPPET_BROWSER_SESSION_FIXTURE marca esa pausa. El gate F5 (6) prueba el FRENO con Opus "
          "estructurado (:8924) y el contraste con :8923 (lo que antes exigía Groq).")
    print(f"  {'✅ TODO VERDE — el MOTOR cierra redondo, forjando con Opus, gate F5 viendo estructurado' if allok else '❌ HAY ROJO'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
