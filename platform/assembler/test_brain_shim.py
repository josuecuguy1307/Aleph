#!/usr/bin/env python3
"""
test_brain_shim.py — el SHIM DEV del cerebro (brain_shim.py). Hermético, sin Anthropic real.

Verifica lo que el shim DEBE garantizar para que "brain → Opus real vía shim" no sea teatro:
  - traducción OpenAI→Anthropic correcta (system concatenado, tool_use/tool_result, tools),
  - DESCARTA temperature/top_p/top_k (Opus 4.8 las rechaza con 400),
  - traducción Anthropic→OpenAI correcta (text, tool_calls, finish_reason, usage mapeado),
  - round-trip HTTP contra un upstream Anthropic FALSO (puertos efímeros, NO toca :8923),
  - SIN key → HTTP 502 honesto (el assembler cae visiblemente; el shim NO finge una respuesta).

Run:  python3 test_brain_shim.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[FAIL] {name} — {detail}")


# ── upstream Anthropic FALSO (captura el body recibido, devuelve un /v1/messages canónico) ──
_CAPTURED: dict = {}


class _FakeAnthropic(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        _CAPTURED["body"] = json.loads(self.rfile.read(n).decode() or "{}")
        _CAPTURED["x-api-key"] = self.headers.get("x-api-key")
        _CAPTURED["anthropic-version"] = self.headers.get("anthropic-version")
        resp = {
            "id": "msg_fake123",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-8",
            "content": [
                {"type": "text", "text": "cuarenta y dos"},
                {"type": "tool_use", "id": "toolu_1", "name": "add", "input": {"a": 21, "b": 21}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 123, "output_tokens": 7},
        }
        out = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


# Arrancar el upstream falso ANTES de importar brain_shim (ANTHROPIC_BASE se lee al importar).
_fake = ThreadingHTTPServer(("127.0.0.1", 0), _FakeAnthropic)
_fake_port = _fake.server_address[1]
threading.Thread(target=_fake.serve_forever, daemon=True).start()
os.environ["ANTHROPIC_API_BASE"] = f"http://127.0.0.1:{_fake_port}"
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"

import brain_shim as bs  # noqa: E402


# ── 1. openai_to_anthropic: system, tools, tool_use/result, SIN sampling params ──
body = {
    "model": "claude-opus-4.8",
    "temperature": 0.7, "top_p": 0.9, "top_k": 40,
    "max_tokens": 99,
    "messages": [
        {"role": "system", "content": "Sos cálculo."},
        {"role": "system", "content": "Respondé solo el número."},
        {"role": "user", "content": "21+21?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_a", "type": "function", "function": {"name": "add", "arguments": "{\"a\":21,\"b\":21}"}}]},
        {"role": "tool", "tool_call_id": "call_a", "content": "42"},
    ],
    "tools": [{"type": "function", "function": {
        "name": "add", "description": "suma", "parameters": {"type": "object", "properties": {"a": {"type": "number"}}}}}],
}
a = bs.openai_to_anthropic(body)
check("1.1 NO reenvía temperature (400 en Opus 4.8)", "temperature" not in a, str(list(a.keys())))
check("1.2 NO reenvía top_p / top_k", "top_p" not in a and "top_k" not in a, str(list(a.keys())))
check("1.3 system concatena los dos system", a.get("system") == "Sos cálculo.\n\nRespondé solo el número.", repr(a.get("system")))
check("1.4 max_tokens preservado", a.get("max_tokens") == 99, str(a.get("max_tokens")))
check("1.5 modelo upstream = id Anthropic (guiones)", a.get("model") == bs.UPSTREAM_MODEL, str(a.get("model")))
check("1.6 tools → input_schema", a.get("tools") and a["tools"][0].get("input_schema", {}).get("type") == "object", str(a.get("tools")))
# mensajes: user texto, assistant con tool_use, user con tool_result
roles = [m["role"] for m in a["messages"]]
check("1.7 roles user/assistant/user", roles == ["user", "assistant", "user"], str(roles))
asst = a["messages"][1]["content"]
check("1.8 assistant lleva bloque tool_use con input parseado",
      any(b.get("type") == "tool_use" and b.get("input") == {"a": 21, "b": 21} for b in asst), str(asst))
tres = a["messages"][2]["content"]
check("1.9 tool → bloque tool_result con tool_use_id", tres and tres[0].get("type") == "tool_result"
      and tres[0].get("tool_use_id") == "call_a", str(tres))


# ── 2. anthropic_to_openai: text, tool_calls, finish_reason, usage ──
adata = {
    "content": [{"type": "text", "text": "hola"}, {"type": "tool_use", "id": "t1", "name": "mul", "input": {"x": 2}}],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 50, "output_tokens": 9},
}
o = bs.anthropic_to_openai(adata, advertised_model="claude-opus-4.8")
msg = o["choices"][0]["message"]
check("2.1 object chat.completion", o.get("object") == "chat.completion", str(o.get("object")))
check("2.2 model = advertised (lo que será model_final)", o.get("model") == "claude-opus-4.8", str(o.get("model")))
check("2.3 text en content", msg.get("content") == "hola", repr(msg.get("content")))
check("2.4 tool_use → tool_calls con arguments JSON-string",
      msg.get("tool_calls") and msg["tool_calls"][0]["function"]["arguments"] == json.dumps({"x": 2}), str(msg.get("tool_calls")))
check("2.5 finish_reason tool_use → tool_calls", o["choices"][0]["finish_reason"] == "tool_calls", str(o["choices"][0]["finish_reason"]))
check("2.6 usage mapeado input→prompt, output→completion",
      o["usage"] == {"prompt_tokens": 50, "completion_tokens": 9, "total_tokens": 59}, str(o["usage"]))
check("2.7 refusal sin texto → mensaje honesto + finish stop",
      (lambda r: r["choices"][0]["finish_reason"] == "stop" and r["choices"][0]["message"]["content"])(
          bs.anthropic_to_openai({"content": [], "stop_reason": "refusal", "usage": {}}, advertised_model="x")))


# ── 3. round-trip HTTP: shim (puerto efímero) → upstream falso → shim → cliente ──
shim = ThreadingHTTPServer(("127.0.0.1", 0), bs._Handler)
shim_port = shim.server_address[1]
threading.Thread(target=shim.serve_forever, daemon=True).start()
try:
    req = urllib.request.Request(
        f"http://127.0.0.1:{shim_port}/v1/chat/completions",
        data=json.dumps({"model": "claude-opus-4.8", "temperature": 0,
                         "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "21+21"}],
                         "max_tokens": 32}).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        rt = json.loads(r.read().decode())
    check("3.1 round-trip → object chat.completion", rt.get("object") == "chat.completion", str(rt.get("object")))
    check("3.2 round-trip → content del upstream falso", rt["choices"][0]["message"]["content"] == "cuarenta y dos", str(rt["choices"][0]["message"].get("content")))
    check("3.3 round-trip → tool_calls del upstream", bool(rt["choices"][0]["message"].get("tool_calls")), str(rt["choices"][0]["message"].get("tool_calls")))
    check("3.4 round-trip → usage mapeado", rt["usage"]["prompt_tokens"] == 123 and rt["usage"]["completion_tokens"] == 7, str(rt.get("usage")))
    check("3.5 el upstream recibió body SIN temperature", "temperature" not in _CAPTURED.get("body", {}), str(list(_CAPTURED.get("body", {}).keys())))
    check("3.6 el shim mandó x-api-key + anthropic-version", _CAPTURED.get("x-api-key") == "test-key-not-real"
          and _CAPTURED.get("anthropic-version") == bs.ANTHROPIC_VERSION, str({k: _CAPTURED.get(k) for k in ("x-api-key", "anthropic-version")}))

    # ── 4. SIN key → 502 honesto (no finge respuesta) ──
    _saved = (os.environ.pop("ANTHROPIC_API_KEY", None), os.environ.pop("PUPPET_BRAIN_SHIM_ANTHROPIC_KEY", None))
    try:
        code = None
        try:
            req2 = urllib.request.Request(
                f"http://127.0.0.1:{shim_port}/v1/chat/completions",
                data=json.dumps({"messages": [{"role": "user", "content": "x"}], "max_tokens": 8}).encode(),
                headers={"content-type": "application/json"}, method="POST")
            urllib.request.urlopen(req2, timeout=10)
        except urllib.error.HTTPError as e:
            code = e.code
        check("4.1 sin key → HTTP 502 (honesto, no finge)", code == 502, str(code))
    finally:
        if _saved[0] is not None:
            os.environ["ANTHROPIC_API_KEY"] = _saved[0]
finally:
    shim.shutdown()
    _fake.shutdown()


print(f"\n=== {_passed} passed, {_failed} failed ===")
sys.exit(1 if _failed else 0)
