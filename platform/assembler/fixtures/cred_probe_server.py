#!/usr/bin/env python3
"""
cred_probe_server.py — Fixture MCP (stdio, JSON-RPC 2.0) que PRUEBA la inyección de la
credencial BYOK por usuario al child_env, SIN exponer nunca el valor.

Razón de ser (F4-B4, credential-broker round-trip):
  El belt real (exa/alphavantage/slack/...) lee su credencial de una env var
  (${EXA_API_KEY}, ${ALPHA_VANTAGE_API_KEY}, ...). Para PROBAR que el broker la cableó
  al subprocess sin tocar un proveedor externo real, este server lee la env var
  PROBE_CRED (cableada vía la receta keys.<provider>.byok_ref → child_env) y expone:

    - cred_status()  → SOLO metadatos: si la credencial llegó (present:true/false),
                       su longitud, y un fingerprint sha256[:12] (NUNCA el valor).
                       Esto demuestra "la credencial llegó al server" sin filtrarla.

La prueba de inyección es POSITIVA por metadatos (present:true + fingerprint estable),
y la prueba de no-fuga es que el VALOR jamás se imprime ni se devuelve. El test del
round-trip compara el fingerprint contra sha256(secreto_de_prueba)[:12] computado afuera.

Sin deps externas, sin tocar red. Igual patrón que gated_server / calc_server.
"""

import hashlib
import json
import os
import sys

# Env var bajo la que el broker inyecta la credencial del usuario. El belt fixture la
# declara como "env": {"PROBE_CRED": "${PROBE_CRED}"} y el provider de la receta mapea
# a ella (provider 'probe' → PROBE_CRED vía el canónico PROBE_API_KEY no aplica, así que
# leemos ambos: el alias explícito y el canónico).
_CRED = os.environ.get("PROBE_CRED") or os.environ.get("PROBE_API_KEY") or ""

TOOLS = [
    {"name": "cred_status",
     "description": "Informa si la credencial inyectada llegó al server (metadatos, NUNCA el valor).",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
]


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _cred_status() -> str:
    present = bool(_CRED)
    fp = hashlib.sha256(_CRED.encode("utf-8")).hexdigest()[:12] if present else None
    # JAMÁS el valor: solo present + length + fingerprint.
    return json.dumps({
        "present": present,
        "length": len(_CRED),
        "fingerprint_sha256_12": fp,
    })


def _call(name: str, args: dict) -> tuple[str, bool]:
    if name == "cred_status":
        return _cred_status(), False
    return f"[unknown tool: {name}]", True


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        rid = req.get("id")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cred-probe", "version": "1.0"},
            }})
        elif method == "notifications/initialized":
            pass  # notificación, sin respuesta
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = req.get("params", {})
            text, is_err = _call(params.get("name", ""), params.get("arguments", {}) or {})
            _send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_err,
            }})
        elif rid is not None:
            _send({"jsonrpc": "2.0", "id": rid,
                   "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
