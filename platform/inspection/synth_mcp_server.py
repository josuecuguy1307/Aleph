#!/usr/bin/env python3
"""
synth_mcp_server.py — servidor MCP stdio GENÉRICO para una tool SINTETIZADA.

FASE 4: la tool que el motor sintetizó (synthesize_tool) se vuelve un MCP server
real y equipable. El assembler lo lanza como subprocess y habla JSON-RPC 2.0 por
stdin/stdout (mismo dialecto que write_file_server.py: líneas JSON, logs a stderr).

El spec de la tool entra por env SYNTH_TOOL_SPEC (ruta a un .spec.json). Expone esa
ÚNICA tool (su mcp_tool def) y al llamarla REPLAYA la request observada con los
args del modelo, vía SynthesizedTool (observe/replay).

GATE (guard de la directiva — writes no se ejecutan sin gate explícito):
  - sin SYNTH_EXECUTE         → DRY-RUN: devuelve la request armada, NO la manda.
  - SYNTH_EXECUTE=1           → ejecuta reads; los writes EXIGEN además SYNTH_ALLOW_WRITE=1.
En prod, SYNTH_EXECUTE/SYNTH_ALLOW_WRITE = la aprobación human-in-the-loop (Telegram):
el belt arranca el server gateado y el OK del humano lo habilita.
"""
import json
import os
import sys
from pathlib import Path

# bootstrap: poné platform/ en el path para importar el paquete inspection
_PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))

from inspection.observe.replay import SynthesizedTool


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _load_spec() -> dict:
    p = os.environ.get("SYNTH_TOOL_SPEC", "")
    if not p or not Path(p).exists():
        raise RuntimeError(f"SYNTH_TOOL_SPEC no apunta a un spec válido: {p!r}")
    return json.loads(Path(p).read_text(encoding="utf-8"))


_SPEC = _load_spec()
_TOOL = SynthesizedTool(_SPEC)
_EXECUTE = _truthy(os.environ.get("SYNTH_EXECUTE"))
_ALLOW_WRITE = _truthy(os.environ.get("SYNTH_ALLOW_WRITE"))


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(req: dict) -> None:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": f"synth-{_TOOL.name}", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": [_SPEC["mcp_tool"]]}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        if name != _TOOL.name:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": f"Unknown tool: {name}"}})
            return
        try:
            out = _TOOL.call(args, execute=_EXECUTE, allow_write=_ALLOW_WRITE)
            is_err = bool(out.get("refused")) or (
                out.get("response", {}).get("status") not in (None, 200, 201, 204)
                if not out.get("dry_run") else False)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                "isError": is_err,
            }})
        except Exception as exc:  # noqa: BLE001
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error ejecutando la tool: {exc}"}],
                "isError": True,
            }})
    elif req_id is not None:
        _send({"jsonrpc": "2.0", "id": req_id,
               "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main() -> None:
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
