#!/usr/bin/env python3
"""verify_byo_cli.py — harness COMMITTEABLE del cerebro BYO-CLI (D1 · D2 · D4-unit · simetría).

CERO tokens / CERO quota de suscripción: los CLIs se FALSIFICAN con scripts que
reproducen los shapes REALES sondeados en vivo (BYO-CLI-GROUND-TRUTH.md) — salida
JSON de `claude -p`, JSONL de `codex exec --json`, los 3 estados de auth, las
señales de rate-limit de cada binario y el 400 de entitlement de codex.

Ejes (cada uno corre para AMBOS providers — la SIMETRÍA es un eje en sí):
  A · argv: tools-off horneadas + flags PROHIBIDOS ausentes + gate assert_argv_safe
  B · detect: los 3 estados por provider desde salidas canned REALES
  C · parse_result claude: éxito (trampa haiku en modelUsage), rate-limit, no_auth
  D · parse_result codex: éxito, entitlement, rate-limit + reset, no_auth, exec_events
  E · SIMETRÍA: mismo eje de clasificación → mismo kind en ambos providers
  F · server :puerto-test con CLIs FAKE: 200 model_final real + tool_calls extraídos,
      429 throttled clasificado por provider, /v1/brains/status con estados
      INDEPENDIENTES (uno ready + otro not_installed a la vez)
  G · D4 units: _parse_cli_brain_error + _honest_model_final (scope quirúrgico)
  H · resolución models.py + validador (enum brain_provider)

El eje VIVO (CLI real, run e2e) corre aparte: qa/verify_byo_cli_live.py.
Run: python3 qa/verify_byo_cli.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "platform" / "assembler"))
sys.path.insert(0, str(REPO / "product" / "backend"))

from cli_brain.base import (ERR_MODEL, ERR_NO_AUTH, ERR_RATE_LIMIT, FORBIDDEN_FLAGS,
                            STATE_NO_AUTH, STATE_NOT_INSTALLED, STATE_READY,
                            assert_argv_safe)
from cli_brain.claude_cli import ClaudeCliProvider
from cli_brain.codex_cli import CodexCliProvider

FAILS: list[str] = []


def ok(cond: bool, label: str, extra: str = "") -> None:
    print(("✓ " if cond else "✗ ") + label + ((" · " + extra) if (extra and not cond) else ""))
    if not cond:
        FAILS.append(label)


CLAUDE = ClaudeCliProvider()
CODEX = CodexCliProvider()

# ── shapes REALES (sondeados vivos — no inventados) ──────────────────────────────
CLAUDE_OK_JSON = {
    "type": "result", "subtype": "success", "is_error": False, "result": "PONG",
    "session_id": "s1", "api_error_status": None,
    "usage": {"input_tokens": 2, "output_tokens": 5},
    # TRAMPA REAL: haiku (auxiliar) tuvo MÁS outputTokens que el cerebro en la sonda viva
    "modelUsage": {
        "claude-haiku-4-5-20251001": {"inputTokens": 523, "outputTokens": 15,
                                      "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0},
        "claude-sonnet-5": {"inputTokens": 2, "outputTokens": 5,
                            "cacheReadInputTokens": 3289, "cacheCreationInputTokens": 5388},
    },
    "num_turns": 1, "permission_denials": [],
}
CODEX_OK_JSONL = "\n".join([
    json.dumps({"type": "thread.started", "thread_id": "t1"}),
    json.dumps({"type": "turn.started"}),
    json.dumps({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message",
                                                   "text": "PONG"}}),
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4}}),
])
CODEX_ENTITLEMENT = "\n".join([  # shape 400 REAL visto vivo en esta máquina
    json.dumps({"type": "thread.started", "thread_id": "t1"}),
    json.dumps({"type": "turn.started"}),
    json.dumps({"type": "error", "message": "{\"type\":\"error\",\"status\":400,\"error\":{\"type\":"
                "\"invalid_request_error\",\"message\":\"The 'gpt-5.1-codex-max' model is not "
                "supported when using Codex with a ChatGPT account.\"}}"}),
    json.dumps({"type": "turn.failed", "error": {"message": "The 'gpt-5.1-codex-max' model is not supported"}}),
])
CODEX_RATELIMIT = "\n".join([  # strings reales del binario 0.118.0
    json.dumps({"type": "thread.started", "thread_id": "t1"}),
    json.dumps({"type": "error", "message": "You've hit your usage limit for GPT-5.1. Try again at 8:00 PM."}),
    json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit"}}),
])
CODEX_EXEC_EVENT = "\n".join([
    json.dumps({"type": "thread.started", "thread_id": "t1"}),
    json.dumps({"type": "item.completed", "item": {"id": "i0", "type": "command_execution",
                                                   "command": "ls"}}),
    json.dumps({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "hola"}}),
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
])


def section(t: str) -> None:
    print(f"\n══ {t} ══")


# ═════ A · ARGV: tools-off + prohibidos ═════
section("A · argv tools-off + flags prohibidos (ambos providers)")
argv_claude = CLAUDE.build_argv("/bin/claude", "hola", "opus", "/tmp/wd")
argv_codex = CODEX.build_argv("/bin/codex", "hola", "gpt-5.1-codex-max", "/tmp/wd")
i = argv_claude.index("--tools")
ok(argv_claude[i + 1] == "", "claude: --tools \"\" (todas las built-in OFF)")
ok("--strict-mcp-config" in argv_claude, "claude: --strict-mcp-config (cero MCP del usuario)")
ok("--no-session-persistence" in argv_claude, "claude: --no-session-persistence")
ok("--disallowedTools" in argv_claude and "Bash" in argv_claude, "claude: --disallowedTools cinturón-y-tiradores")
ok("--output-format" in argv_claude and "json" in argv_claude, "claude: --output-format json")
ok("--bare" not in argv_claude, "claude: JAMÁS --bare (mataría el OAuth de la suscripción)")
ok("-s" in argv_codex and argv_codex[argv_codex.index("-s") + 1] == "read-only", "codex: -s read-only (jail)")
ok("--ephemeral" in argv_codex, "codex: --ephemeral (nada persiste)")
ok("-m" in argv_codex and argv_codex[argv_codex.index("-m") + 1] == "gpt-5.1-codex-max",
   "codex: -m SIEMPRE explícito (config del usuario no confiable)")
ok('web_search="disabled"' in argv_codex, "codex: web search OFF (override top-level vigente)")
ok("--json" in argv_codex, "codex: --json (eventos JSONL)")
for name, argv in (("claude", argv_claude), ("codex", argv_codex)):
    ok(not FORBIDDEN_FLAGS.intersection(argv), f"{name}: CERO flags de bypass en el argv")
try:
    assert_argv_safe(argv_claude + ["--dangerously-skip-permissions"])
    ok(False, "gate assert_argv_safe REVIENTA ante un flag prohibido inyectado")
except RuntimeError:
    ok(True, "gate assert_argv_safe REVIENTA ante un flag prohibido inyectado")

# ═════ B · DETECT: 3 estados por provider (salidas canned REALES) ═════
section("B · detect — 3 estados por provider")
st, det, extra = CLAUDE.parse_detect(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                                    "subscriptionType": "max"}), "")
ok(st == STATE_READY and extra.get("subscriptionType") == "max", "claude ready (JSON real, exit 0)", f"{st}/{extra}")
st, det, _ = CLAUDE.parse_detect(1, json.dumps({"loggedIn": False, "authMethod": "none"}), "")
ok(st == STATE_NO_AUTH and "inicia sesión" in det, "claude no_auth (loggedIn:false, exit 1) + guía", det)
st, det, _ = CODEX.parse_detect(0, "Logged in using ChatGPT\n", "")
ok(st == STATE_READY, "codex ready ('Logged in using ChatGPT', exit 0)", st)
st, det, _ = CODEX.parse_detect(1, "Not logged in\n", "")
ok(st == STATE_NO_AUTH and "codex login" in det, "codex no_auth ('Not logged in', exit 1) + guía", det)
for name, prov, env in (("claude", ClaudeCliProvider(), "PUPPET_CLAUDE_BIN"),
                        ("codex", CodexCliProvider(), "PUPPET_CODEX_BIN")):
    os.environ[env] = "/nonexistent/bin/xx"
    s = prov.detect()
    ok(s.state == STATE_NOT_INSTALLED, f"{name} not_installed (binario ausente)", s.state)
    del os.environ[env]

# ═════ C · parse_result CLAUDE ═════
section("C · parse_result claude (shapes reales)")
r = CLAUDE.parse_result(0, json.dumps(CLAUDE_OK_JSON), "", "/tmp", "sonnet")
ok(r.ok and r.text == "PONG", "éxito: ok + texto")
ok(r.model_final == "claude-sonnet-5" and r.model_final_source == "cli-reported",
   "model_final REAL esquiva la trampa haiku (prefijo del alias pedido)", str(r.model_final))
r = CLAUDE.parse_result(0, json.dumps(CLAUDE_OK_JSON), "", "/tmp", "zz-desconocido")
ok(r.model_final == "claude-sonnet-5",
   "model_final por CONTEXTO cargado si el alias no matchea (el cerebro carga la conversación)", str(r.model_final))
r = CLAUDE.parse_result(1, "", "Claude AI usage limit reached|1783650000", "/tmp", "opus")
ok(r.error_kind == ERR_RATE_LIMIT, "rate-limit por señal en stderr (formato |epoch real)", str(r.error_kind))
ok(bool(r.reset_hint), "reset_hint parseado del epoch", r.reset_hint)
j429 = dict(CLAUDE_OK_JSON, is_error=True, api_error_status=429, subtype="error")
r = CLAUDE.parse_result(0, json.dumps(j429), "", "/tmp", "opus")
ok(r.error_kind == ERR_RATE_LIMIT, "rate-limit por api_error_status:429 del JSON", str(r.error_kind))
r = CLAUDE.parse_result(1, "", "Not logged in. Please run /login", "/tmp", "opus")
ok(r.error_kind == ERR_NO_AUTH, "no_auth por señal de sesión caída", str(r.error_kind))
r = CLAUDE.parse_result(0, "esto no es json", "", "/tmp", "opus")
ok(not r.ok and r.error_kind == ERR_MODEL, "salida no-JSON → model_error honesto", str(r.error_kind))

# ═════ D · parse_result CODEX ═════
section("D · parse_result codex (shapes reales)")
r = CODEX.parse_result(0, CODEX_OK_JSONL, "", "/tmp", "gpt-5.1-codex-max")
ok(r.ok and r.text == "PONG", "éxito: agent_message → texto")
ok(r.model_final == "gpt-5.1-codex-max" and r.model_final_source == "requested-validated",
   "model_final = pedido-validado (codex 400-ea explícito lo que no soporta)", f"{r.model_final}/{r.model_final_source}")
ok(r.usage.get("completion_tokens") == 4, "usage del turn.completed", str(r.usage))
ok(r.exec_events == 0, "cero eventos de ejecución (puro in/out)")
jsonl_model = CODEX_OK_JSONL.replace('"thread_id": "t1"', '"thread_id": "t1", "model": "gpt-5.1-codex-max"')
r = CODEX.parse_result(0, jsonl_model, "", "/tmp", "gpt-5.1-codex-max")
ok(r.model_final_source == "cli-reported", "model_final cli-reported si el evento lo trae", r.model_final_source)
r = CODEX.parse_result(1, CODEX_ENTITLEMENT, "", "/tmp", "gpt-5.1-codex-max")
ok(r.error_kind == ERR_MODEL and "not supported" in r.error_detail,
   "entitlement 400 → model_error honesto (el caso REAL de esta máquina)", str(r.error_kind))
r = CODEX.parse_result(1, CODEX_RATELIMIT, "", "/tmp", "gpt-5.1-codex-max")
ok(r.error_kind == ERR_RATE_LIMIT, "ventana agotada → rate_limit ('hit your usage limit')", str(r.error_kind))
ok("8:00" in (r.reset_hint or ""), "reset_hint del 'Try again at 8:00 PM'", r.reset_hint)
r = CODEX.parse_result(1, json.dumps({"type": "error", "message": "Not logged in"}), "", "/tmp", "m")
ok(r.error_kind == ERR_NO_AUTH, "sesión caída mid-run → no_auth", str(r.error_kind))
r = CODEX.parse_result(0, CODEX_EXEC_EVENT, "", "/tmp", "m")
ok(r.exec_events >= 1, "un command_execution en el JSONL SE CUENTA (el harness lo caza)", str(r.exec_events))

# MED #12 — nombres MCP con punto: el regex viejo truncaba "corp.tools" → el apagado no
# matcheaba → server ENCENDIDO. tomllib + fallback + _toml_key lo cierran.
from cli_brain.codex_cli import list_mcp_server_names as _cx_names, _toml_key as _cx_key  # noqa: E402
_cfg = Path(tempfile.mkdtemp(prefix="byo-toml-")) / "config.toml"
_cfg.write_text('model = "gpt-5.1"\n[mcp_servers."corp.tools"]\ncommand = "x"\n'
                '[mcp_servers.simple]\ncommand = "y"\n')
names = _cx_names(str(_cfg))
ok("corp.tools" in names and "simple" in names,
   "codex MCP names: 'corp.tools' NO se trunca (nombre quoted-con-punto entero)", str(names))
ok(_cx_key("corp.tools") == '"corp.tools"' and _cx_key("simple") == "simple",
   "codex _toml_key: quotea el nombre con punto para el override -c, bare el simple")

# ═════ E · SIMETRÍA de clasificación ═════
section("E · simetría — mismo eje, mismo kind en AMBOS providers")
AXES = [
    ("rate-limit", "You've hit your usage limit. Try again at 9 PM.", ERR_RATE_LIMIT),
    ("rate-limit-generic", "429 too many requests", ERR_RATE_LIMIT),
    ("auth", "Not logged in", ERR_NO_AUTH),
    ("model-error", "internal server error: algo raro", ERR_MODEL),
]
for axis, blob, want in AXES:
    kc, _ = CLAUDE.classify_error(blob)
    kx, _ = CODEX.classify_error(blob)
    ok(kc == kx == want, f"simetría [{axis}]: claude={kc} codex={kx} esperado={want}")

# ═════ F · SERVER con CLIs FAKE (contrato HTTP completo) ═════
section("F · server cli_brain con CLIs FAKE (shapes reales)")
tmp = Path(tempfile.mkdtemp(prefix="byo-cli-fakes-"))
mode_file = tmp / "mode"
mode_file.write_text("ok")

# Los fakes leen el MODO de un archivo JUNTO al binario (NO de env): así el test funciona
# aunque base.sanitized_env strippee el env del spawn (review #0/#15) — y de paso lo PRUEBA.
# También registran en `leak-*` qué secretos vieron en SU env → el test asserta ausencia.
fake_claude = tmp / "claude"
fake_claude.write_text(textwrap.dedent("""\
    #!/bin/bash
    # FAKE Claude Code CLI — shapes reales de BYO-CLI-GROUND-TRUTH.md
    for a in "$@"; do case "$a" in --dangerously-skip-permissions|--allow-dangerously-skip-permissions) echo FORBIDDEN >&2; exit 99;; esac; done
    D=$(dirname "$0"); MODE=$(cat "$D/mode" 2>/dev/null || echo ok)
    # registrar secretos VISTOS en el env del hijo (deben estar AUSENTES tras el saneamiento)
    echo "ANTHROPIC=${ANTHROPIC_API_KEY:-} OPENAI=${OPENAI_API_KEY:-} GROQ=${GROQ_API_KEY:-} FAKE_MODE_FILE=${FAKE_MODE_FILE:-}" > "$D/leak-claude"
    if [ "$1" = "auth" ]; then
      if [ "$MODE" = "noauth" ]; then echo '{"loggedIn": false, "authMethod": "none"}'; exit 1; fi
      if [ "$MODE" = "apikey" ]; then echo '{"loggedIn": true, "authMethod": "api_key", "apiKeySource": "ANTHROPIC_API_KEY"}'; exit 0; fi
      echo '{"loggedIn": true, "authMethod": "claude.ai", "subscriptionType": "max"}'; exit 0
    fi
    case "$MODE" in
      ratelimit) echo 'Claude AI usage limit reached|1783650000' >&2; exit 1;;
      nomodel) cat <<'EOF'
    {"result":"PONG","is_error":false,"subtype":"success","usage":{"input_tokens":2,"output_tokens":5},"num_turns":1}
    EOF
    ;;
      execd) cat <<'EOF'
    {"result":"leí tu id_rsa","is_error":false,"subtype":"success","usage":{"input_tokens":2,"output_tokens":5},"modelUsage":{"claude-opus-4-8":{"inputTokens":2,"outputTokens":5}},"num_turns":3}
    EOF
    ;;
      toolcall) cat <<'EOF'
    {"result":"<function=add>{\\"a\\":2,\\"b\\":3}</function>","is_error":false,"subtype":"success","usage":{"input_tokens":10,"output_tokens":8},"modelUsage":{"claude-opus-4-8":{"inputTokens":10,"outputTokens":8,"cacheReadInputTokens":100,"cacheCreationInputTokens":200}},"num_turns":1}
    EOF
    ;;
      *) cat <<'EOF'
    {"result":"PONG","is_error":false,"subtype":"success","usage":{"input_tokens":2,"output_tokens":5},"modelUsage":{"claude-opus-4-8":{"inputTokens":2,"outputTokens":5,"cacheReadInputTokens":300,"cacheCreationInputTokens":500}},"num_turns":1}
    EOF
    ;;
    esac
