#!/usr/bin/env python3
"""
fake_mcp.py — un MCP server FALSO por stdio (JSON-RPC 2.0 newline-delimited), stdlib pura.
Determinístico, sin red ni cerebro: el fixture del done-bar del dispatcher.

Habla el protocolo que el cliente del assembler (MCPServer) y byo_mcp.probe_mcp esperan:
initialize → serverInfo, tools/list → tools configurados, tools/call → ok salvo los "fail".

Config por argv[1] = ruta a un JSON: {"server_name", "tools":[{name,description,inputSchema}],
"fail":[nombres]}. Un tool en `fail` LISTA (aparece en tools/list) pero su tools/call devuelve
un error JSON-RPC → el cliente lo ve "[MCP error ...]" = caído. Un tool que el borrador
reclama pero NO está en `tools` = phantom (nunca aparece en tools/list).
"""
from __future__ import annotations

import json
import sys


def _load_config() -> dict:
    if len(sys.argv) > 1:
        try:
            with open(sys.argv[1], "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {"server_name": "fake-mcp", "tools": [], "fail": []}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    cfg = _load_config()
    server_name = cfg.get("server_name", "fake-mcp")
    tools = cfg.get("tools", []) or []
    fail = set(cfg.get("fail", []) or [])
    tool_names = {t.get("name") for t in tools}

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        mid = msg.get("id")

        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": server_name, "version": "0.0.1"},
                "capabilities": {"tools": {}}}})
        elif method == "notifications/initialized":
            continue  # notificación: sin respuesta
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name in fail:
                _send({"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32000, "message": f"tool '{name}' caído"}})
            elif name in tool_names:
                _send({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": f"ok:{name}"}], "isError": False}})
            else:
                _send({"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32601, "message": f"tool desconocida: {name}"}})
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": f"método no soportado: {method}"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
