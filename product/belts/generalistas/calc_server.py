#!/usr/bin/env python3
"""
Minimal MCP calc server (stdio, JSON-RPC 2.0) — multi-tool, credential-free.

Exposes SIX tools (add, sub, mul, div, pow, mod) so the assembler's
curated-subset filter (tool_filters) and lazy-schema loading can be proven on a
real surface: a recipe that lists only {add, mul} must cable exactly two of the
six, dropping the rest. No external deps, no credentials — a different "niche"
fixture from echo, used to prove the assembler is parametrizable across niches.
"""

import json
import sys

TOOLS = [
    {"name": "add", "description": "Suma dos números: a + b.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}},
    {"name": "sub", "description": "Resta dos números: a - b.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}},
    {"name": "mul", "description": "Multiplica dos números: a * b.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}},
    {"name": "div", "description": "Divide dos números: a / b.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}},
    {"name": "pow", "description": "Eleva a a la potencia b.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}},
    {"name": "mod", "description": "Módulo: a % b.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}},
]


def _compute(name: str, a: float, b: float) -> float:
    if name == "add":
        return a + b
    if name == "sub":
        return a - b
    if name == "mul":
        return a * b
    if name == "div":
        return a / b
    if name == "pow":
        return a ** b
    if name == "mod":
        return a % b
    raise ValueError(f"unknown tool {name}")


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
            "serverInfo": {"name": "calc-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            val = _compute(name, float(args.get("a", 0)), float(args.get("b", 0)))
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": str(val)}], "isError": False,
            }})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error: {exc}"}], "isError": True,
            }})
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
