#!/usr/bin/env python3
"""
shim_claude_code.py — OPCIÓN C: endpoint OpenAI-compatible de PURA COGNICIÓN sobre
`claude -p --model opus --output-format json`, con las tools de Claude Code DESHABILITADAS.

El harness de Aleph (assembler) sigue manejando el LOOP, el BELT y los GATES. Claude Code
SOLO provee el next-message (la cognición). Aleph ejecuta las tools del belt contra el
engine real; Claude Code NUNCA ejecuta nada internamente (tools off + instrucción explícita).

Cómo encaja en el contrato del assembler (verificado en assembler.py:_chat):
  - POST <base_url>/chat/completions con {model, messages, tools, tool_choice}.
  - Respuesta OpenAI: {choices:[{message:{role,content}}], usage}.
  - El assembler ESCANEA el `content` por `<function=NOMBRE>{json}</function>` (y harmony)
    cuando no hay `tool_calls` structured → ejecuta la tool y devuelve el resultado en la
    próxima request. Por eso el shim instruye a Opus a emitir EXACTAMENTE ese formato.
  - model_final = el `model` (primary) de la receta → poné primary="claude-code-opus-4.8".

NO toca models.py (congelado en main). Es eval-local: la receta del eval apunta su
base_url a este shim (key dummy).

Throttle: si `claude` devuelve is_error / api_error_status de rate-limit / exit≠0 con señal
de límite → responde HTTP 429 con el motivo. Corré la matriz con PUPPET_OSS_DIRECT=0 para que
un 429 NO se enmascare con el fallback OSS: el run falla limpio y el harness para y reporta.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("SHIM_PORT", "8923"))
CLAUDE = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
CLAUDE_MODEL = os.environ.get("SHIM_CLAUDE_MODEL", "opus")
MODEL_LABEL = os.environ.get("SHIM_MODEL_LABEL", "claude-code-opus-4.8")
CALL_TIMEOUT = float(os.environ.get("SHIM_CALL_TIMEOUT", "180"))

# Claude Code built-in tools OFF → pura cognición (Aleph ejecuta el belt, no Claude Code).
DISALLOWED = ["Bash", "BashOutput", "KillShell", "Read", "Edit", "Write", "NotebookEdit",
              "Glob", "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite", "SlashCommand"]

# señales de throttle/limite del Max plan (heurística sobre stderr/result)
_THROTTLE_RE = re.compile(r"(rate.?limit|usage limit|overloaded|429|too many requests|"
                          r"quota|capacity|temporarily unavailable|exceeded)", re.I)

_log = sys.stderr


def _tools_block(tools: list) -> str:
    if not tools:
        return ""
    lines = ["", "HERRAMIENTAS DISPONIBLES (las ejecuta EL SISTEMA, no tú):"]
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name", "?")
        desc = (fn.get("description") or "").strip().replace("\n", " ")[:200]
        params = (fn.get("parameters") or {}).get("properties") or {}
        pkeys = ", ".join(params.keys())
        lines.append(f"  - {name}({pkeys}): {desc}")
    lines += [
        "",
        "Para LLAMAR una herramienta respondé SOLO con una línea, sin nada más:",
        '  <function=NOMBRE>{"arg":"valor"}</function>',
        "El sistema la ejecuta de verdad y te devuelve el resultado en el próximo mensaje.",
        "Para la RESPUESTA FINAL escribí texto normal (sin <function=...>).",
        "Reglas: no ejecutes nada vos mismo, no inventes resultados de herramientas, "
        "fundamentá los datos SOLO en lo que la herramienta devuelva.",
    ]
    return "\n".join(lines)


def _render_prompt(messages: list, tools: list) -> str:
    sys_parts, convo = [], []
    id2name = {}
    # primer paso: mapear tool_call ids → nombre (para etiquetar resultados role:tool)
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            id2name[tc.get("id")] = (tc.get("function") or {}).get("name", "tool")
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            if content:
                sys_parts.append(content if isinstance(content, str) else json.dumps(content))
        elif role == "user":
            convo.append(f"[Usuario]: {content}")
        elif role == "assistant":
            tcs = m.get("tool_calls") or []
            if tcs:
                for tc in tcs:
                    fn = tc.get("function") or {}
                    convo.append(f"[Tú llamaste]: <function={fn.get('name')}>{fn.get('arguments')}</function>")
            if content:
                convo.append(f"[Tú]: {content}")
        elif role == "tool":
            nm = id2name.get(m.get("tool_call_id"), m.get("name", "herramienta"))
            convo.append(f"[Resultado de {nm}]: {content}")
    head = "\n".join(sys_parts) if sys_parts else "Eres un agente útil y honesto."
    body = "\n".join(convo)
    return (f"{head}\n{_tools_block(tools)}\n\n=== CONVERSACIÓN ===\n{body}\n\n"
            f"Da el PRÓXIMO PASO: una sola llamada a herramienta (formato <function=...>) "
            f"o la respuesta final. No repitas pasos ya hechos.")


_VALID_EFFORT = {"low", "medium", "high", "max"}


def _run_claude(prompt: str, effort: str = None) -> dict:
    """Corre claude -p pura-cognición. Devuelve {ok, text, usage, throttled, error, effort}.
    TICKET 27·3 · DIAL DE ESFUERZO: si `effort` ∈ {low,medium,high,max}, pasa `--effort <level>`
    al CLI (flag REAL, verificable en el forense: qué effort corrió el turno)."""
    _eff = (effort or "").strip().lower() if effort else None
    _eff = _eff if _eff in _VALID_EFFORT else None
    cmd = [CLAUDE, "-p", prompt, "--model", CLAUDE_MODEL,
           "--output-format", "json", "--disallowedTools", *DISALLOWED]
    if _eff:
        cmd += ["--effort", _eff]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "throttled": False, "error": "claude -p timeout", "text": "", "usage": {}}
    out, err = r.stdout or "", r.stderr or ""
    if r.returncode != 0:
        thr = bool(_THROTTLE_RE.search(out + err))
        return {"ok": False, "throttled": thr, "error": f"exit {r.returncode}: {(err or out)[:300]}",
                "text": "", "usage": {}}
    try:
        j = json.loads(out)
    except Exception as e:
        return {"ok": False, "throttled": False, "error": f"bad json: {e}: {out[:200]}", "text": "", "usage": {}}
    if j.get("is_error") or j.get("api_error_status"):
        blob = json.dumps(j)
        return {"ok": False, "throttled": bool(_THROTTLE_RE.search(blob)),
                "error": f"claude is_error: {j.get('subtype')}/{j.get('api_error_status')}",
                "text": "", "usage": {}}
    u = j.get("usage") or {}
    return {"ok": True, "throttled": False, "error": None, "text": j.get("result", "") or "",
            "usage": {"prompt_tokens": u.get("input_tokens", 0),
                      "completion_tokens": u.get("output_tokens", 0)}}


# ── traducción de la RESPUESTA: <function=NOMBRE>{json}</function> → tool_calls OpenAI ──
# Opus llama tools emitiéndolas como TEXTO en el content (el shim inlinea las tools por texto
# y Opus responde con ese marcador). Esto las RE-EMITE como tool_calls estructurado SIN tocar
# el camino texto: el content se conserva tal cual (fallback para consumidores que todavía
# escanean <function=> — sobre todo la FORJA, que lee JSON crudo del content). Cero-teatro:
# solo se emite tool_calls si Opus REALMENTE puso un <function=>; si nada parsea → [] (texto).
_FUNC_RE = re.compile(r"<function=\s*([A-Za-z0-9_.\-]+)\s*>(.*?)</function>", re.DOTALL)
_FUNC_OPEN_RE = re.compile(r"<function=\s*([A-Za-z0-9_.\-]+)\s*>", re.DOTALL)


def _balanced_json(s: str) -> str:
    """Primer objeto/array JSON balanceado al inicio de `s` (tolera multilínea y strings con
    llaves). "" si no hay uno bien cerrado. Sirve al fallback de un <function=> sin cierre."""
    s = s.lstrip()
    if not s or s[0] not in "{[":
        return ""
    open_c, close_c = (("{", "}") if s[0] == "{" else ("[", "]"))
    depth = 0
    in_str = esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_c:
            depth += 1
        elif ch == close_c:
            depth -= 1
            if depth == 0:
                return s[:i + 1]
    return ""


def _mk_call(name: str, raw_args: str):
    """Arma un tool_call OpenAI. Normaliza el json si parsea; si NO parsea devuelve None
    (→ el marcador se queda como texto: no fabricamos args inválidos, no reventamos)."""
    name = (name or "").strip()
    raw_args = (raw_args or "").strip()
    if not name:
        return None
    if not raw_args:
        args_str = "{}"
    else:
        try:
            args_str = json.dumps(json.loads(raw_args), ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            return None
    return {"id": "call_" + uuid.uuid4().hex[:24], "type": "function",
            "function": {"name": name, "arguments": args_str}}


def _extract_tool_calls(text: str) -> list:
    """Traduce los marcadores <function=NOMBRE>{json}</function> del content a tool_calls
    OpenAI. Robusto: json multilínea + varias llamadas (finditer + DOTALL). Si nada parsea
    → [] y el caller cae a texto. NUNCA tira: cualquier error → []."""
    try:
        text = text or ""
        calls = []
        for m in _FUNC_RE.finditer(text):
            c = _mk_call(m.group(1), m.group(2))
            if c:
                calls.append(c)
        if calls:
            return calls
        # fallback: opener sin </function> de cierre (la salida se cortó) → json balanceado
        m = _FUNC_OPEN_RE.search(text)
        if m:
            raw = _balanced_json(text[m.end():])
            c = _mk_call(m.group(1), raw) if raw else None
            if c:
                return [c]
        return []
    except Exception:  # robustez dura: ante cualquier sorpresa, cae a texto
        return []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models") or self.path == "/health":
            self._send(200, {"object": "list", "data": [{"id": MODEL_LABEL}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n).decode())
        except Exception as e:
            return self._send(400, {"error": {"message": f"bad request: {e}"}})

        model = req.get("model", MODEL_LABEL)
        # TICKET 27·3 · el effort del turno viaja en el request (lo pone el assembler desde la receta);
        # el shim lo baja al CLI y lo REPORTA en la respuesta (forense verificable).
        effort = req.get("effort")
        prompt = _render_prompt(req.get("messages", []), req.get("tools", []))
        _efftag = (effort or "").strip().lower()
        _efftag = _efftag if _efftag in _VALID_EFFORT else None
        print(f"[shim] → claude ({len(prompt)} chars, model={CLAUDE_MODEL}"
              + (f", effort={_efftag}" if _efftag else "") + ")", file=_log, flush=True)
        t0 = time.time()
        res = _run_claude(prompt, effort=effort)
        dt = time.time() - t0

        if not res["ok"]:
            code = 429 if res["throttled"] else 502
            tag = "THROTTLE" if res["throttled"] else "ERROR"
            print(f"[shim] ✗ {tag} ({dt:.1f}s): {res['error']}", file=_log, flush=True)
            return self._send(code, {"error": {"message": res["error"],
                                               "type": "throttled" if res["throttled"] else "shim_error"}})

        txt = res["text"]
        tool_calls = _extract_tool_calls(txt)
        has_call = bool(tool_calls)
        print(f"[shim] ✓ ({dt:.1f}s) {'tool-call' if has_call else 'final'} "
              f"out_tok={res['usage'].get('completion_tokens')}"
              + (f" ×{len(tool_calls)} structured" if has_call else ""),
              file=_log, flush=True)
        # content SIEMPRE conserva el texto (fallback para la forja / escáneres de <function=>).
        # Cuando hay llamada: + tool_calls estructurado y finish_reason="tool_calls" (estándar
        # OpenAI); sin marcador parseable: respuesta normal (content texto, finish_reason="stop").
        message = {"role": "assistant", "content": txt}
        finish_reason = "stop"
        if has_call:
            message["tool_calls"] = tool_calls
            finish_reason = "tool_calls"
        resp = {
            "id": "chatcmpl-" + uuid.uuid4().hex[:12],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            # TICKET 27·3 · forense: el effort REAL con el que corrió el CLI este turno.
            "effort": _efftag,
            "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
            "usage": {"prompt_tokens": res["usage"].get("prompt_tokens", 0),
                      "completion_tokens": res["usage"].get("completion_tokens", 0),
                      "total_tokens": res["usage"].get("prompt_tokens", 0) + res["usage"].get("completion_tokens", 0)},
        }
        self._send(200, resp)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[shim] OpenAI-compat claude-code-opus shim en http://127.0.0.1:{PORT}/v1 "
          f"(model_label={MODEL_LABEL}, claude={CLAUDE} --model {CLAUDE_MODEL}, tools OFF)",
          file=_log, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
