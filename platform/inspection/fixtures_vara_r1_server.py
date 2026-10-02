#!/usr/bin/env python3
"""
Minimal MCP echo server (stdio, JSON-RPC 2.0).
Exposes one tool: echo — returns the input string unchanged.
Used by config-dummy.json to verify the assembler works with any belt.
No external dependencies.
"""

import json
import os
import sys
import time

# VARA R1: mismo servidor que el fixture, con un modo que NO CONTESTA para que el reloj
# del transporte venza de verdad. El stderr de arranque existe para que el evento de
# muerte tenga algo real que traer.
_MODO = os.environ.get("ALEPH_VARA_MODO", "normal")
sys.stderr.write("server_vara arrancando pid=%d modo=%s\n" % (os.getpid(), _MODO))
sys.stderr.flush()

def _quizas_colgar():
    if _MODO == "colgar":
        time.sleep(3600)
    if _MODO == "incompatible":
        # El traceback EXACTO que `diagnostico_conectores` mapea a `servidor_incompatible`
        # (ModuleNotFoundError dentro de un traceback). Se escribe a stderr y se muere: es
        # lo que hace un paquete que publicó una versión que no arranca.
        sys.stderr.write(
            'Traceback (most recent call last):\n'
            '  File "server.py", line 1, in <module>\n'
            "ModuleNotFoundError: No module named 'dependencia_que_ya_no_existe'\n")
        sys.stderr.flush()
        os._exit(1)

TOOLS = [
    {
        "name": "echo",
        "description": "Returns the input text unchanged. Useful for testing the tool-use loop.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo back"}
            },
            "required": ["text"],
        },
    }
]


def _send(obj: dict):
    line = json.dumps(obj)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        _send({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo-server", "version": "0.1.0"},
            },
        })

    elif method == "notifications/initialized":
        pass  # no response needed

    elif method == "tools/list":
        _quizas_colgar()
        _send({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        })

    elif method == "tools/call":
        _quizas_colgar()
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name == "echo":
            text = arguments.get("text", "")
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            })
        else:
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            })

    else:
        if req_id is not None:
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


def main():
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
