#!/usr/bin/env python3
"""
Minimal MCP echo server (stdio, JSON-RPC 2.0).
Exposes one tool: echo — returns the input string unchanged.
Used by config-dummy.json to verify the assembler works with any belt.
No external dependencies.
"""

import json
import sys

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
        _send({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        })

    elif method == "tools/call":
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
