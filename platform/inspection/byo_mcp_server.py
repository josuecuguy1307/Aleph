#!/usr/bin/env python3
"""
byo_mcp_server.py — PUENTE stdio↔HTTP para un MCP PROPIO del usuario (BYO-MCP, FASE 1 · C3).

El assembler de Puppet AI solo sabe lanzar MCP servers por **stdio** (subprocess + JSON-RPC
por stdin/stdout — ver platform/assembler/assembler.py::MCPServer). Un MCP que el usuario
PEGA por HTTP (público, Streamable HTTP) no encaja en eso directamente. Este proceso es el
adaptador: el assembler lo lanza como un server stdio NORMAL, y él reenvía cada llamada al
MCP REMOTO por HTTP (vía `inspection.transporte`, que desde la sesión 3 elige el puente al
SDK oficial o el cliente viejo según `ALEPH_TRANSPORTE`). Así "pegá tu MCP → Sumar" produce
un belt equipable como cualquier otro, SIN tocar el assembler (invariante: no redefinimos T5).

Manifiesto (argv[1], o env BYO_MCP_MANIFEST como fallback):
    {
      "url": "https://...",                 # endpoint del MCP remoto (obligatorio)
      "headers": {"Authorization": "..."},  # opcional (BYO con auth simple por header)
      "allowed_tools": ["tool_a", ...],     # opcional: subset a exponer (si falta, todas)
      "label": "Mi MCP"                      # opcional, para logs
    }

GATE: este puente NO decide gates. El candado vive ARRIBA, en la sesión (el enforcer fuerza
money/send por nombre de tool sobre CUALQUIER server, incluido este). El puente solo ejecuta
lo que el registry gateado ya autorizó. Reads pasan; un BYO con tool de escritura igual cae
bajo el gate del motor.

JSON-RPC 2.0 por líneas, logs SOLO a stderr (mismo dialecto que synth_mcp_server.py).
Stdlib pura.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# bootstrap: platform/ en el path para importar el paquete inspection
_PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))

# EL TRANSPORTE LO ELIGE `transporte` (sesión 3): el puente al SDK por default, el
# cliente viejo con ALEPH_TRANSPORTE=viejo. Este puente BYO se spawnea DE VERDAD —es el
# server stdio de toda entidad HTTP equipada, `byo-ai-exa-exa` entre ellas—, así que
# hablarle al remoto por fuera del switch dejaba un camino de producto sin migrar.
from inspection import transporte as _TP


def _log(msg: str) -> None:
    print(f"[byo-mcp] {msg}", file=sys.stderr, flush=True)


def _expand_env(headers: dict) -> dict:
    """Expande ${VAR}/$VAR en los VALORES de los headers contra os.environ (no toca las
    claves). Un valor sin ${} queda igual. Esto permite que el manifest seguro del resolver
    guarde `{"Authorization": "Bearer ${RESOLVER_X_API_KEY}"}` en disco (placeholder, NO el
    secreto) y que el secreto real se materialice solo en runtime desde el env inyectado por
    el assembler (vault → byok_ref → child_env). os.path.expandvars usa os.environ."""
    out = {}
    for k, v in (headers or {}).items():
        if isinstance(v, str):
            ref = _REF_HEADER.match(v.strip())
            out[k] = _del_paquete(ref) if ref else os.path.expandvars(v)
        else:
            out[k] = v
    return out


#: [S4] La forma `${VAR:NombreDelHeader}` — el manifest de un BYO-HTTP forjado por
#: `byo_mcp.forge_byo_belt`. Los headers que el usuario pega van CIFRADOS al llavero como
#: UN solo valor (un JSON `{header: valor}`), no uno por header: es una sola credencial en
#: la UI, una sola rotación y una sola fila del vault. Por eso hace falta un placeholder que
#: además diga QUÉ header sacar del paquete — `${VAR}` a secas no alcanzaría.
_REF_HEADER = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*):([^}]+)\}$")


def _del_paquete(ref) -> str:
    """El valor de un header dentro del JSON que vino en la env var, o el literal.

    Devolver el placeholder tal cual cuando falta es deliberado y es la misma regla que ya
    tenía `${VAR}` sin setear: el remoto contesta 401 —fallo honesto y accionable— en vez de
    que el puente arranque sin auth y el usuario vea «anduvo» con media superficie."""
    var, nombre = ref.group(1), ref.group(2)
    crudo = os.environ.get(var) or ""
    if not crudo:
        return ref.group(0)
    try:
        return json.loads(crudo).get(nombre) or ref.group(0)
    except (ValueError, AttributeError):
        # La env var existe pero no es el paquete que esperábamos. NO se usa como valor de
        # header: mandar un JSON entero como `Authorization` filtraría los OTROS headers al
        # remoto.
        _log(f"la variable {var} no tiene la forma del paquete de headers; se ignora")
        return ref.group(0)


def _load_manifest() -> dict:
    raw = None
    if len(sys.argv) > 1 and sys.argv[1].strip():
        p = Path(sys.argv[1])
        if p.exists():
            raw = p.read_text(encoding="utf-8")
    if raw is None:
        env = os.environ.get("BYO_MCP_MANIFEST", "")
        if env and Path(env).exists():
            raw = Path(env).read_text(encoding="utf-8")
        elif env.strip().startswith("{"):
            raw = env  # inline JSON
    if raw is None:
        raise RuntimeError("BYO manifest no encontrado (ni argv[1] ni BYO_MCP_MANIFEST)")
    man = json.loads(raw)
    if not man.get("url"):
        raise RuntimeError("BYO manifest sin 'url'")
    return man


class _Bridge:
    """Mantiene un cliente HTTP vivo al MCP remoto; init perezoso al primer uso."""

    def __init__(self, manifest: dict):
        self.url = manifest["url"]
        # [resolver/seguridad] Los valores de header se EXPANDEN contra os.environ en
        # RUNTIME: un manifest seguro guarda un PLACEHOLDER ${VAR} (no el secreto en claro),
        # y el secreto llega como env var inyectada por el assembler desde el vault (resuelta
        # por keys.<provider>.byok_ref). Un header SIN ${} queda idéntico → compat total con
        # el BYO viejo. Un ${VAR} no seteada queda literal → el remoto responde 401 (fallo
        # honesto), nunca se filtra el secreto.
        self.headers = _expand_env(manifest.get("headers") or {})
        self.allowed = manifest.get("allowed_tools")  # None = todas
        self.label = manifest.get("label") or self.url
        self._client = None
        self._tools_cache: list[dict] | None = None

    def _ensure(self):
        if self._client is None:
            c = _TP.cliente_http()(self.url, self.headers)
            c.initialize()
            self._client = c
            _log(f"conectado a {self.label} ({c.server_info.get('name','?')})")
        return self._client

    def list_tools(self) -> list[dict]:
        if self._tools_cache is None:
            tools = self._ensure().list_tools()
            if self.allowed is not None:
                allow = set(self.allowed)
                tools = [t for t in tools if t.get("name") in allow]
            self._tools_cache = tools
        return self._tools_cache

    def call_tool(self, name: str, arguments: dict) -> dict:
        if self.allowed is not None and name not in set(self.allowed):
            return {"content": [{"type": "text",
                                 "text": f"tool '{name}' no está habilitada en este MCP propio"}],
                    "isError": True}
        return self._ensure().call_tool(name, arguments)


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(bridge: _Bridge, req: dict) -> None:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {}) or {}

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "byo-mcp-bridge", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        try:
            tools = bridge.list_tools()
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})
        except _TP.error_http() as e:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32001, "message": f"BYO remoto: {e}"}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            result = bridge.call_tool(name, args)
            # el resultado remoto YA es {content:[...], isError:bool}; pasamos tal cual.
            if not isinstance(result, dict) or "content" not in result:
                result = {"content": [{"type": "text",
                                       "text": json.dumps(result, ensure_ascii=False)}],
                          "isError": False}
            _send({"jsonrpc": "2.0", "id": req_id, "result": result})
        except _TP.error_http() as e:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error llamando al MCP propio: {e}"}],
                "isError": True}})
        except Exception as e:  # noqa: BLE001
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error inesperado en el puente BYO: {e}"}],
                "isError": True}})
    elif req_id is not None:
        _send({"jsonrpc": "2.0", "id": req_id,
               "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main() -> None:
    try:
        manifest = _load_manifest()
    except Exception as e:  # noqa: BLE001
        _log(f"FATAL cargando manifest: {e}")
        sys.exit(1)
    bridge = _Bridge(manifest)
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        try:
            _handle(bridge, req)
        except Exception as e:  # noqa: BLE001 — un fallo manejando un request no tumba el server
            _log(f"error manejando {req.get('method')!r}: {e}")


if __name__ == "__main__":
    main()
