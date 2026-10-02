#!/usr/bin/env python3
"""
Fixture MCP server: imita la superficie de tools del server `sheets` (mcp-google-sheets)
que usa T05, SIN credenciales Google reales. Permite el E2E del gate contra el
assembler real: el agente intenta `batch_update_cells` (acción confirma-siempre
según la matriz) y el GatedRegistry la intercepta.

Tools expuestas (subset real de mcp-google-sheets):
  - get_sheet_data       (lectura -> auto-ejecuta)
  - batch_update_cells   (escritura en vivo -> confirma-siempre)

Devuelve datos canned + registra una "escritura" en un archivo de marca para que
el E2E pueda verificar si la escritura aterrizó o no.
"""

import json
import os
import sys

MARK_FILE = os.environ.get("FAKE_SHEETS_MARK", "/tmp/puppet_fake_sheets_write.json")

TOOLS = [
    {
        "name": "get_sheet_data",
        "description": "Lee datos de un rango de una hoja de Google Sheets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "sheet": {"type": "string"},
                "range": {"type": "string"},
            },
            "required": ["spreadsheet_id"],
        },
    },
    {
        "name": "batch_update_cells",
        "description": "ESCRIBE en vivo en el Google Sheet del usuario (rango de celdas).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "sheet": {"type": "string"},
                "range": {"type": "string"},
                "data": {"type": "array"},
            },
            "required": ["spreadsheet_id", "data"],
        },
    },
]


def _send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(req):
    method = req.get("method", "")
    rid = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-sheets", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name == "get_sheet_data":
            # datos canned: budget vs actual
            data = [["Línea", "Budget", "Actual"],
                    ["Ventas", "100000", "70000"],
                    ["COGS", "40000", "57000"],
                    ["Marketing", "20000", "15000"]]
            _send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(data)}], "isError": False}})
        elif name == "batch_update_cells":
            # registra la escritura REAL (esto es lo que el gate debe poder frenar)
            with open(MARK_FILE, "w") as f:
                json.dump({"wrote": True, "args": args}, f)
            _send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": "OK: 12 celdas escritas en Varianzas."}],
                "isError": False}})
        else:
            _send({"jsonrpc": "2.0", "id": rid,
                   "error": {"code": -32601, "message": f"Unknown tool: {name}"}})
    else:
        if rid is not None:
            _send({"jsonrpc": "2.0", "id": rid,
                   "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
