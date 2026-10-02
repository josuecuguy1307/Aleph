#!/usr/bin/env python3
"""
connections.py — BLOCK D · FASE 2 · conexiones por-usuario a servers MCP de Smithery.

Smithery brokea el OAuth de servicio: vos creás una "connection" con la GATEWAY key del
producto + metadata.userId del usuario FINAL; si el server pide que el usuario autorice
(GitHub, Notion, Gmail…), Smithery devuelve un `setupUrl` que el usuario visita; Smithery
hostea el callback, guarda y refresca el token. El producto NUNCA ve la credencial del
servicio — solo el estado de la conexión.

DOS CAPAS de auth (no confundir):
  - GATEWAY  = la Smithery API key del PRODUCTO (una sola), cifrada BYOK bajo el owner de
               plataforma. Se usa como `Authorization: Bearer` contra smithery.run.
  - SERVICIO = OAuth POR-USUARIO que Smithery brokea. El usuario final se identifica con
               `metadata.userId` = su user_id de Aleph. Así cada usuario tiene su conexión.

API REAL (verificada 2026-06-19 contra smithery.run; NO asumida):
  - PUT    https://smithery.run/{namespace}/{connectionId}   body {mcpUrl,name,metadata}
           → 201 {connectionId, status:{state, setupUrl}}   state ∈ auth_required|input_required|connected
  - GET    https://smithery.run/{namespace}/{connectionId}   → estado actual
  - DELETE https://smithery.run/{namespace}/{connectionId}   → borra la conexión
  - GET    https://registry.smithery.ai/servers/{qualified}  → {deploymentUrl=mcpUrl, ...}
  - Cloudflare BANEA el UA default de python → User-Agent OBLIGATORIO.

Este módulo NO expone tools al agente (eso es FASE 3) ni toca el send-gate (FASE 4). Solo
establece/consulta la conexión por-usuario y entrega el setupUrl para que la Sala lo muestre.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

_CONN_BASE = "https://smithery.run"
_REGISTRY_BASE = "https://registry.smithery.ai"
_UA = "Mozilla/5.0 (compatible; PuppetAI-Aleph/0.1; +https://puppet.ai)"
_TIMEOUT = 25

# El namespace y el owner de la GATEWAY key son config de plataforma (no hardcode de secreto):
#   - NAMESPACE: el namespace de Smithery del producto (la cuenta del gateway key).
#   - OWNER: el user_id de Aleph bajo el que está guardada (cifrada) la Smithery API key.
_NAMESPACE = os.environ.get("SMITHERY_NAMESPACE", "demo-userarcos1307")
_OWNER_USER = os.environ.get("SMITHERY_OWNER_USER", "0e890e35-c23d-468e-8c46-c50c769eeac8")
_GATEWAY_BYOK_REF = "keys:smithery"


class SmitheryError(RuntimeError):
    pass


def _slug(s: str) -> str:
    """qualifiedName (@owner/name) → slug seguro para un connectionId."""
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def connection_id(user_id: str, qualified: str) -> str:
    """ID determinístico y por-usuario: no hace falta persistirlo, se deriva de (user, server).
    El estado vive en Smithery (autoritativo); Aleph lo consulta cuando lo necesita."""
    uid = re.sub(r"[^a-z0-9]+", "", user_id.lower())[:12]
    return f"aleph-{_slug(qualified)}-{uid}"


def _gateway_key(resolver: Callable[[str], str]) -> str:
    key = resolver(_GATEWAY_BYOK_REF) or ""
    if not key:
        raise SmitheryError(
            "Smithery gateway key ausente (BYOK provider 'smithery' bajo el owner de "
            "plataforma). Fail-closed: no se hardcodea ni se sigue sin credencial.")
    return key


def make_resolver(get_conn) -> Callable[[str], str]:
    """Resolver BYOK del OWNER de plataforma (de ahí sale la GATEWAY key, no del end-user)."""
    from app.phase1 import credential_broker as broker  # import perezoso
    return broker.make_user_resolver(_OWNER_USER, get_conn=get_conn)


def _req(method: str, url: str, key: str, body: Optional[dict] = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": _UA,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except urllib.error.URLError as e:
        return 0, {"error": "network", "detail": str(e.reason)}


def resolve_mcp_url(qualified: str, key: str) -> str:
    """qualifiedName → mcpUrl (deploymentUrl) vía el registry de Smithery."""
    st, data = _req("GET", f"{_REGISTRY_BASE}/servers/{urllib.parse.quote(qualified)}", key)
    if st != 200 or not isinstance(data, dict):
        raise SmitheryError(f"registry {qualified} → HTTP {st}: {str(data)[:160]}")
    url = data.get("deploymentUrl")
    if not url:
        conns = data.get("connections") or []
        url = (conns[0].get("deploymentUrl") if conns and isinstance(conns[0], dict) else None)
    if not url:
        raise SmitheryError(f"server {qualified} sin deploymentUrl (¿no es remoto?)")
    return url


def _shape(conn_id: str, data: Any) -> dict:
    status = (data.get("status") if isinstance(data, dict) else {}) or {}
    return {
        "connection_id": conn_id,
        "namespace": _NAMESPACE,
        "state": status.get("state"),                       # auth_required|input_required|connected
        "setup_url": status.get("setupUrl") or status.get("authorizationUrl"),
        "missing": status.get("missing"),                   # campos de config faltantes (input_required)
        "metadata": data.get("metadata") if isinstance(data, dict) else None,
    }


def ensure_connection(user_id: str, qualified: str, resolver: Callable[[str], str],
                      display_name: Optional[str] = None,
                      mcp_url: Optional[str] = None) -> dict:
    """Crea/actualiza la conexión por-usuario y devuelve {state, setup_url, connection_id}.
    Si state == 'connected' → lista para usar. Si 'auth_required' → mostrar setup_url en la Sala."""
    key = _gateway_key(resolver)
    conn_id = connection_id(user_id, qualified)
    mcp = mcp_url or resolve_mcp_url(qualified, key)
    body = {"mcpUrl": mcp, "name": display_name or qualified,
            "metadata": {"userId": user_id, "server": qualified}}
    st, data = _req("PUT", f"{_CONN_BASE}/{_NAMESPACE}/{conn_id}", key, body)
    if st not in (200, 201):
        raise SmitheryError(f"PUT connection {conn_id} → HTTP {st}: {str(data)[:200]}")
    out = _shape(conn_id, data)
    out["http_status"] = st
    return out


def get_status(user_id: str, qualified: str, resolver: Callable[[str], str]) -> dict:
    """Estado actual de la conexión por-usuario (autoritativo en Smithery). 404 → no existe."""
    key = _gateway_key(resolver)
    conn_id = connection_id(user_id, qualified)
    st, data = _req("GET", f"{_CONN_BASE}/{_NAMESPACE}/{conn_id}", key)
    if st == 404:
        return {"connection_id": conn_id, "namespace": _NAMESPACE, "state": "not_connected",
                "setup_url": None}
    if st != 200:
        raise SmitheryError(f"GET connection {conn_id} → HTTP {st}: {str(data)[:200]}")
    return _shape(conn_id, data)


def delete_connection(user_id: str, qualified: str, resolver: Callable[[str], str]) -> bool:
    key = _gateway_key(resolver)
    conn_id = connection_id(user_id, qualified)
    st, _ = _req("DELETE", f"{_CONN_BASE}/{_NAMESPACE}/{conn_id}", key)
    return st in (200, 204)


__all__ = ["ensure_connection", "get_status", "delete_connection", "connection_id",
           "resolve_mcp_url", "make_resolver", "SmitheryError"]
