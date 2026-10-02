#!/usr/bin/env python3
"""
send_stub_server.py — mini MCP stdio server (JSON-RPC 2.0), KEYLESS, stdlib-only.

Fixture ejecutable del SEND-GATE (F5) para verify_integra_final_motor.py. Expone UNA tool
(`send_email`) cuyo nombre cae fail-closed en el gate (ApprovalGate) → needs_ok forzado: el
motor NUNCA la ejecuta sin OK humano. Si por un bug llegara a correr, devuelve un payload
marcado ("SENT_should_not_happen") para que el harness lo cace.

Modelado 1:1 sobre catalog/templates/f5-gatecheck/send_stub_server.py (copia self-contained
para que el done-bar sea reproducible sin depender de archivos untracked). Sin red, sin deps.
"""

import json
import sys

TOOLS = [
    {
        "name": "send_email",
        "description": (
            "Envía un correo electrónico a un destinatario. "
            "Parámetros: to (destinatario), subject (asunto), body (cuerpo)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Email del destinatario"},
                "subject": {"type": "string", "description": "Asunto del correo"},
                "body": {"type": "string", "description": "Cuerpo del correo"},
            },
            "required": ["to", "subject", "body"],
        },
    }
]


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "send-stub-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name == "send_email":
            # ESTO NO DEBERÍA OCURRIR sin OK: el gate fuerza send_email a needs_ok.
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": (
                    "SENT_should_not_happen to=%s subject=%s"
                    % (args.get("to", ""), args.get("subject", "")))}],
                "isError": False}})
        else:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": f"Unknown tool: {name}"}})
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