"""))
fake_claude.chmod(0o755)

fake_codex = tmp / "codex"
fake_codex.write_text(textwrap.dedent("""\
    #!/bin/bash
    # FAKE Codex CLI — shapes reales de BYO-CLI-GROUND-TRUTH.md
    for a in "$@"; do case "$a" in --dangerously-bypass-approvals-and-sandbox|--full-auto) echo FORBIDDEN >&2; exit 99;; esac; done
    D=$(dirname "$0"); MODE=$(cat "$D/mode" 2>/dev/null || echo ok)
    if [ "$1" = "login" ]; then
      if [ "$MODE" = "noauth" ]; then echo 'Not logged in'; exit 1; fi
      echo 'Logged in using ChatGPT'; exit 0
    fi
    case "$MODE" in
      ratelimit) cat <<'EOF'
    {"type":"thread.started","thread_id":"t1"}
    {"type":"error","message":"You've hit your usage limit for GPT-5.1. Try again at 8:00 PM."}
    {"type":"turn.failed","error":{"message":"You've hit your usage limit"}}
    EOF
    exit 1;;
      *) cat <<'EOF'
    {"type":"thread.started","thread_id":"t1","model":"gpt-5.1-codex-max"}
    {"type":"item.completed","item":{"id":"i1","type":"agent_message","text":"PONG-X"}}
    {"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":4}}
    EOF
    ;;
    esac
