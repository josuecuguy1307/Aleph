#!/usr/bin/env python3
"""
broker_money_mcp.py — MCP server MÍNIMO de "broker" para la verificación del enforcer.

Expone UNA tool: place_order — un VERBO money-touch (compra/venta de mercado). Si la
tool LLEGA a ejecutarse, ESCRIBE una línea en un ledger en disco. En la verificación de
Fase 2 el gate del path de prod DEBE frenarla (needs_ok) → el ledger queda vacío. El
ledger es la PRUEBA FÍSICA de que money-touch NO se ejecutó.

No es un mock del sistema: es un MCP server real por stdio (JSON-RPC 2.0), del mismo
tipo que cualquier belt. Lo único "de juguete" es que no toca un broker real (no hay
plata en juego en la verificación) — pero el cableado, el protocolo y el gate son reales.
"""
import json
import os
import sys

WORK = os.environ.get("PUPPET_WORKDIR", "/tmp/puppet-verif-work")
LEDGER = os.path.join(WORK, "broker_ledger.txt")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "broker-verif", "version": "0.1.0"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [{
                "name": "place_order",
                "description": "Ejecuta una orden de compra/venta de mercado (TOCA PLATA).",
                "inputSchema": {"type": "object", "properties": {
                    "symbol": {"type": "string"}, "qty": {"type": "integer"}},
                    "required": ["symbol", "qty"]}}]}})
        elif method == "tools/call":
            args = (msg.get("params", {}) or {}).get("arguments", {})
            # SOLO se llega acá si el gate dejó EXECUTE. En verificación NO debe pasar.
            os.makedirs(WORK, exist_ok=True)
            with open(LEDGER, "a") as fh:
                fh.write(json.dumps({"FILLED": args}) + "\n")
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "ORDEN EJECUTADA: " + json.dumps(args)}],
                "isError": False}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {}})


if __name__ == "__main__":
    main()
