#!/usr/bin/env python3
"""armed_executor.py — dispara UNA request ARMADA de un belt forjado, DESDE EL PATH CONFIABLE.

TICKET 36 · el enfoque (A) aprobado por persona usuaria. §7 se mantiene INTACTO: `forged_mcp_server.py`
NUNCA emite POST/PUT/PATCH/DELETE por su cuenta (grep-verificable: ese archivo no dispara writes).
Este módulo — SEPARADO, invocado SÓLO por `execute_held_tool` TRAS el OK EXPLÍCITO del dueño
(approve-by-HTTP) — dispara la request que el server forjado ARMÓ y (correctamente) no pegó.

Se acabó el "executed sobre dry-run": approve → POST real → id real; reject → nunca llega acá.
Auth = MISMO vault Fernet del belt (FORGE_CRED_FILE) que el server usa para reads. Sin deps nuevas
(urllib stdlib). NUNCA loguea ni devuelve el secreto.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _resolve_secret(env: dict, auth: dict) -> str:
    """La credencial del belt desde el vault Fernet (FORGE_CRED_FILE) — idéntico camino que el
    forged_mcp_server para reads. Nunca del manifest en claro."""
    cred_file = env.get("FORGE_CRED_FILE", "")
    cred_name = (auth or {}).get("cred_name", "API_KEY")
    if not cred_file or not Path(cred_file).exists():
        return ""
    _platform = Path(__file__).resolve().parents[2]
    if str(_platform) not in sys.path:
        sys.path.insert(0, str(_platform))
    from inspection import crypto  # CredentialVault del org
    vault_mod = crypto._load_vault_module()
    master = env.get("PUPPET_VAULT_MASTER") or crypto.runtime_master_secret()
    vault = vault_mod.CredentialVault(cred_file, master_secret=master)
    if not vault.has(cred_name):
        return ""
    return vault.inject_env({}, [cred_name]).get(cred_name, "") or ""


def fire_armed_request(armed: dict, env: dict) -> dict:
    """Dispara la request armada {method,url,query,body} con la auth del belt (`env` = el env del
    server forjado: FORGE_SPEC/FORGE_CRED_FILE/PUPPET_VAULT_MASTER). Devuelve
    {ok, status, result:{status,id,json}, error}. Sólo métodos mutantes (un GET no viene por acá)."""
    try:
        method = str(armed.get("method", "")).upper()
        url = armed.get("url") or ""
        if method not in _WRITE_METHODS:
            return {"ok": False, "error": f"armed_executor sólo dispara writes; method={method!r}"}
        if not url:
            return {"ok": False, "error": "armed request sin url"}

        spec_path = env.get("FORGE_SPEC", "")
        auth: dict = {}
        if spec_path and Path(spec_path).exists():
            auth = (json.loads(Path(spec_path).read_text(encoding="utf-8")).get("auth") or {})
        secret = _resolve_secret(env, auth)

        query = dict(armed.get("query") or {})
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        cookie = None
        where = auth.get("in", "query")
        if where == "header":
            tmpl = auth.get("template", "Bearer {token}")
            headers[auth.get("name", "Authorization")] = (
                tmpl.format(token=secret) if "{token}" in tmpl else secret)
        elif where == "cookie":
            cookie = f'{auth.get("name", "session")}={secret}'
        else:  # query — el secreto viaja en la URL (no se loguea: url_redacted abajo)
            if secret:
                query[auth.get("param", "api_key")] = secret

        full = url + (("?" + urllib.parse.urlencode(query)) if query else "")
        body = armed.get("body")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(full, data=data, method=method, headers=headers)
        if cookie:
            req.add_header("Cookie", cookie)

        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                status = getattr(r, "status", None) or r.getcode()
                text = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status = e.code
            text = e.read().decode("utf-8", "replace")
        except urllib.error.URLError as e:
            # NO exponer `full` (podría llevar el secreto en query-auth)
            return {"ok": False, "error": f"no se pudo conectar al software: {getattr(e, 'reason', 'error de red')}"}

        parsed = None
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        rid = None
        if isinstance(parsed, dict):
            rid = parsed.get("pk") or parsed.get("id") or parsed.get("reference")
        ok = 200 <= int(status) < 300
        return {"ok": ok, "status": int(status),
                "result": {"status": int(status), "id": rid,
                           "json": parsed if parsed is not None else text[:500]},
                "error": None if ok else f"HTTP {status}: {text[:300]}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
