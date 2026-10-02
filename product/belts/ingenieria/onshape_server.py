#!/usr/bin/env python3
"""Onshape MCP (OAuth bearer), con superficie determinada por scope CONCEDIDO.

El access token y el companion cifrado salen del broker sólo al environment de
este subprocess. ``tools/list`` no publica una operación si su scope no aparece
en ``ONSHAPE_OAUTH_META.granted_scopes``. No se infiere nada de los scopes pedidos.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = (os.environ.get("ONSHAPE_API_BASE") or
         "https://cad.onshape.com/api/v16").rstrip("/")
_TIMEOUT = 25


def _token() -> str:
    """El bearer OAuth, y NADA MÁS.

    Acá había un fallback a ``ONSHAPE_API_KEY`` y lo borró la guarda de §9.2
    (`verify_env_declarado.py`), con razón y por dos motivos:

      1. **La receta no la declara.** Leer una variable que el belt no declara rompe la
         huella sobre el env: dos conexiones que difieran SÓLO en ella compartirían
         proceso, y compartir de más ES la fuga. Peor todavía tratándose de una credencial.
      2. **Era código muerto que además contradecía la ficha.** Es un vestigio del modelo
         `personal_token` que esta misma tanda corrigió a OAuth bearer. Y no podía funcionar
         ni por accidente: la superficie sale de `ONSHAPE_OAUTH_META.granted_scopes`, así
         que una API key sin companion daba `tools/list` vacío igual.

    Declararla habría sido peor que borrarla: dejaría escrita en el catálogo una credencial
    que este conector no usa.
    """
    return (os.environ.get("ONSHAPE_ACCESS_TOKEN") or "").strip()


def _oauth_meta() -> dict:
    try:
        value = json.loads(os.environ.get("ONSHAPE_OAUTH_META") or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _granted() -> set[str]:
    meta = _oauth_meta()
    if meta.get("state") not in (None, "", "connected"):
        return set()
    value = meta.get("granted_scopes")
    if not isinstance(value, list):
        return set()
    return {str(scope) for scope in value if str(scope).strip()}


def _request(method: str, path: str, payload: Any = None) -> tuple[int, Any]:
    token = _token()
    if not token:
        return 0, {"ok": False, "error": "missing_credential",
                   "detail": "Conecta Onshape antes de usar esta tool."}
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json;charset=UTF-8; qs=0.09",
        "User-Agent": "Aleph-Onshape-OAuth/1",
    }
    if body is not None:
        headers["Content-Type"] = "application/json;charset=UTF-8; qs=0.09"
    req = urllib.request.Request(_BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
            if not raw:
                return response.status, {}
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw[:1000]
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw[:500]
        if exc.code == 401:
            return 401, {
                "ok": False,
                "error": "oauth_access_rejected",
                "detail": "Onshape rechazó el OAuth; Aleph intentará refresh o pedirá reconectar.",
            }
        return exc.code, {"ok": False, "error": "onshape_http",
                          "status": exc.code, "detail": detail}
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {"ok": False, "error": "network",
                   "detail": "No pude contactar a Onshape."}


def _ok(status: int, data: Any) -> dict:
    if 200 <= status < 300:
        return {"ok": True, "status": status, "data": data}
    if isinstance(data, dict):
        return data
    return {"ok": False, "status": status, "detail": data}


def _whoami(_args: dict) -> dict:
    status, data = _request("GET", "/users/sessioninfo")
    if not (200 <= status < 300) or not isinstance(data, dict):
        return _ok(status, data)
    return {
        "ok": True, "status": status,
        "id": data.get("id") or data.get("userId"),
        "name": data.get("name"),
        "email": data.get("email"),
    }


def _list_documents(args: dict) -> dict:
    try:
        limit = max(1, min(int(args.get("limit", 20)), 20))
    except (TypeError, ValueError):
        limit = 20
    query = str(args.get("query") or "").strip()
    params = urllib.parse.urlencode({
        "q": query, "filter": 0, "sortColumn": "modifiedAt",
        "sortOrder": "desc", "offset": 0, "limit": limit,
    })
    status, data = _request("GET", f"/documents?{params}")
    if not (200 <= status < 300) or not isinstance(data, dict):
        return _ok(status, data)
    items = data.get("items") or data.get("documents") or []
    documents = [
        {
            "id": item.get("id") or item.get("documentId"),
            "name": item.get("name"),
            "modifiedAt": item.get("modifiedAt"),
            "permission": item.get("permission"),
            "href": item.get("href"),
        }
        for item in items if isinstance(item, dict)
    ]
    return {"ok": True, "status": status, "count": len(documents),
            "documents": documents}


def _create_document(args: dict) -> dict:
    name = str(args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "bad_args", "detail": "name es obligatorio."}
    return _ok(*_request("POST", "/documents", {
        "name": name, "isPublic": bool(args.get("is_public", False)),
    }))


def _delete_document(args: dict) -> dict:
    did = str(args.get("document_id") or "").strip()
    if not did:
        return {"ok": False, "error": "bad_args",
                "detail": "document_id es obligatorio."}
    forever = "true" if bool(args.get("forever", False)) else "false"
    return _ok(*_request(
        "DELETE", f"/documents/{urllib.parse.quote(did, safe='')}?forever={forever}"
    ))


def _share_document(args: dict) -> dict:
    did = str(args.get("document_id") or "").strip()
    email = str(args.get("email") or "").strip()
    if not did or not email:
        return {"ok": False, "error": "bad_args",
                "detail": "document_id y email son obligatorios."}
    payload = {
        "documentId": did,
        "entries": [{"email": email}],
        "permission": int(args.get("permission", 0) or 0),
        "update": False,
        "message": str(args.get("message") or "")[:500],
    }
    return _ok(*_request(
        "POST", f"/documents/{urllib.parse.quote(did, safe='')}/share", payload
    ))


def _consume_purchase(args: dict) -> dict:
    pid = str(args.get("purchase_id") or "").strip()
    if not pid:
        return {"ok": False, "error": "bad_args",
                "detail": "purchase_id es obligatorio."}
    return _ok(*_request(
        "POST", f"/accounts/purchases/{urllib.parse.quote(pid, safe='')}/consume", {}
    ))


_ALL_TOOLS = [
    {
        "scope": "OAuth2ReadPII",
        "name": "onshape_whoami",
        "description": "Lee la identidad de la cuenta Onshape conectada. No modifica nada.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "call": _whoami,
    },
    {
        "scope": "OAuth2Read",
        "name": "onshape_list_documents",
        "description": "Lista documentos reales de la cuenta Onshape. Sólo lectura.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "filtro opcional por nombre"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 20},
            },
            "required": [],
        },
        "call": _list_documents,
    },
    {
        "scope": "OAuth2Write",
        "name": "onshape_create_document",
        "description": "Crea un documento en Onshape. Efecto externo: requiere aprobación B4.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "is_public": {"type": "boolean", "default": False},
            },
            "required": ["name"],
        },
        "call": _create_document,
    },
    {
        "scope": "OAuth2Delete",
        "name": "onshape_delete_document",
        "description": "Borra un documento de Onshape. Requiere aprobación B4.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "forever": {"type": "boolean", "default": False},
            },
            "required": ["document_id"],
        },
        "call": _delete_document,
    },
    {
        "scope": "OAuth2Share",
        "name": "onshape_share_document",
        "description": "Comparte un documento con un email. Requiere aprobación B4.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "email": {"type": "string"},
                "permission": {"type": "integer", "default": 0},
                "message": {"type": "string"},
            },
            "required": ["document_id", "email"],
        },
        "call": _share_document,
    },
    {
        "scope": "OAuth2Purchase",
        "name": "onshape_consume_purchase",
        "description": "Marca una compra Onshape como consumida. Piso money: siempre aprobación B4.",
        "inputSchema": {
            "type": "object",
            "properties": {"purchase_id": {"type": "string"}},
            "required": ["purchase_id"],
        },
        "call": _consume_purchase,
    },
]


def _surface() -> list[dict]:
    granted = _granted()
    return [
        {k: tool[k] for k in ("name", "description", "inputSchema")}
        for tool in _ALL_TOOLS if tool["scope"] in granted
    ]


def _send(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(req: dict) -> None:
    method, req_id = req.get("method", ""), req.get("id")
    params = req.get("params") or {}
    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "aleph-onshape", "version": "1.0.0"},
        }})
    elif method == "notifications/initialized":
        return
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id,
               "result": {"tools": _surface()}})
    elif method == "tools/call":
        name = str(params.get("name") or "")
        tool = next((t for t in _ALL_TOOLS
                     if t["name"] == name and t["scope"] in _granted()), None)
        if tool is None:
            result = {"ok": False, "error": "tool_not_granted",
                      "detail": "Esta tool no existe para los scopes concedidos."}
        else:
            try:
                result = tool["call"](params.get("arguments") or {})
            except Exception:
                result = {"ok": False, "error": "tool_failed",
                          "detail": "La operación de Onshape falló."}
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text",
                         "text": json.dumps(result, ensure_ascii=False)}],
            "isError": not bool(result.get("ok")),
        }})
    elif req_id is not None:
        _send({"jsonrpc": "2.0", "id": req_id,
               "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main() -> None:
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(request, dict):
            _handle(request)


if __name__ == "__main__":
    main()
