#!/usr/bin/env python3
"""
brain_shim.py — SHIM DEV del cerebro: OpenAI /chat/completions → Anthropic Messages → Opus 4.8 real.

C6: el brain del producto es Opus 4.8 real. En PROD el camino es OpenRouter con crédito. En
DEV no hay crédito (OpenRouter → 402), así que este shim local en :8923 le da al assembler un
endpoint OpenAI-compat (lo único que el assembler habla) que por dentro llama a la API NATIVA
de Anthropic (`POST /v1/messages`, `claude-opus-4-8`). models.py apunta el alias `brain` acá
con `PUPPET_BRAIN_SHIM=1`.

HONESTO, CERO TEATRO:
  - Con `ANTHROPIC_API_KEY` (o PUPPET_BRAIN_SHIM_ANTHROPIC_KEY) → Opus 4.8 REAL.
  - SIN key, o si Anthropic falla → responde HTTP 502 (no finge una respuesta). El assembler
    lo trata como "el brain no respondió" y CAE — visiblemente — a la red OSS (record["degraded"]
    + aviso). Nunca un modelo barato haciéndose pasar por el cerebro.

DISEÑO: la traducción OpenAI↔Anthropic vive en FUNCIONES PURAS (testeables sin red, ver
test_brain_shim.py); el servidor HTTP es una cáscara fina. Stdlib only (http.server + urllib),
igual que el resto del assembler — el shim debe "arrancar y andar" sin pip install.

NOTA Opus 4.8: la API de Anthropic RECHAZA (400) `temperature`/`top_p`/`top_k` y el thinking con
budget en Opus 4.8. El assembler SIEMPRE manda `temperature` — así que el shim lo DESCARTA. El
thinking se omite (corre sin thinking, suficiente para el loop de tools).

Correr:   ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python brain_shim.py
Probar:   curl -s localhost:8923/health
          curl -s -XPOST localhost:8923/v1/chat/completions -d '{"model":"x","messages":[{"role":"user","content":"hola"}],"max_tokens":16}'
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANTHROPIC_BASE = os.environ.get("ANTHROPIC_API_BASE", "https://api.anthropic.com")
ANTHROPIC_VERSION = os.environ.get("ANTHROPIC_VERSION", "2023-06-01")
# Id del modelo Anthropic upstream (la API usa guiones: claude-opus-4-8).
UPSTREAM_MODEL = os.environ.get("PUPPET_BRAIN_SHIM_ANTHROPIC_MODEL", "claude-opus-4-8")
# Id que el shim ANUNCIA y devuelve al cliente OpenAI (lo que termina en model_final).
ADVERTISED_MODEL = os.environ.get("PUPPET_BRAIN_SHIM_MODEL", "claude-opus-4.8")
DEFAULT_MAX_TOKENS = int(os.environ.get("PUPPET_BRAIN_SHIM_MAX_TOKENS", "2048"))


def _api_key() -> str:
    return (os.environ.get("PUPPET_BRAIN_SHIM_ANTHROPIC_KEY")
            or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


# ── TRADUCCIÓN OpenAI → Anthropic (funciones puras) ──────────────────────────────

def _content_to_anthropic_blocks(content) -> list:
    """content OpenAI (str | lista de partes) → lista de bloques Anthropic."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks: list = []
    for part in content:
        if not isinstance(part, dict):
            blocks.append({"type": "text", "text": str(part)})
            continue
        ptype = part.get("type")
        if ptype == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url.startswith("data:"):
                # data:<media_type>;base64,<data>
                try:
                    head, data = url.split(",", 1)
                    media_type = head.split(":", 1)[1].split(";", 1)[0]
                    blocks.append({"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": data}})
                except (ValueError, IndexError):
                    pass
            elif url:
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
    return blocks


def openai_to_anthropic(body: dict) -> dict:
    """Request OpenAI /chat/completions → request Anthropic /v1/messages.

    - system: concatena TODOS los mensajes role=system (Anthropic lo lleva top-level).
    - assistant.tool_calls → bloques tool_use; role=tool → bloques tool_result (en user).
    - DESCARTA temperature/top_p/top_k (Opus 4.8 los rechaza con 400).
    - Mergea mensajes consecutivos del mismo rol (Anthropic los combina; evita rarezas).
    """
    msgs_in = body.get("messages") or []
    system_parts: list[str] = []
    out_msgs: list = []

    def _append(role: str, blocks: list) -> None:
        if not blocks:
            return
        if out_msgs and out_msgs[-1]["role"] == role:
            out_msgs[-1]["content"].extend(blocks)
        else:
            out_msgs.append({"role": role, "content": list(blocks)})

    for m in msgs_in:
        role = m.get("role")
        if role == "system":
            txt = m.get("content")
            if isinstance(txt, str) and txt:
                system_parts.append(txt)
            elif isinstance(txt, list):
                system_parts += [b.get("text", "") for b in txt if isinstance(b, dict) and b.get("type") == "text"]
        elif role == "tool":
            _append("user", [{
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id") or "",
                "content": m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content")),
            }])
        elif role == "assistant":
            blocks = _content_to_anthropic_blocks(m.get("content"))
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                blocks.append({"type": "tool_use", "id": tc.get("id") or "call",
                               "name": fn.get("name") or "", "input": args if isinstance(args, dict) else {}})
            _append("assistant", blocks)
        else:  # user (o cualquier otro → user)
            _append("user", _content_to_anthropic_blocks(m.get("content")))

    out: dict = {
        "model": UPSTREAM_MODEL,
        "max_tokens": int(body.get("max_tokens") or DEFAULT_MAX_TOKENS),
        "messages": out_msgs,
    }
    if system_parts:
        out["system"] = "\n\n".join(p for p in system_parts if p)
    tools = openai_tools_to_anthropic(body.get("tools"))
    if tools:
        out["tools"] = tools
    # NOTA: temperature/top_p/top_k OMITIDOS a propósito (400 en Opus 4.8).
    return out


