#!/usr/bin/env python3
"""MCP stdio mínimo y determinista para la vara de ENTRAR."""
from __future__ import annotations

import json
import sys


TOOL = {
    "name": "entrar_ping",
    "description": "devuelve una señal local de vida",
    "inputSchema": {"type": "object", "properties": {}},
}


for raw in sys.stdin:
    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        continue
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "entrar-stdio", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "pong"}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