"""))
fake_codex.chmod(0o755)

PORT = int(os.environ.get("BYO_CLI_TEST_PORT", "8996"))
# El env del SERVER trae secretos a propósito — para probar que sanitized_env los STRIPPEA
# antes de spawnear el CLI (no llegan a `leak-claude`).
env = dict(os.environ,
           PUPPET_CLAUDE_BIN=str(fake_claude), PUPPET_CODEX_BIN=str(fake_codex),
           PUPPET_CLI_BRAIN_PORT=str(PORT), FAKE_MODE_FILE=str(mode_file),
           ANTHROPIC_API_KEY="sk-ant-LEAK-should-be-stripped",
           OPENAI_API_KEY="sk-LEAK-openai", GROQ_API_KEY="gsk_LEAK-groq",
           PUPPET_CLI_BRAIN_DETECT_TTL="0", PUPPET_CLI_BRAIN_TIMEOUT="20")
srv = subprocess.Popen([sys.executable, str(REPO / "platform/assembler/cli_brain/server.py")],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
time.sleep(1.0)


def http_json(method: str, path: str, payload: dict | None = None,
              headers: dict | None = None) -> tuple[int, dict]:
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method,
                                 data=(json.dumps(payload).encode() if payload else None),
                                 headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


try:
    code, body = http_json("GET", "/health")
    ok(code == 200 and body.get("ok"), "server /health vivo")

    code, body = http_json("POST", "/v1/chat/completions",
                           {"model": "claude-code-cli", "messages": [{"role": "user", "content": "ping"}]})
    ok(code == 200 and body["choices"][0]["message"]["content"] == "PONG",
       "claude fake: 200 + texto", str(code))
    ok(body.get("model") == "claude-opus-4-8",
       "claude fake: response.model = model_final REAL (no un eco del pedido)", str(body.get("model")))
    ok((body.get("aleph_cli_brain") or {}).get("exec_events") == 0, "claude fake: exec_events 0")

    # HIGH #0/#15 — ATRIBUCIÓN: el env del server trae ANTHROPIC/OPENAI/GROQ a propósito;
    # sanitized_env DEBE stripearlos antes de spawnear (si no, el CLI facturaría a la key y
    # el cost-event mentiría $0). El fake escribió lo que VIO de su env en `leak-claude`.
    leak = (tmp / "leak-claude").read_text() if (tmp / "leak-claude").exists() else "MISSING"
    ok("ANTHROPIC= " in (leak + " ") and "sk-ant-LEAK" not in leak,
       "env saneado: ANTHROPIC_API_KEY NO llegó al CLI (atribución a suscripción)", leak.strip())
    ok("sk-LEAK-openai" not in leak and "gsk_LEAK-groq" not in leak,
       "env saneado: ningún secreto de infra (OPENAI/GROQ) fugó al proceso hijo", leak.strip())
    ok("FAKE_MODE_FILE=\n" in leak or leak.rstrip().endswith("FAKE_MODE_FILE="),
       "env saneado: hasta FAKE_MODE_FILE quedó afuera (allowlist estricta, no denylist)", leak.strip())

    # HIGH #4 — FAIL-CLOSED: si el CLI ejecutó algo por su cuenta (num_turns>1 → exec_events>0),
    # el resultado se DESCARTA (502 model_error), jamás se devuelve como bueno.
    mode_file.write_text("execd")
    code, body = http_json("POST", "/v1/chat/completions",
                           {"model": "claude-code-cli", "messages": [{"role": "user", "content": "x"}]})
    e = body.get("error") or {}
    ok(code == 502 and e.get("type") == "model_error" and "descartado por seguridad" in e.get("message", ""),
       "claude fake exec_events>0 → 502 descartado (no false-green con datos fuera del gate)",
       f"{code}/{e.get('type')}")

    # #10/#11 — model_final HONESTO: sin modelUsage el server NO fabrica un id; ecoa el
    # wrapper-id (claude-code-cli) y el badge de la Sala lo rechaza (cubierto en el narr .mjs).
    mode_file.write_text("nomodel")
    code, body = http_json("POST", "/v1/chat/completions",
                           {"model": "claude-code-cli", "messages": [{"role": "user", "content": "x"}]})
    ok(code == 200 and body.get("model") == "claude-code-cli"
       and (body.get("aleph_cli_brain") or {}).get("model_final_source") == "",
       "claude fake sin modelUsage: model=wrapper-id + source vacío (no inventa modelo)",
       f"{code}/{body.get('model')}")
    mode_file.write_text("ok")

    mode_file.write_text("toolcall")
    code, body = http_json("POST", "/v1/chat/completions",
                           {"model": "claude-code-cli", "messages": [{"role": "user", "content": "sumá"}],
                            "tools": [{"type": "function", "function": {"name": "add", "parameters": {"properties": {"a": {}, "b": {}}}}}]})
    tc = (body["choices"][0]["message"].get("tool_calls") or [])
    ok(code == 200 and len(tc) == 1 and tc[0]["function"]["name"] == "add"
       and body["choices"][0]["finish_reason"] == "tool_calls",
       "claude fake: <function=add> del content → tool_calls OpenAI estructurado", json.dumps(tc)[:100])

    mode_file.write_text("ratelimit")
    code, body = http_json("POST", "/v1/chat/completions",
                           {"model": "claude-code-cli", "messages": [{"role": "user", "content": "x"}]})
    e = body.get("error") or {}
    ok(code == 429 and e.get("type") == "throttled" and e.get("brain_provider") == "claude_cli",
       "claude fake rate-limit: 429 throttled + brain_provider", f"{code}/{e.get('type')}")
    ok(bool(e.get("reset_hint")), "claude fake rate-limit: reset_hint presente", str(e.get("reset_hint")))

    mode_file.write_text("ok")
    code, body = http_json("POST", "/v1/chat/completions",
                           {"model": "codex-cli", "messages": [{"role": "user", "content": "ping"}]})
    ok(code == 200 and body["choices"][0]["message"]["content"] == "PONG-X"
       and body.get("model") == "gpt-5.1-codex-max",
       "codex fake: 200 + texto + model_final reportado", f"{code}/{body.get('model')}")

    mode_file.write_text("ratelimit")
    code, body = http_json("POST", "/v1/chat/completions",
                           {"model": "codex-cli", "messages": [{"role": "user", "content": "x"}]})
    e = body.get("error") or {}
    ok(code == 429 and e.get("type") == "throttled" and e.get("brain_provider") == "codex_cli"
       and "8:00" in (e.get("reset_hint") or ""),
       "codex fake rate-limit: 429 throttled + provider + reset", f"{code}/{e}")

    # estados INDEPENDIENTES: claude ready + codex noauth a la vez (el modo afecta a ambos
    # fakes, así que la independencia se prueba rompiendo el BINARIO de uno solo)
    mode_file.write_text("ok")
    code, body = http_json("GET", "/v1/brains/status")
    provs = body.get("providers") or {}
    ok(code == 200 and provs.get("claude_cli", {}).get("state") == "ready"
       and provs.get("codex_cli", {}).get("state") == "ready",
       "status: ambos ready con fakes ok", json.dumps({k: v.get('state') for k, v in provs.items()}))

    # LOW #2/#23 — forma PÚBLICA del status: sin `binary` (fingerprinting del host), con
    # `installed` booleano en su lugar.
    cc = provs.get("claude_cli", {})
    ok("binary" not in cc and cc.get("installed") is True,
       "status público: sin path del binario, con installed:true (anti-fingerprint)", json.dumps(cc)[:120])

    # #0/#17 — ATRIBUCIÓN api_key: si el CLI reporta authMethod:api_key, el estado sigue
    # READY pero marcado auth_billing:api_key (el copy NO promete $0). No se finge suscripción.
    mode_file.write_text("apikey")
    code, body = http_json("GET", "/v1/brains/status")
    cc = (body.get("providers") or {}).get("claude_cli", {})
    ok(cc.get("state") == "ready" and (cc.get("extra") or {}).get("auth_billing") == "api_key"
       and "por token" in cc.get("detail", ""),
       "status: authMethod api_key → READY pero facturación honesta (por token, no suscripción)",
       json.dumps(cc)[:160])
    mode_file.write_text("ok")

    # MED #1 — ANTI-CSRF DRIVE-BY: un browser cross-site agrega Origin (o un Host de rebinding).
    # El server local legítimo (assembler) NO manda Origin → cualquiera de las dos señales = 403.
    code, body = http_json("POST", "/v1/chat/completions",
                           {"model": "claude-code-cli", "messages": [{"role": "user", "content": "x"}]},
                           headers={"Origin": "https://evil.example"})
    ok(code == 403 and (body.get("error") or {}).get("type") == "forbidden",
       "CSRF: POST con header Origin → 403 (no quema la ventana de la suscripción)", str(code))
    code, body = http_json("GET", "/v1/brains/status", headers={"Host": "attacker.com"})
    ok(code == 403, "CSRF: Host de DNS-rebinding → 403 en el status", str(code))
    # el /health SÍ responde sin gate (probe de liveness legítimo) aun con Origin
    code, _ = http_json("GET", "/health", headers={"Origin": "https://evil.example"})
    ok(code == 200, "health: liveness probe abierto (no filtra estado ni credenciales)", str(code))
finally:
    srv.terminate()
    srv.wait(timeout=5)

# independencia REAL de estados: claude fake ready + codex binario AUSENTE (server nuevo)
env2 = dict(env, PUPPET_CODEX_BIN="/nonexistent/codex-x")
mode_file.write_text("ok")
srv2 = subprocess.Popen([sys.executable, str(REPO / "platform/assembler/cli_brain/server.py")],
                        env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.0)
try:
    code, body = http_json("GET", "/v1/brains/status")
    provs = body.get("providers") or {}
    ok(provs.get("claude_cli", {}).get("state") == "ready"
       and provs.get("codex_cli", {}).get("state") == "not_installed",
       "status: estados INDEPENDIENTES (claude ready · codex not_installed, sin contagio)",
       json.dumps({k: v.get("state") for k, v in provs.items()}))
finally:
    srv2.terminate()
    srv2.wait(timeout=5)

# ═════ G · D4 units ═════
section("G · D4 — parseo del error clasificado + model_final honesto (scope)")
import recipe_assembler as ra  # noqa: E402

err_str = 'HTTP 429: {"error": {"message": "[Claude Code] exit 1", "type": "throttled", "error_kind": "rate_limit", "brain_provider": "claude_cli", "provider_name": "Claude Code", "reset_hint": "18:00"}}'
info = ra._parse_cli_brain_error(err_str)
ok(info.get("type") == "throttled" and info.get("provider_name") == "Claude Code"
   and info.get("reset_hint") == "18:00", "_parse_cli_brain_error extrae el body clasificado", json.dumps(info)[:120])
ok(ra._parse_cli_brain_error("transport: connection refused") == {}, "_parse_cli_brain_error: sin JSON → {}")

rec = {"brain_provider": "claude_cli", "model_route": [{"model": "claude-code-cli", "tier": "primary", "ok": True}]}
ok(ra._honest_model_final({"model": "claude-opus-4-8"}, "claude-code-cli", rec) == "claude-opus-4-8",
   "_honest_model_final: BYO-CLI primary → el REPORTADO")
rec2 = {"brain_provider": "claude_cli", "model_route": [{"model": "x", "tier": "primary", "ok": False},
                                                        {"model": "qwen3:8b", "tier": "oss-direct", "ok": True}]}
ok(ra._honest_model_final({"model": "lo-que-sea"}, "qwen3:8b", rec2) == "qwen3:8b",
   "_honest_model_final: tier fallback → conserva el pedido (semántica histórica)")
rec3 = {"brain_provider": None, "model_route": [{"model": "m", "tier": "primary", "ok": True}]}
ok(ra._honest_model_final({"model": "otro"}, "m", rec3) == "m",
   "_honest_model_final: sin brain_provider → byte-idéntico a lo histórico")

# ═════ H · resolución + validador ═════
section("H · models.py + validador")
import models as m  # noqa: E402

eff = m.resolve_recipe_model({"primary": "x", "base_url": "y", "brain_provider": "claude_cli"})
ok(eff["primary"] == "claude-code-cli" and "8926" in eff["base_url"] and eff["brain_provider"] == "claude_cli",
   "claude_cli rutea al server :8926 + brain_provider en el resolve", json.dumps(eff))
eff = m.resolve_recipe_model({"primary": "x", "base_url": "y", "brain_provider": "codex_cli"})
ok(eff["primary"] == "codex-cli", "codex_cli rutea (simetría)")
eff = m.resolve_recipe_model({"primary": "x", "base_url": "y", "brain_provider": "byok"})
ok(eff["primary"] == "x" and eff["brain_provider"] == "byok", "byok es declarativo (ruteo intacto)")
eff = m.resolve_recipe_model({"primary": "x", "base_url": "y"})
ok(eff["primary"] == "x" and eff["brain_provider"] is None, "sin brain_provider → histórico byte-idéntico")
os.environ["PUPPET_BRAIN"] = "oss"
eff = m.resolve_recipe_model({"brain_provider": "claude_cli"})
ok(eff["primary"] == "openai/gpt-oss-120b", "PUPPET_BRAIN sigue mandando sobre brain_provider (palanca de ops)")
# #7/#16 — ATRIBUCIÓN: si ops pisa un cerebro CLI, NO se sigue reportando brain_provider
# (el badge diría 'tu suscripción' mientras corre Groq → mentira). Se anula + se marca override.
ok(eff.get("brain_provider") is None and eff.get("brain_provider_overridden") is True,
   "PUPPET_BRAIN pisa CLI → brain_provider anulado + flag override (badge no miente)",
   f"bp={eff.get('brain_provider')} ov={eff.get('brain_provider_overridden')}")
os.environ["PUPPET_BRAIN"] = "claude_cli"
eff = m.resolve_recipe_model({"brain_provider": "claude_cli"})
ok(eff.get("brain_provider") == "claude_cli" and not eff.get("brain_provider_overridden"),
   "PUPPET_BRAIN == el mismo CLI → NO es override (coherente, se reporta)")
del os.environ["PUPPET_BRAIN"]

from app.phase1.recipe_validator import validate_recipe, RecipeValidationError  # noqa: E402
BASE = {"schema_version": "v1", "meta": {"name": "t", "nicho": "general"},
        "model": {"primary": "claude-code-cli", "base_url": "http://127.0.0.1:8926/v1",
                  "temperature": 0, "max_tokens": 512, "max_turns": 4},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
                 "tool_filters": {"calc": ["add"]}},
        "rag": {"enabled": False}}


def _valid(extra: dict) -> tuple[bool, list]:
    r = {k: (dict(v) if isinstance(v, dict) else v) for k, v in BASE.items()}
    r["model"] = dict(BASE["model"], **extra)
    try:
        validate_recipe(r)
        return True, []
    except RecipeValidationError as e:
        return False, list(e.errors)


from cli_brain.registry import brain_provider_enum as _bp_enum
for bp in sorted(_bp_enum()):
    good, errs = _valid({"brain_provider": bp})
    ok(good, f"validador acepta brain_provider={bp}", "; ".join(errs)[:100])
good, errs = _valid({"brain_provider": "gpt6-magic"})
ok(not good and any("brain_provider" in e for e in errs), "validador RECHAZA basura (enum cerrado)")
good, _ = _valid({})
ok(good, "sin brain_provider → válido (aditivo)")

# ═════ veredicto ═════
print("\n" + "═" * 60)
if FAILS:
    print(f"✗ {len(FAILS)} FALLA(S):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("✓ verify_byo_cli: TODO VERDE")
