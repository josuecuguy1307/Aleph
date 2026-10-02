"""
⚠️ LEGACY — SÓLO FALLBACK. SE RETIRA POST-CERTIFICACIÓN. NO AGREGAR CONSUMIDORES.

Desde la sesión 3 del SDK, el camino real es `inspection/transporte_sdk.ClienteSdkHttp`
(el SDK oficial). Este cliente ya no lo alcanza nadie del producto: el único que lo
construye es `inspection/transporte.py::cliente_http()`, y sólo cuando alguien pide
`ALEPH_TRANSPORTE=viejo`. Existe para eso, y sólo para eso: **el rollback de un click**
mientras la certificación final en la `.app` no pase.

Si necesitás hablar HTTP con un MCP, andá por `inspection.transporte`. Un import directo de
este módulo vuelve a partir el producto en dos transportes y lo caza
`test_frontera_transporte.py`.

Cuando la certificación pase, esto y `assembler.MCPServer` se borran juntos.

────────────────────────────────────────────────────────────────────────────────────────
mcp_http_client.py — cliente MCP por HTTP (Streamable HTTP) en stdlib pura (FASE 1 · C3).

Habla el transporte "Streamable HTTP" del protocolo MCP (rev 2024-11-05 / 2025-03-26)
contra un server MCP PÚBLICO por HTTP: POST de un JSON-RPC al endpoint, y la respuesta
llega como `application/json` (un objeto) o como `text/event-stream` (SSE — un `data:`
por línea). Maneja ambos, propaga el `Mcp-Session-Id` si el server lo emite (los servers
stateless como DeepWiki no lo emiten — también funciona), negocia protocolVersion y manda
la notificación `notifications/initialized` tras el handshake.

Lo usan DOS lados del BYO-MCP, sin duplicar:
  - el PROBE (byo_mcp.probe_mcp): valida un MCP pegado = conecta + lista tools.
  - el PROXY stdio (byo_mcp_server.py): el agente equipa el MCP remoto como un belt normal.

Cero dependencias de terceros (no existe el paquete `mcp` en este entorno): solo urllib +
json. Cero red en import (todo es perezoso, al primer método).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

_DEFAULT_UA = "puppet-byo-mcp/1.0"
_PROTOCOL_VERSION = "2024-11-05"
_ERROR_BODY_CAP = 32 * 1024


class MCPHttpError(Exception):
    """Falla de transporte/protocolo hablando con el MCP remoto (mensaje legible)."""

    def __init__(self, message: str, *, evidencia: Optional[dict] = None):
        super().__init__(message)
        self.evidencia = dict(evidencia or {})


def _evidencia_protocolo(obj: Any, cliente: str) -> dict:
    """Proyecta requested/supported sin interpretar texto libre."""
    out: dict[str, Any] = {"cliente": cliente}
    if not isinstance(obj, dict):
        return out
    error = obj.get("error") if isinstance(obj.get("error"), dict) else {}
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    requested = data.get("requested")
    supported = data.get("supported")
    if isinstance(requested, str) and requested:
        out["cliente"] = requested
    if isinstance(supported, list):
        versions = [v for v in supported if isinstance(v, str) and v]
        if versions:
            out["servidor"] = versions[0]
            out["servidor_soportadas"] = versions
    if error.get("code") == -32022:
        out["incompatible"] = True
        out["negociacion"] = "fallida"
    return out


class MCPHttpClient:
    """Cliente mínimo de un MCP por Streamable HTTP. No es thread-safe (un _id por cliente)."""

    def __init__(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        *,
        timeout: float = 45.0,
        user_agent: str = _DEFAULT_UA,
    ):
        if not url or not isinstance(url, str):
            raise MCPHttpError("URL del MCP vacía o inválida")
        self.url = url.strip()
        self.extra_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self.timeout = float(timeout)
        self.user_agent = user_agent
        self.session_id: Optional[str] = None
        self.protocol_version = _PROTOCOL_VERSION
        self.server_info: dict[str, Any] = {}
        self._id = 0

    # ── transporte ────────────────────────────────────────────────────────────
    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": self.user_agent,
        }
        h.update(self.extra_headers)
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        # algunos servers exigen el header de versión de protocolo en cada request
        if self.protocol_version:
            h["MCP-Protocol-Version"] = self.protocol_version
        return h

    def _post(self, payload: dict, *, is_notification: bool = False) -> Optional[dict]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, method="POST", headers=self._headers())
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            body = ""
            parsed: Any = None
            try:
                body = e.read().decode("utf-8", "replace")[-_ERROR_BODY_CAP:]
                parsed = json.loads(body)
            except Exception:
                pass
            # 202 Accepted a una notificación: no es error (algunos servers responden así)
            if is_notification and e.code in (200, 202, 204):
                return None
            raise MCPHttpError(
                f"HTTP {e.code} del MCP remoto" + (f": {body}" if body else ""),
                evidencia={
                    "http_status": e.code,
                    "respuesta": parsed if isinstance(parsed, dict) else body,
                    "protocolo": _evidencia_protocolo(parsed, self.protocol_version),
                    "red": {"consultada": True, "online": True},
                },
            )
        except urllib.error.URLError as e:
            raise MCPHttpError(f"no se pudo conectar al MCP remoto: {getattr(e, 'reason', e)}")
        except (TimeoutError, OSError) as e:
            raise MCPHttpError(f"timeout/red hablando con el MCP remoto: {e}")

        with resp:
            sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid
            if is_notification:
                try:
                    resp.read()
                except Exception:
                    pass
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            try:
                raw = resp.read().decode("utf-8", "replace")
            except Exception as e:
                raise MCPHttpError(f"no se pudo leer la respuesta del MCP remoto: {e}")

        if "text/event-stream" in ctype:
            obj = _parse_sse_jsonrpc(raw)
            if obj is None:
                raise MCPHttpError("el MCP remoto no devolvió un mensaje JSON-RPC en el SSE")
            return obj
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise MCPHttpError(f"respuesta no-JSON del MCP remoto: {e}")

    def _rpc(self, method: str, params: dict) -> dict:
        obj = self._post({"jsonrpc": "2.0", "id": self._next_id(),
                          "method": method, "params": params})
        if obj is None:
            raise MCPHttpError(f"sin respuesta del MCP remoto a {method}")
        if isinstance(obj, dict) and obj.get("error"):
            raise MCPHttpError(
                f"error del MCP remoto en {method}: {obj['error']}",
                evidencia={
                    "respuesta": obj,
                    "protocolo": _evidencia_protocolo(obj, self.protocol_version),
                    "red": {"consultada": True, "online": True},
                },
            )
        return (obj or {}).get("result", {}) if isinstance(obj, dict) else {}

    # ── handshake + operaciones ─────────────────────────────────────────────────
    def initialize(self) -> dict:
        result = self._rpc("initialize", {
            "protocolVersion": self.protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "puppet-byo", "version": "0.1.0"},
        })
        pv = result.get("protocolVersion")
        if isinstance(pv, str) and pv:
            self.protocol_version = pv
        self.server_info = result.get("serverInfo", {}) or {}
        # notificación obligatoria post-init (best-effort: un fallo acá no tumba el handshake)
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                       is_notification=True)
        except MCPHttpError:
            pass
        return result

    def list_tools(self) -> list[dict]:
        result = self._rpc("tools/list", {})
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict:
        """Devuelve el `result` crudo de tools/call: {content:[...], isError:bool}."""
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        """Best-effort: cerrar la sesión remota si el server la abrió (DELETE)."""
        if not self.session_id:
            return
        try:
            req = urllib.request.Request(self.url, method="DELETE", headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
        except Exception:
            pass
        finally:
            self.session_id = None


def _parse_sse_jsonrpc(raw: str) -> Optional[dict]:
    """De un cuerpo SSE devuelve el PRIMER evento `data:` que sea un JSON-RPC con result/error.

    Reensambla líneas `data:` consecutivas de un mismo evento (la spec SSE permite multi-línea),
    separando eventos por líneas en blanco.
    """
    event_lines: list[str] = []

    def _flush(lines: list[str]) -> Optional[dict]:
        if not lines:
            return None
        payload = "\n".join(lines).strip()
        if not payload:
            return None
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, dict) and ("result" in obj or "error" in obj):
            return obj
        return None

    for line in raw.splitlines():
        if line.startswith("data:"):
            event_lines.append(line[len("data:"):].lstrip())
        elif line.strip() == "":
            found = _flush(event_lines)
            event_lines = []
            if found is not None:
                return found
        # ignoramos `event:`/`id:`/`:comment`
    return _flush(event_lines)


__all__ = ["MCPHttpClient", "MCPHttpError"]
