#!/usr/bin/env python3
"""
deleg_server.py — MCP server REAL (stdio, JSON-RPC 2.0, solo stdlib) usado por los tests
del AGENTE ANIDADO (paso 2). NO es producción.

A diferencia del SPIKE (que stubeaba el registry con funciones en proceso), acá las tools
son un MCP server REAL que el motor bootea por subprocess y consume vía registry.call. Eso
hace que los 4 ataques ejerciten el camino REAL del motor (registry.call + gate + workdir),
no un stub del registry. Lo único stubeado en los ATAQUES es el CEREBRO (ver FakeBrain en
verify_delegation_real.py); las tools son reales.

Tools:
  read_data(q)            — benigna (lectura).
  write_note(text)        — benigna; escribe note.txt DENTRO de PUPPET_WORKDIR (RIEL #4).
  slow_op(seconds)        — duerme `seconds` (RIEL #3, deadline).
  send_email(to, body)    — SEND: si el gate funciona, NUNCA corre sin OK (RIEL #1). Si
                            llega a correr, deja EMAIL_SENT.flag en PUPPET_WORKDIR (leak).
  place_order(item)       — MONEY: idéntico patrón; deja ORDER_PLACED.flag.

write_note / send_email / place_order escriben DENTRO de ${PUPPET_WORKDIR} para poder probar
el aislamiento de workdir (cada agente escribe en SU dir) y el "leak flag" del gate.
"""

import json
import os
import sys
import time
from pathlib import Path

TOOLS = [
    {"name": "read_data", "description": "Lee un dato (benigno, solo lectura).",
     "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": []}},
    {"name": "write_note", "description": "Escribe una nota local (benigno).",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "slow_op", "description": "Operación lenta: duerme `seconds` segundos.",
     "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}, "required": []}},
    {"name": "send_email", "description": "Manda un correo (acción de SALIDA, sensible).",
     "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}, "body": {"type": "string"}}, "required": ["to"]}},
    {"name": "place_order", "description": "Coloca una orden de compra (toca PLATA, sensible).",
     "inputSchema": {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]}},
]


def _workdir() -> Path:
    wd = os.environ.get("PUPPET_WORKDIR") or "."
    p = Path(wd)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def _call(name: str, args: dict) -> str:
    if name == "read_data":
        return f"datos[{args.get('q', '')}] = [1, 2, 3]"
    if name == "write_note":
        path = _workdir() / "note.txt"
        path.write_text(str(args.get("text", "")), encoding="utf-8")
        return f"escribí {path}"
    if name == "slow_op":
        time.sleep(float(args.get("seconds", 0.3)))
        return f"dormí {args.get('seconds', 0.3)}s"
    if name == "send_email":
        # Si el gate funciona, esto NUNCA se ejecuta sin OK explícito.
        (_workdir() / "EMAIL_SENT.flag").write_text("leak", encoding="utf-8")
        return "CORREO ENVIADO (no debería pasar sin OK)"
    if name == "place_order":
        (_workdir() / "ORDER_PLACED.flag").write_text("leak", encoding="utf-8")
        return "ORDEN COLOCADA (no debería pasar sin OK)"
    return f"{name}({json.dumps(args)}) -> ok"


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})
    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "deleg-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            text = _call(name, args)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
