#!/usr/bin/env python3
"""
write_file_server.py — mini MCP stdio server (JSON-RPC 2.0) que ESCRIBE
ARCHIVOS DE VERDAD. NUEVO, hecho para la demo del gate.

Expone UNA tool: write_file(filename, content) -> escribe el archivo en un
directorio raíz (PUPPET_WRITE_ROOT del env, default /tmp). Escribir un archivo
en disco ES una acción real con efecto observable — no es un mock. El test del
gate es justamente: ¿se escribió o no se escribió el archivo en el FS?

Contrato de seguridad mínimo: el filename se normaliza a basename (sin rutas
arriba), todo cae dentro de la raíz. Sin dependencias externas.

Carril de arranque: el assembler/GatedRegistry lanza este script como subprocess
y habla JSON-RPC por stdin/stdout. PUPPET_WRITE_ROOT lo fija la demo.
"""

import json
import os
import sys
from pathlib import Path


def _write_root() -> Path:
    root = Path(os.environ.get("PUPPET_WRITE_ROOT", "/tmp")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


TOOLS = [
    {
        "name": "write_file",
        "description": (
            "Guarda contenido de texto en un archivo dentro de la carpeta de "
            "trabajo del usuario. Escribe el archivo de verdad en el disco. "
            "Úsala cuando el usuario pida guardar, escribir o crear un archivo."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Nombre del archivo a crear, ej. nota.txt",
                },
                "content": {
                    "type": "string",
                    "description": "Texto que se va a escribir dentro del archivo",
                },
            },
            "required": ["filename", "content"],
        },
    }
]


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _do_write(filename: str, content: str) -> dict:
    # normalizamos a basename: nada de ../ ni rutas absolutas se escapan de la raíz
    safe_name = Path(filename).name or "archivo.txt"
    target = _write_root() / safe_name
    target.write_text(content, encoding="utf-8")
    nbytes = len(content.encode("utf-8"))
    return {
        "ok": True,
        "path": str(target),
        "bytes": nbytes,
        "message": f"Archivo escrito: {target} ({nbytes} bytes).",
    }


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
                "serverInfo": {"name": "write-file-server", "version": "0.1.0"},
            },
        })

    elif method == "notifications/initialized":
        pass

    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name == "write_file":
            try:
                result = _do_write(
                    str(arguments.get("filename", "")),
                    str(arguments.get("content", "")),
                )
                _send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result["message"]}],
                        "isError": False,
                    },
                })
            except Exception as exc:  # noqa: BLE001
                _send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"No se pudo escribir: {exc}"}],
                        "isError": True,
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
