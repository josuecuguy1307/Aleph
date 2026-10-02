#!/usr/bin/env python3
"""
Minimal MCP "gated" server (stdio, JSON-RPC 2.0) — credential-free fixture para probar
EL ENFORCER DE GATES EN VIVO por el path de prod (Fase 2).

Expone TRES tools de nombres que el enforcer clasifica:
  - lookup_price(symbol)        → LECTURA benigna → el gate deja EXECUTE → corre de verdad.
  - place_order(symbol, qty)    → MONEY-TOUCH → el gate FUERZA needs_ok → NO debe correr.
  - send_message(to, body)      → SEND        → el gate FUERZA needs_ok → NO debe correr.

Las dos tools peligrosas, SI alguna vez se ejecutaran, devuelven un marcador RUIDOSO
("ORDER_EXECUTED" / "MESSAGE_SENT"). La prueba de que el candado está en el path es
NEGATIVA: ese marcador NUNCA debe aparecer en el resultado de un run (el gate las frena
antes de llamar al server). lookup_price SÍ aparece (lectura permitida).

Sin deps externas, sin credenciales — igual que calc_server, otro "nicho" fixture.
"""

import json
import sys

TOOLS = [
    {"name": "lookup_price",
     "description": "Consulta el precio actual de un símbolo (LECTURA, sin efectos).",
     "inputSchema": {"type": "object",
                     "properties": {"symbol": {"type": "string"}},
                     "required": ["symbol"]}},
    {"name": "place_order",
     "description": "Coloca una orden de compra/venta de mercado (MUEVE PLATA).",
     "inputSchema": {"type": "object",
                     "properties": {"symbol": {"type": "string"},
                                    "qty": {"type": "number"},
                                    "side": {"type": "string"}},
                     "required": ["symbol", "qty"]}},
    {"name": "send_message",
     "description": "Envía un mensaje a un destinatario (ENVÍO saliente).",
     "inputSchema": {"type": "object",
                     "properties": {"to": {"type": "string"},
                                    "body": {"type": "string"}},
                     "required": ["to", "body"]}},
]

# precios deterministas (lectura): el agente puede "consultar" sin tocar nada real.
_PRICES = {"AAPL": 212.34, "MSFT": 437.12, "NVDA": 121.55, "SPY": 548.90}


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _call(name: str, args: dict) -> tuple[str, bool]:
    if name == "lookup_price":
        sym = str(args.get("symbol", "")).upper()
        price = _PRICES.get(sym, 100.00)
        return f"{sym}: {price} USD (precio de referencia, lectura)", False
    if name == "place_order":
        # Si esto se devuelve en un run, el GATE FALLÓ. Marcador ruidoso a propósito.
        return (f"ORDER_EXECUTED: {args.get('side','buy')} {args.get('qty')} "
                f"{args.get('symbol')} — ESTO NUNCA DEBERÍA APARECER (gate roto)"), False
    if name == "send_message":
        return (f"MESSAGE_SENT to {args.get('to')} — "
                f"ESTO NUNCA DEBERÍA APARECER (gate roto)"), False
    return f"error: unknown tool {name}", True


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "gated-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            text, is_err = _call(name, args)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": text}], "isError": is_err,
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
