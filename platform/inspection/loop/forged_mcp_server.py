#!/usr/bin/env python3
"""
forged_mcp_server.py — server MCP stdio del MCP FORJADO en vivo (Capa 5).

Sirve, como CUALQUIER belt, las N tools de lectura que el loop verificó contra el
software real. JSON-RPC 2.0 por stdin/stdout (mismo dialecto que synth_mcp_server).

Lo que lo hace honesto:
  • la api_key se RESUELVE del vault Fernet (FORGE_CRED_FILE) en el momento de la
    llamada — el manifest solo trae un PLACEHOLDER (cred_ref), nunca el secreto en
    claro (cierra CASO D);
  • READ: GET vivo con la auth del spec — token en query (Forma 1) o la sesión
    en header/cookie (Forma 2/3). FORGE_DRY_RUN=1 devuelve la request sin pegarla.
  • WRITE (§7): GATED · FAIL-CLOSED. Una tool con `gated`/`kind=="write"` (o método
    mutante) NO se ejecuta directo: devuelve la request ARMADA + `approval_required`
    (el gate humano visible antes de tocar el mundo). FORGE_DRY_RUN la devuelve sin
    pegarla. El server forjado nunca emite POST/PUT/PATCH/DELETE por su cuenta.

Entradas (env):  FORGE_SPEC (json del MCP) · FORGE_CRED_FILE (vault) · FORGE_EXECUTE.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLATFORM = _HERE.parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection.loop.live_http import LiveHTTP  # noqa: E402

_PATH_PARAM = re.compile(r"\{([^}]+)\}")
# §7 · métodos seguros de ejecutar (no mutan). Todo lo demás es GATED.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _load_spec() -> dict:
    p = os.environ.get("FORGE_SPEC", "")
    if not p or not Path(p).exists():
        raise RuntimeError(f"FORGE_SPEC no apunta a un spec válido: {p!r}")
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _resolve_secret() -> str:
    """Lee la api_key del vault Fernet (NUNCA del manifest)."""
    cred_file = os.environ.get("FORGE_CRED_FILE", "")
    cred_name = (_SPEC.get("auth") or {}).get("cred_name", "API_KEY")
    if not cred_file or not Path(cred_file).exists():
        return ""
    from inspection import crypto  # carga el CredentialVault del org
    vault_mod = crypto._load_vault_module()
    master = os.environ.get("PUPPET_VAULT_MASTER") or crypto.runtime_master_secret()
    vault = vault_mod.CredentialVault(cred_file, master_secret=master)
    if not vault.has(cred_name):
        return ""
    return vault.inject_env({}, [cred_name]).get(cred_name, "") or ""


_SPEC = _load_spec()
_BASE = (_SPEC.get("base_url") or "").rstrip("/")
_AUTH = _SPEC.get("auth") or {}
_AUTH_PARAM = _AUTH.get("param", "api_key")
_TOOLS = {t["name"]: t for t in (_SPEC.get("tools") or []) if t.get("name")}


def _auth_kwargs(secret: str) -> dict:
    """Cómo el server forjado inyecta la credencial del vault, según el `auth` del spec.
    query (Forma 1) → token en query (idéntico a siempre); header/cookie (Forma 2/3) →
    la sesión viaja en header (con su template) o cookie, NUNCA en la URL."""
    where = _AUTH.get("in", "query")
    if where == "header":
        template = _AUTH.get("template", "Bearer {token}")
        value = template.format(token=secret) if "{token}" in template else secret
        return {"headers": {_AUTH.get("name", "Authorization"): value}}
    if where == "cookie":
        return {"cookies": {_AUTH.get("name", "session"): secret}}
    return {"secret": secret, "auth_param": _AUTH_PARAM}
_EXECUTE = _truthy(os.environ.get("FORGE_EXECUTE", "1")) and not _truthy(os.environ.get("FORGE_DRY_RUN"))


def _mcp_tool_defs() -> list[dict]:
    out = []
    for t in _TOOLS.values():
        out.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "inputSchema": t.get("input_schema") or {"type": "object", "properties": {}},
        })
    return out


def _build_url(tool: dict, args: dict) -> tuple[str, dict, list]:
    sample = tool.get("sample_call") or {}
    path_params = {**(sample.get("path_params") or {}), **{k: v for k, v in args.items()}}
    query = {**(sample.get("query") or {}), **{k: v for k, v in args.items()}}
    path = tool["endpoint"]
    missing = []
    for name in _PATH_PARAM.findall(tool["endpoint"]):
        if name in path_params and path_params[name] not in (None, ""):
            path = path.replace("{" + name + "}", str(path_params[name]))
            query.pop(name, None)
        else:
            missing.append(name)
    return _BASE + path, query, missing


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _build_body(tool: dict, args: dict) -> dict:
    """El cuerpo que la write LLEVARÍA: sample_call.body + los args que no son path params.
    Solo para ARMAR la request (mostrarla en el gate / dry-run); nunca se pega desde acá."""
    sample = tool.get("sample_call") or {}
    body = dict(sample.get("body") or {})
    path_names = set(_PATH_PARAM.findall(tool.get("endpoint", "")))
    for k, v in (args or {}).items():
        if k not in path_names:
            body[k] = v
    return body


def _is_gated(tool: dict, method: str) -> bool:
    """§7: una tool se gatea si el spec la marca (gated/kind=write) o su método muta."""
    return bool(tool.get("gated")) or tool.get("kind") == "write" or method not in _SAFE_METHODS


def _call_tool(name: str, args: dict) -> dict:
    tool = _TOOLS.get(name)
    if not tool:
        return {"refused": True, "reason": f"tool desconocida: {name}"}
    url, query, missing = _build_url(tool, args or {})
    if missing:
        return {"refused": True, "reason": f"faltan path params: {missing}"}

    method = (tool.get("method") or "GET").upper()
    if _is_gated(tool, method):
        # §7 · FAIL-CLOSED: la write NUNCA se pega desde acá. Dry-run → request armada;
        # ejecución → request armada + gate humano (no toca el mundo).
        armed = {"method": method, "url": url, "query": query, "body": _build_body(tool, args or {})}
        if not _EXECUTE:
            return {"dry_run": True, "gated": True, "request": armed}
        return {"gated": True, "approval_required": True, "request": armed,
                "reason": "write tool GATED — exige gate humano visible antes de tocar el mundo (§7)"}

    # READ (seguro): GET vivo, o dry-run que devuelve la request sin pegarla.
    if not _EXECUTE:
        return {"dry_run": True, "request": {"method": method, "url": url, "query": query}}
    secret = _resolve_secret()
    try:
        _interval = float(os.environ.get("FORGE_MIN_INTERVAL", "0") or 0)
    except ValueError:
        _interval = 0.0
    http = LiveHTTP(timeout=15.0, min_interval=_interval, **_auth_kwargs(secret))
    res = http.get(url, query)
    return {
        "dry_run": False,
        "request": {"method": method, "url": res.url_redacted},
        "response": {"status": res.status, "json": res.json},
    }


def _handle(req: dict) -> None:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {}) or {}

    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": f"forged-{Path(_SPEC.get('base_url','')).name or 'mcp'}",
                           "version": "1.0.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _mcp_tool_defs()}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        out = _call_tool(name, args)
        is_err = bool(out.get("refused")) or (
            (out.get("response", {}) or {}).get("status") not in (None, 200, 201, 204)
            if not out.get("dry_run") else False)
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
            "isError": is_err,
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