def openai_tools_to_anthropic(tools) -> list:
    """[{type:function, function:{name,description,parameters}}] → [{name,description,input_schema}]."""
    out: list = []
    for t in (tools or []):
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if t.get("type") == "function" else t
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


# ── TRADUCCIÓN Anthropic → OpenAI (funciones puras) ──────────────────────────────

def _finish_reason(stop_reason) -> str:
    return {
        "tool_use": "tool_calls",
        "max_tokens": "length",
        "end_turn": "stop",
        "stop_sequence": "stop",
        "refusal": "stop",
    }.get(stop_reason, "stop")


def anthropic_to_openai(adata: dict, *, advertised_model: str, req_id: str = "chatcmpl-shim", created: int = 0) -> dict:
    """Response Anthropic /v1/messages → response OpenAI /chat/completions."""
    content_blocks = adata.get("content") or []
    text = "".join(b.get("text", "") for b in content_blocks if isinstance(b, dict) and b.get("type") == "text")
    tool_calls = []
    for b in content_blocks:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            tool_calls.append({
                "id": b.get("id") or "call",
                "type": "function",
                "function": {"name": b.get("name") or "", "arguments": json.dumps(b.get("input") or {})},
            })
    stop_reason = adata.get("stop_reason")
    if stop_reason == "refusal" and not text:
        text = "El modelo declinó la solicitud por políticas de seguridad (refusal)."
    message: dict = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage_in = adata.get("usage") or {}
    pt = int(usage_in.get("input_tokens") or 0)
    ct = int(usage_in.get("output_tokens") or 0)
    return {
        "id": req_id,
        "object": "chat.completion",
        "created": created,
        "model": advertised_model,
        "choices": [{"index": 0, "finish_reason": _finish_reason(stop_reason), "message": message}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
    }


# ── LLAMADA NATIVA A ANTHROPIC (urllib) ──────────────────────────────────────────

def call_anthropic(anthropic_body: dict, api_key: str, *, base: str = ANTHROPIC_BASE,
                   version: str = ANTHROPIC_VERSION, timeout: float = 120.0) -> dict:
    """POST nativo a Anthropic /v1/messages. Levanta RuntimeError ante error (honesto)."""
    endpoint = base.rstrip("/") + "/v1/messages"
    data = json.dumps(anthropic_body).encode()
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": version,
    }
    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"anthropic HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"anthropic transport: {getattr(e, 'reason', e)}")


# ── SERVIDOR HTTP (cáscara fina) ─────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):  # silencio (no ensuciar stderr del run)
        pass

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/health", ""):
            self._json(200, {"object": "list", "data": [{"id": ADVERTISED_MODEL}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(n).decode() or "{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": {"message": "invalid json", "type": "bad_request"}})
            return
        key = _api_key()
        if not key:
            # HONESTO: sin key no hay Opus real → 502, el assembler CAE (visiblemente) a OSS.
            self._json(502, {"error": {"type": "no_key", "message": (
                "brain_shim: sin ANTHROPIC_API_KEY — no hay Opus real; el cascade debe caer "
                "(visiblemente) a la red OSS. No se finge una respuesta.")}})
            return
        try:
            adata = call_anthropic(openai_to_anthropic(body), key)
        except RuntimeError as exc:
            self._json(502, {"error": {"type": "upstream", "message": str(exc)}})
            return
        out = anthropic_to_openai(
            adata, advertised_model=ADVERTISED_MODEL,
            req_id="chatcmpl-" + (adata.get("id") or "shim"), created=int(time.time()))
        self._json(200, out)


def main() -> None:
    port = int(os.environ.get("PUPPET_BRAIN_SHIM_PORT", "8923"))
    have_key = bool(_api_key())
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[brain_shim] :{port} → Anthropic {UPSTREAM_MODEL} (advertised {ADVERTISED_MODEL}) "
          f"| key={'present' if have_key else 'MISSING (will 502 → visible fallback)'}", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
