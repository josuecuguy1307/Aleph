#!/usr/bin/env python3
"""verify_annex_submodel.py — DONE-BAR del MINI-ANEXO (sub-modelo por provider, BYO-CLI).

Principio: "elegir es un PEDIDO; model_final es el HECHO" — jamás sustitución silenciosa.
Se prueba el camino REAL (build_argv del CLI, _chat del assembler, _route_chat con su guarda,
la clasificación honesta del env-block, y el endpoint del guía /v1/cuarto/guide) — sin correr
un CLI vivo ni tocar :8080/:8926. Cada aserción muerde código de producción, no mocks del feature.

Checks:
  A1  claude build_argv threadea `--model <sub>`  → el PEDIDO llega al spawn (elegir=pedido).
  A2  codex  build_argv threadea `-m <sub>`       → idem para Codex (el done-bar de env-block).
  A3  assembler._chat mete `cli_model`/`effort` en el payload IFF se pasaron.
  A4  _route_chat SÓLO reenvía cli_model/effort al endpoint :8926 (guarda _is_cli_brain_endpoint);
      a un endpoint no-CLI el kwarg cae a None → el run no-CLI es byte-idéntico.
  A5  Codex env-blocked es HONESTO: invoke con binario ausente → error CLASIFICADO
      (not_installed), sin model_final fabricado (jamás un falso verde).
  A6  /v1/cuarto/guide reenvía cli_model al cerebro CLI y ECHOA model_final honesto (el que
      el cerebro reportó, no el pedido).
  A7  /v1/cuarto/guide ante error del plan (HTTP 400) → 502 CLASIFICADO por requested_cli_model
      (la traza honesta "pediste X"), nunca un falso verde.
  B1  compileModel: cli_model viaja SÓLO en un provider CLI y sólo si se pidió; omitido en el
      resto → recetas no-CLI byte-idénticas (paridad con A3/A4 en el front).

Correr (con el venv del backend, para A6/A7 que usan FastAPI):
    product/backend/.venv/bin/python platform/assembler/verify_annex_submodel.py
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
REPO = _THIS.parents[1]

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    mark = "✓" if cond else "✗"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"  {mark} {name}" + (f"  — {detail}" if detail and not cond else (f"  ({detail})" if detail else "")))


print("── ANEXO · SUB-MODELO POR PROVIDER (BYO-CLI) ──────────────────────────────")

# ── A1/A2 · el PEDIDO llega al spawn del CLI (build_argv threadea el flag) ───────────
print("\n[A] el sub-modelo pedido llega al spawn del CLI")
from cli_brain.claude_cli import ClaudeCliProvider  # noqa: E402
from cli_brain.codex_cli import CodexCliProvider        # noqa: E402

argv_c = ClaudeCliProvider().build_argv("claude", "PROMPT", "sonnet", "/tmp/wd")
ok_c = "--model" in argv_c and argv_c[argv_c.index("--model") + 1] == "sonnet"
check("A1 claude build_argv → `--model sonnet` (pedido honrado en el spawn)", ok_c,
      " ".join(argv_c[:6]))

argv_x = CodexCliProvider().build_argv("codex", "PROMPT", "gpt-5.1-codex", "/tmp/wd")
ok_x = "-m" in argv_x and argv_x[argv_x.index("-m") + 1] == "gpt-5.1-codex"
check("A2 codex build_argv → `-m gpt-5.1-codex` (assert flag in spawn)", ok_x,
      " ".join(argv_x[:8]))

# el default del plan (sin sub-modelo) usa el default del provider, no un flag vacío
argv_def = ClaudeCliProvider().build_argv("claude", "P", ClaudeCliProvider().default_model(), "/tmp")
check("A2b default del plan = default_model del provider (no flag vacío)",
      argv_def[argv_def.index("--model") + 1] == "opus", "claude default=opus")

# ── A3 · assembler._chat: cli_model en el payload IFF se pasó (byte-identity) ────────
print("\n[A3] assembler._chat mete cli_model sólo si se pasó (byte-identity)")
import assembler as _asm  # noqa: E402

_cap = {}


def _fake_urlopen(req, timeout=None):
    _cap["body"] = json.loads(req.data.decode())

    class _R:
        def read(self_inner):
            return json.dumps({"choices": [{"message": {"content": "ok"}}], "model": "m"}).encode()

        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

    return _R()


import urllib.request as _ur  # noqa: E402
_orig_urlopen = _ur.urlopen
_ur.urlopen = _fake_urlopen
try:
    _asm._chat([{"role": "user", "content": "x"}], [], "http://127.0.0.1:8926/v1", "claude-code-cli", "", 100, 0, cli_model="sonnet", effort="high")
    with_cli = dict(_cap["body"])
    _asm._chat([{"role": "user", "content": "x"}], [], "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "k", 100, 0)
    without_cli = dict(_cap["body"])
finally:
    _ur.urlopen = _orig_urlopen

check("A3 payload CON cli_model cuando se pasa", with_cli.get("cli_model") == "sonnet")
check("A3 payload CON effort cuando se pasa", with_cli.get("effort") == "high")
check("A3 payload SIN clave cli_model cuando NO se pasa (byte-identity no-CLI)",
      "cli_model" not in without_cli)
check("A3 payload SIN clave effort cuando NO se pasa (byte-identity no-CLI)",
      "effort" not in without_cli)

# ── A4 · _route_chat guarda cli_model al endpoint :8926 solamente ────────────────────
print("\n[A4] _route_chat reenvía cli_model SÓLO al endpoint CLI (:8926)")
import recipe_assembler as ra  # noqa: E402

# OJO: recipe_assembler carga su PROPIO objeto módulo assembler (ra._asm vía _load_assembler),
# distinto del `import assembler` de este harness. _route_chat llama ra._asm._chat → hay que
# espiar ESE, no el nuestro (si no, el spy nunca se invoca).
_seen = []
_orig_chat = ra._asm._chat


def _spy_chat(messages, tools, url, model, key, max_tokens, temperature,
              cli_model=None, effort=None, **_otros):
    # `**_otros` y no una lista de kwargs a mano: esta vara mide `cli_model`/`effort`, no la
    # firma entera de `_chat`. Cada parámetro nuevo del motor la rompía sin que hubiera
    # ninguna regresión de lo suyo — pasó con `tool_choice` (B0-2) y lo pagó esta línea.
    _seen.append((url, cli_model, effort))
    return {"choices": [{"message": {"content": "ok"}}], "model": model}


ra._asm._chat = _spy_chat
try:
    _seen.clear()
    ra._route_chat([{"role": "user", "content": "x"}], [],
                   base_url="https://api.groq.com/openai/v1", primary="openai/gpt-oss-120b",
                   fallback=None, api_key="k", max_tokens=100, temperature=0,
                   route_log=[], cli_model="sonnet", effort="max")
    non_cli = _seen[0]
    _seen.clear()
    ra._route_chat([{"role": "user", "content": "x"}], [],
                   base_url="http://127.0.0.1:8926/v1", primary="claude-code-cli",
                   fallback=None, api_key="", max_tokens=100, temperature=0,
                   route_log=[], cli_model="sonnet", effort="max")
    cli_ep = _seen[0]
finally:
    ra._asm._chat = _orig_chat

check("A4 endpoint NO-CLI → _chat recibe cli_model=None (run byte-idéntico)", non_cli[1] is None,
      f"url={non_cli[0]} cli_model={non_cli[1]}")
check("A4 endpoint :8926 → _chat recibe cli_model='sonnet' (el pedido pasa)", cli_ep[1] == "sonnet",
      f"url={cli_ep[0]} cli_model={cli_ep[1]}")
check("A4 endpoint NO-CLI → effort no se filtra", non_cli[2] is None,
      f"url={non_cli[0]} effort={non_cli[2]}")
check("A4 endpoint :8926 → effort='max' llega al CLI", cli_ep[2] == "max",
      f"url={cli_ep[0]} effort={cli_ep[2]}")

# ── A5 · Codex env-blocked es HONESTO (clasificado, sin falso verde) ─────────────────
print("\n[A5] Codex env-blocked → error clasificado, sin model_final fabricado")
os.environ["PUPPET_CODEX_BIN"] = "/nonexistent/definitely-not-codex-xyz"
try:
    res = CodexCliProvider().invoke("hola", model="gpt-5.1-codex")
finally:
    os.environ.pop("PUPPET_CODEX_BIN", None)
from cli_brain.base import ERR_NOT_INSTALLED  # noqa: E402
check("A5 invoke NO ok (env-blocked, jamás falso verde)", res.ok is False, f"ok={res.ok}")
check("A5 error CLASIFICADO not_installed", res.error_kind == ERR_NOT_INSTALLED, f"kind={res.error_kind}")
check("A5 sin model_final fabricado", not res.model_final, f"model_final={res.model_final!r}")

# ── A6/A7 · /v1/cuarto/guide reenvía cli_model + honestidad model_final/clasificación ─
print("\n[A6/A7] /v1/cuarto/guide: reenvía cli_model + model_final honesto + error clasificado")
try:
    sys.path.insert(0, str(REPO / "product" / "backend"))
    from fastapi import FastAPI  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    import app.phase1.cuarto_guide as cg  # noqa: E402

    app = FastAPI()
    app.include_router(cg.build_cuarto_guide_router())
    client = TestClient(app)
    GM = {"brain_provider": "claude_cli", "alias": "claude_cli",
          "base_url": "http://127.0.0.1:8926/v1", "primary": "claude-code-cli"}

    _guide_cap = {}

    def _guide_ok_urlopen(req, timeout=None):
        _guide_cap["body"] = json.loads(req.data.decode())

        class _R:
            def read(self_inner):
                # el cerebro REPORTA otro modelo que el pedido → model_final honesto
                return json.dumps({"choices": [{"message": {"content": "listo", "tool_calls": []}}],
                                   "model": "claude-sonnet-4-6-cli-reported"}).encode()

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return _R()

    _cg_orig = cg.urllib.request.urlopen
    cg.urllib.request.urlopen = _guide_ok_urlopen
    try:
        r = client.post("/v1/cuarto/guide", json={
            "messages": [{"role": "user", "content": "armame un agente"}],
            "tools": [{"type": "function", "function": {"name": "ver_cuarto", "parameters": {}}}],
            "guide_model": GM, "cli_model": "sonnet"})
    finally:
        cg.urllib.request.urlopen = _cg_orig

    if r.status_code != 200:
        check("A6 endpoint 200", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        d = r.json()
        check("A6 el endpoint reenvió cli_model='sonnet' al cerebro CLI",
              _guide_cap.get("body", {}).get("cli_model") == "sonnet")
        check("A6 model_final HONESTO = lo que el cerebro reportó (no el pedido)",
              d.get("model_final") == "claude-sonnet-4-6-cli-reported", f"model_final={d.get('model_final')}")
        check("A6 requested_cli_model echoado (traza del pedido)", d.get("requested_cli_model") == "sonnet")

    # A7 · error del plan → 502 clasificado por requested_cli_model
    def _guide_err_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "model not in plan", {},
                                     io.BytesIO(b'{"error":"unsupported cli model for this plan"}'))

    cg.urllib.request.urlopen = _guide_err_urlopen
    try:
        r2 = client.post("/v1/cuarto/guide", json={
            "messages": [{"role": "user", "content": "hola"}], "tools": [],
            "guide_model": GM, "cli_model": "sonnet"})
    finally:
        cg.urllib.request.urlopen = _cg_orig
    err = (r2.json() or {}).get("error", {})
    check("A7 error del plan → 502 (no 200 falso verde)", r2.status_code == 502, f"status={r2.status_code}")
    check("A7 clasificado por requested_cli_model (traza 'pediste X')",
          err.get("requested_cli_model") == "sonnet", f"err={err}")

    # ── A8/A9/A10 · SSRF + exfiltración de credenciales (review BLOCKER #1) ───────────
    print("\n[A8/A9/A10] anti-SSRF: base_url del cliente JAMÁS se usa; sin alias conocido → 400, sin outbound")
    _reached = {"called": False, "url": None, "auth": None}

    def _tripwire_urlopen(req, timeout=None):
        # si ESTO se llama con un host del atacante, el fix falló → registramos y devolvemos algo inerte
        _reached["called"] = True
        _reached["url"] = req.full_url
        _reached["auth"] = req.headers.get("Authorization")

        class _R:
            def read(self_inner):
                return json.dumps({"choices": [{"message": {"content": "x"}}], "model": "x"}).encode()

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return _R()

    cg.urllib.request.urlopen = _tripwire_urlopen
    try:
        # A8 · base_url arbitrario + SIN alias conocido → RECHAZO 400, sin outbound, sin key
        _reached.update(called=False, url=None, auth=None)
        rA = client.post("/v1/cuarto/guide", json={
            "messages": [{"role": "user", "content": "hi"}],
            "guide_model": {"base_url": "https://attacker.tld/v1", "primary": "x"}})
        check("A8 base_url arbitrario sin alias → 400 (rechazo)", rA.status_code == 400, f"status={rA.status_code}")
        check("A8 NUNCA hizo el request saliente (0 SSRF)", _reached["called"] is False, f"url={_reached['url']}")

        # A9 · truco de substring (groq.com.attacker) con alias BOGUS → RECHAZO, sin key exfiltrada
        _reached.update(called=False, url=None, auth=None)
        rB = client.post("/v1/cuarto/guide", json={
            "messages": [{"role": "user", "content": "hi"}],
            "guide_model": {"alias": "totally-bogus-alias", "base_url": "https://groq.com.attacker.tld/v1", "primary": "x"}})
        check("A9 substring-trick + alias desconocido → 400 (no fallback al base_url del cliente)",
              rB.status_code == 400, f"status={rB.status_code}")
        check("A9 la key de infra NUNCA viajó a un host no vetado", _reached["called"] is False,
              f"url={_reached['url']} auth={'set' if _reached['auth'] else None}")

        # A10 · REGRESIÓN: un alias CONOCIDO (oss) sí resuelve → outbound al host del REGISTRO (groq real),
        # jamás a un base_url del cliente. Prueba que el fix no rompió la resolución legítima.
        _reached.update(called=False, url=None, auth=None)
        rC = client.post("/v1/cuarto/guide", json={
            "messages": [{"role": "user", "content": "hi"}],
            "guide_model": {"alias": "oss", "base_url": "https://groq.com.attacker.tld/v1", "primary": "pwn"}})
        # oss requiere GROQ key; si no está en el env, el endpoint corta con 502 no_key ANTES del outbound.
        # En ambos casos, el host jamás es el del atacante y el primary jamás es 'pwn'.
        host_ok = (not _reached["called"]) or ("api.groq.com" in (_reached["url"] or ""))
        check("A10 alias conocido resuelve al host del REGISTRO, no al base_url del cliente",
              host_ok and "attacker" not in (_reached["url"] or ""), f"status={rC.status_code} url={_reached['url']}")
    finally:
        cg.urllib.request.urlopen = _cg_orig
except ImportError as e:
    check("A6/A7 FastAPI disponible (correr con el venv del backend)", False, f"ImportError: {e}")

# ── B1 · compileModel (front) byte-identity + carriage del pedido ────────────────────
print("\n[B1] compileModel: cli_model sólo en provider CLI y sólo si se pidió")
_models_js = str(REPO / "product" / "app" / "design" / "cuarto" / "cuarto.models.js")
_node = f"""
import {{ compileModel, cliSubmodels }} from {json.dumps(_models_js)};
const cli = compileModel("claude_cli", {{ cli_model: "sonnet", effort: "high" }});
const cliDefault = compileModel("claude_cli", {{}});
const apiKey = compileModel("opus", {{ cli_model: "sonnet", effort: "high" }});
const subs = cliSubmodels("claude_cli").map(s => s.id);
const subsApi = cliSubmodels("opus");
console.log(JSON.stringify({{
  cli_has: cli.cli_model === "sonnet" && cli.brain_provider === "claude_cli",
  cli_effort: cli.effort === "high",
  cliDefault_omits: !("cli_model" in cliDefault),
  apiKey_omits: !("cli_model" in apiKey),
  apiKey_effort_omits: !("effort" in apiKey),
  subs_ok: subs.includes("sonnet") && subs.includes("opus") && subs.includes(""),
  subsApi_empty: subsApi.length === 0,
}}));
"""
try:
    out = subprocess.run(["node", "--input-type=module", "-e", _node],
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        check("B1 node compileModel", False, out.stderr[:300])
    else:
        b = json.loads(out.stdout.strip().splitlines()[-1])
        check("B1 provider CLI + pedido → cli_model viaja", b["cli_has"])
        check("B1 provider CLI + pedido → effort viaja", b["cli_effort"])
        check("B1 provider CLI sin pedido → cli_model OMITIDO (default del plan)", b["cliDefault_omits"])
        check("B1 provider por API key → cli_model OMITIDO (byte-identity no-CLI)", b["apiKey_omits"])
        check("B1 provider por API key → effort OMITIDO", b["apiKey_effort_omits"])
        check("B1 catálogo de sub-modelos CLI presente (sonnet/opus/default)", b["subs_ok"])
        check("B1 provider por API key NO ofrece sub-modelo (lista vacía)", b["subsApi_empty"])
except (subprocess.TimeoutExpired, FileNotFoundError) as e:
    check("B1 node disponible", False, str(e))

print(f"\n── RESULTADO: {_passed} passed · {_failed} failed ──")
sys.exit(1 if _failed else 0)
