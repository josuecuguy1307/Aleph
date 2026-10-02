#!/usr/bin/env python3
"""
pysandbox_server.py — Python-sandbox MCP server (stdio, JSON-RPC 2.0), keyless.

Belt RESEARCH, leg "cómputo". Expone UNA tool de cálculo:

  • run_python(code, timeout_s) → ejecuta `code` en una VM Linux efímera,
    sin adaptadores de red, discos ni carpetas compartidas; un único canal serial
    entrega código y devuelve stdout/stderr. Si el guest no está íntegro, falla cerrado.

POR QUÉ ESTA TOOL ES EL ANTÍDOTO A LA FABRICACIÓN (bar de la misión):
    "todo número desde código ejecutado". El modelo NO computa de cabeza: escribe código,
    esta tool lo CORRE de verdad, y el número que vuelve es el que imprimió el proceso.
    Si el código falla, vuelve el traceback real (no un número inventado).

No tiene autoridad de host; el gate mantiene la aprobación por invocación.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guest_execution import GuestUnavailable, execute_python

_DEFAULT_TIMEOUT = 15
_MAX_TIMEOUT = 30
_OUT_LIMIT = 12000  # recorte de stdout/stderr para no inundar el contexto del modelo


TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Ejecuta código Python REAL en un guest aislado y devuelve su salida "
            "exacta (stdout, stderr, returncode). Usa esta tool para "
            "cálculo numérico — nunca calcules de memoria. Imprime los resultados con "
            "print(). Sólo stdlib de Python (sin pip). Requiere aprobación; "
            "corre en un guest Linux sobre macOS arm64 y falla cerrado si no está disponible."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Código Python a ejecutar."},
                "timeout_s": {
                    "type": "integer",
                    "description": f"Límite de segundos (1-{_MAX_TIMEOUT}).",
                    "default": _DEFAULT_TIMEOUT,
                },
            },
            "required": ["code"],
        },
    },
]


def _run_python(code: str, timeout_s: int = _DEFAULT_TIMEOUT) -> dict:
    try:
        return execute_python(code, timeout_s)
    except GuestUnavailable as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc),
                "timed_out": False, "blocked": True}


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
            "serverInfo": {"name": "pysandbox-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "run_python":
                val = _run_python(args.get("code", ""), args.get("timeout_s", _DEFAULT_TIMEOUT))
            else:
                raise ValueError(f"unknown tool {name}")
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": bool(val.get("blocked") or val.get("timed_out") or not val.get("ok", False)),
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
