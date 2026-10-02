#!/usr/bin/env python3
"""
selftest_loop_forma2.py — GATE del WIRE · el LOOP INTERNO §3 corre sobre FORMA 2.

Prueba la TESIS del wire (FASE 2): el loop interno, que hasta hoy hardcodeaba la Forma 1
(token en query), ahora consume CUALQUIER `SessionProvider` por la `Session` uniforme.
Acá se le enchufa una `LoginAPISession` (Forma 2 · login definido por la API) contra un
login server LOCAL benigno y se asierta, contra el entorno vivo y sin mocks:

  1. el loop COMPLETO corre encima de LoginAPISession: adquiere sesión por login-API →
     observa → sintetiza (cerebro real) → el candado valida → forja un MCP;
  2. ≥1 tool de lectura VERIFICADA viva DETRÁS del login (la auth viaja en header Bearer,
     inyectada por el wire en CADA request — el observador/validador no saben la forma);
  3. la protección es REAL: sin la sesión, el mismo endpoint 401ea (control) → con el wire
     da 200. No es un server abierto: el login hace falta de verdad;
  4. credencial/sesión CIFRADA (Fernet): password y token de sesión NUNCA en claro en disco;
  5. el guard SSRF corre primero (fail-closed): con el guard real, loopback se bloquea;
  6. el MCP forjado es HONESTO: el spec registra auth.in=header + cred_name=SESSION_TOKEN, y
     al ejecutarlo de verdad (stdio) autentica por header y devuelve 200 detrás del login.

Forma 1 (TMDB) NO se toca acá: su no-regresión la prueba selftest_loop_internal.py (5/5).

Uso:
    PUPPET_BRAIN_SHIM=1 PYTHONPATH=platform \\
      product/backend/.venv/bin/python platform/inspection/loop/selftest_loop_forma2.py
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import uuid
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.budget import Budget  # noqa: E402
from inspection.loop.engine import run_internal_loop  # noqa: E402
from inspection.loop.live_http import LiveHTTP  # noqa: E402
from inspection.loop.session_login import (  # noqa: E402
    AuthInjection, LoginAPISession, SESSION_CRED_NAME, TokenSource,
)

_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


# ── el login server LOCAL benigno: notas-api detrás de un Bearer ────────────────
TOKEN = "tok_" + uuid.uuid4().hex
GOOD = {"username": "demo-user", "password": "s3cr3t-pass-" + uuid.uuid4().hex[:8]}


class _NotesHandler(http.server.BaseHTTPRequestHandler):
    """POST /login → Bearer token. Todo GET exige `Authorization: Bearer <token>`
    (sin él, 401). Una API REST de notas, read-only, paginación + sub-recurso por id."""

    def log_message(self, *a):  # silencio
        pass

    def _send(self, code, body=None, headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body or {}).encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = dict(urllib.parse.parse_qsl(raw))
        if self.path == "/login":
            if payload.get("username") == GOOD["username"] and payload.get("password") == GOOD["password"]:
                self._send(200, {"access_token": TOKEN, "token_type": "bearer"})
            else:
                self._send(401, {"error": "bad credentials"})
        else:
            self._send(404, {"error": "no such endpoint"})

    def do_GET(self):
        # TODO endpoint protegido: exige el Bearer. Sin él → 401 (no es un server abierto).
        if self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            self._send(401, {"error": "unauthorized — login required"})
            return
        u = urllib.parse.urlparse(self.path)
        path = u.path
        if path == "/":
            self._send(200, {"service": "notes-api", "version": 1,
                             "endpoints": ["/notes", "/notes/{id}", "/profile"]})
        elif path == "/profile":
            self._send(200, {"user": "demo-user", "plan": "free", "id": 7})
        elif path == "/notes":
            self._send(200, {"results": [{"id": 1, "title": "primera nota"},
                                          {"id": 2, "title": "segunda nota"}],
                             "page": 1, "total_pages": 1, "count": 2})
        elif path.startswith("/notes/"):
            nid = path.rsplit("/", 1)[-1]
            if nid.isdigit():
                self._send(200, {"id": int(nid), "title": f"nota {nid}",
                                 "body": "contenido de la nota " + nid})
            else:
                self._send(404, {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})


def _start_server() -> tuple[socketserver.TCPServer, str]:
    srv = socketserver.TCPServer(("127.0.0.1", 0), _NotesHandler)
    srv.allow_reuse_address = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


class _LoopbackGuard(C.SSRFGuard):
    """Guard de TEST: permite loopback explícitamente (opt-in). La puerta SIGUE corriendo
    un guard — solo que este aprueba 127.0.0.1 para el server local. El check [5] usa el
    guard REAL para probar que sin este opt-in, loopback se bloquea."""

    def check(self, url: str) -> C.GuardVerdict:
        return C.GuardVerdict(True, "loopback test")


_SHAPE_HINT = (
    "API REST LOCAL de notas, read-only, detrás de un login (la sesión ya está inyectada "
    "en el header Authorization). Endpoints de LECTURA (GET): "
    "GET /notes → lista paginada {results:[{id,title}], page, total_pages, count}; "
    "GET /notes/{id} → detalle de una nota {id, title, body} (sample id=1); "
    "GET /profile → el usuario actual {user, plan, id}. "
    "Propón esas tools de lectura con su sample_call concreto."
)


def main() -> int:
    print("═" * 72)
    print("  GATE · WIRE FASE 2 · el LOOP INTERNO §3 corre sobre FORMA 2 (login API)")
    print("═" * 72)
    srv, base = _start_server()
    root = Path(tempfile.mkdtemp(prefix="forma2-wire-"))
    slug = "notes-forma2"
    principal = C.Principal(anon_id=f"wire-f2-{uuid.uuid4().hex[:12]}")

    try:
        # ── control · sin sesión, el endpoint 401ea (la protección es real) ────────
        print(f"\n[0] control: sin sesión, GET /notes en {base} → 401 (protegido de verdad)")
        ctrl = LiveHTTP().get(base + "/notes")
        check("sin auth, /notes responde 401 (no es un server abierto)", ctrl.status == 401,
              f"status={ctrl.status}")

        # ── 1 · armar la Forma 2 y correr el loop COMPLETO encima ──────────────────
        print("\n[1] el loop interno corre sobre LoginAPISession (Forma 2 · header Bearer)")
        provider = LoginAPISession(
            base, "/login", GOOD, principal, slug,
            token_source=TokenSource("json", "access_token"),
            inject_as=AuthInjection("header", "Authorization", "Bearer {token}"),
            validate_path="/profile", guard=_LoopbackGuard(), cred_root=root,
        )
        budget = Budget(max_rounds=5, max_live_calls=50, max_synth_tokens=300_000, max_seconds=240)
        res = run_internal_loop(
            base, "", principal, slug=slug, provider=provider,
            validate_path="/profile", budget=budget, cred_root=root,
            api_shape_hint=_SHAPE_HINT,
        )
        # working set auditable
        print("\n  ── working set por vuelta (§3) ──")
        for r in res.rounds_log:
            print(f"   v{r['round']}: CONFIRMED={r['CONFIRMED_total']} "
                  f"VERIFIED+={r['VERIFIED_nuevas']} FAILED+={r['FAILED_nuevas']} "
                  f"calls={r['budget']['live_calls']}")

        check("la puerta Forma 2 NO erroró (login vivo + validación)", not res.error,
              res.error or "ok")
        check("la sesión adquirida es LOGIN_API (Forma 2)",
              res.session_meta.get("auth_form") == "login_api", str(res.session_meta.get("auth_form")))
        check("el loop NO está degradado (cerebro real respondió)", res.degraded is False)
        check("convergió a ≥1 tool de lectura VERIFICADA detrás del login",
              len(res.verified) >= 1, f"{len(res.verified)}: {res.verified_names}")
        check("toda verificada es GET read-only (§7)",
              all(v.candidate.kind is C.ToolKind.READ and v.candidate.method == "GET"
                  for v in res.verified))
        check("toda verificada trae sample_response real (cuerpo vivo detrás del login)",
              all(bool(v.sample_response) and len(v.sample_response) > 2 for v in res.verified))

        # ── 2 · la auth viajó por header (no por query) — el wire enchufó la Session ─
        print("\n[2] el wire inyectó la sesión en el header (no en la URL)")
        check("la meta de sesión declara inyección por header Authorization",
              res.session_meta.get("inject_as", "").startswith("header:Authorization"),
              res.session_meta.get("inject_as", ""))
        # el token de sesión NO aparece en ningún url_redacted del log (va en header, no en query)
        leaked_url = any(TOKEN in json.dumps(ev, ensure_ascii=False) for ev in res.events)
        check("el token NUNCA aparece en los eventos/URLs del loop (header, no query)",
              not leaked_url)

        # ── 3 · credencial/sesión CIFRADA (Fernet) — nada en claro ─────────────────
        print("\n[3] credencial y sesión cifradas (Fernet) — password/token jamás en claro")
        cred_file = C.credential_dir(principal, slug, root=root) / "credentials.enc"
        check("credentials.enc existe (vault por-principal)", cred_file.exists(), str(cred_file))
        leaked = []
        for pth in root.rglob("*"):
            if pth.is_file() and pth.name != "credentials.enc":
                blob = pth.read_bytes()
                if GOOD["password"].encode() in blob or TOKEN.encode() in blob:
                    leaked.append(str(pth.relative_to(root)))
        enc_plain = (GOOD["password"].encode() in cred_file.read_bytes()
                     or TOKEN.encode() in cred_file.read_bytes())
        check("password y token NUNCA en claro en disco", not leaked and not enc_plain,
              "limpio" if not leaked and not enc_plain else f"FILTRADO en {leaked or 'credentials.enc'}")
        check("el token de sesión quedó cifrado (SESSION_TOKEN en el vault)",
              provider.store.has(SESSION_CRED_NAME))

        # ── 4 · el guard SSRF corre primero (fail-closed) ──────────────────────────
        print("\n[4] el guard SSRF manda — sin opt-in, loopback se bloquea")
        from inspection.loop.guard import PublicHTTPGuard
        blocked = LoginAPISession(base, "/login", GOOD, C.Principal(anon_id="f2-ssrf"),
                                  "f2-ssrf", guard=PublicHTTPGuard(), cred_root=root)
        try:
            blocked.acquire()
            check("el guard real bloquea loopback (SSRF)", False, "no bloqueó")
        except C.SessionError as e:
            check("el guard real bloquea loopback (SSRF, fail-closed)",
                  "guard" in str(e).lower() or "ssrf" in str(e).lower())

        # ── 5 · el MCP forjado es HONESTO y FUNCIONA detrás del login ──────────────
        print("\n[5] el MCP forjado registra header-auth y autentica de verdad (stdio e2e)")
        f = res.forged
        check("se forjó un MCP con las tools verificadas", f is not None and len(f.tools) >= 1,
              f"{len(f.tools) if f else 0} tools")
        gdir = C.credential_dir(principal, slug, root=root)
        forge_spec_path = gdir / f"{slug}.forge.json"
        belt_path = gdir / f"belt-{slug}.mcp.json"
        check("belt + forge_spec en disco (forjado desde cero)",
              belt_path.exists() and forge_spec_path.exists())
        spec = json.loads(forge_spec_path.read_text()) if forge_spec_path.exists() else {}
        auth = spec.get("auth", {})
        check("el forge_spec declara auth.in=header (no query — honesto)",
              auth.get("in") == "header", json.dumps(auth))
        check("el forge_spec apunta a cred_name=SESSION_TOKEN (la sesión, no una api_key)",
              auth.get("cred_name") == SESSION_CRED_NAME, auth.get("cred_name", ""))
        # el token no aparece en claro en los artefactos del forge
        art_leak = [str(p.relative_to(root)) for p in (belt_path, forge_spec_path)
                    if p.exists() and TOKEN.encode() in p.read_bytes()]
        check("el token NUNCA en claro en el manifest/spec forjado", not art_leak,
              "limpio" if not art_leak else f"FILTRADO en {art_leak}")

        # ── 6 · EJECUTAR el forged server de verdad: ¿autentica por header? ────────
        e2e_ok, e2e_detail = _run_forged_e2e(forge_spec_path, gdir / "credentials.enc", res.verified)
        check("el MCP forjado, ejecutado (stdio), autentica por header y devuelve 200 detrás del login",
              e2e_ok, e2e_detail)

    finally:
        srv.shutdown()

    print("\n" + "═" * 72)
    if _FAILS:
        print(f"  ROJO — {len(_FAILS)} check(s) fallaron: {_FAILS}")
        return 1
    print("  VERDE — el loop interno §3 corre sobre Forma 2 enchufada y forja un MCP honesto")
    return 0


def _run_forged_e2e(forge_spec: Path, cred_file: Path, verified) -> tuple[bool, str]:
    """Lanza forged_mcp_server.py por stdio y llama UNA tool verificada. El server resuelve
    el token del vault (runtime master) y lo inyecta como header → debe dar 200 (no 401)."""
    if not forge_spec.exists() or not cred_file.exists() or not verified:
        return False, "faltan artefactos del forge"
    server = Path(__file__).resolve().parent / "forged_mcp_server.py"
    env = dict(os.environ)
    env["FORGE_SPEC"] = str(forge_spec)
    env["FORGE_CRED_FILE"] = str(cred_file)
    env["FORGE_EXECUTE"] = "1"
    env["PYTHONPATH"] = str(_PLATFORM)
    # elegí una tool SIN path params (más robusta para el e2e); si no hay, la primera.
    tool = next((v.candidate.name for v in verified
                 if "{" not in v.candidate.endpoint), verified[0].candidate.name)
    proc = subprocess.Popen([sys.executable, str(server)], env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": tool, "arguments": {}}},
    ]
    try:
        out, err = proc.communicate("\n".join(json.dumps(m) for m in msgs) + "\n", timeout=40)
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, "timeout del forged server"
    status = None
    for line in out.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("id") == 2:
            txt = (((obj.get("result") or {}).get("content") or [{}])[0]).get("text", "{}")
            try:
                payload = json.loads(txt)
                status = (payload.get("response") or {}).get("status")
            except Exception:
                pass
    return status == 200, f"tool={tool} status={status}" + (f" stderr={err[:160]}" if status != 200 else "")


if __name__ == "__main__":
    raise SystemExit(main())
