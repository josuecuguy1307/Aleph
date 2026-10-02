#!/usr/bin/env python3
"""mcp_lento.py — un server MCP stdio que TARDA en el saludo, a propósito.

Existe para medir si el arranque del cinturón se solapa o hace fila **sin depender de la
red ni del caché de uv/npx**. Un server real tarda distinto en cada corrida (medido: la
misma pieza, 7.738 ms en frío y ~300 ms en caliente), así que con servers reales el
veredicto lo decide el caché y no el código. Acá el retardo lo pone el fixture.

    ALEPH_MCP_LENTO_S=<segundos>   cuánto duerme ANTES de contestar `initialize`
"""
import json
import os
import sys
import time

_DORMIR = float(os.environ.get("ALEPH_MCP_LENTO_S", "1.5"))


def _responder(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            msg = json.loads(linea)
        except ValueError:
            continue
        metodo = msg.get("method")
        rid = msg.get("id")
        if metodo == "initialize":
            time.sleep(_DORMIR)                 # ← EL RETARDO, que es todo el fixture
            # LA VERSIÓN ES LA QUE EL CLIENTE PIDIÓ, no una fija: el SDK rechaza una
            # revisión que no conoce y el fixture dejaría de medir lo que dice medir
            # (murió así en su primera corrida: «versión MCP no soportada: 2025-06-18»).
            _pedida = ((msg.get("params") or {}).get("protocolVersion")
                       or "2025-06-18")
            _responder({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": _pedida,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcp-lento", "version": "1.0.0"}}})
        elif metodo == "notifications/initialized":
            continue
        elif metodo == "tools/list":
            _responder({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": "nada", "description": "no hace nada",
                 "inputSchema": {"type": "object", "properties": {}}}]}})
        elif rid is not None:
            _responder({"jsonrpc": "2.0", "id": rid, "result": {}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
