#!/usr/bin/env python3
"""
ORCID MCP server (stdio, JSON-RPC 2.0) — keyless (Public API read), read-only.

Wrapper MCP delgado sobre la Public API de ORCID (pub.orcid.org/v3.0), SIN token para
LECTURA pública:
  • search(query, rows)   → busca investigadores por nombre → ORCID iD + institución.
  • works(orcid_id, rows) → trae las obras PÚBLICAS de un ORCID iD (título, año, DOI).
Dato REAL en vivo. Sólo stdlib (urllib + json). Read-only → el enforcer lo deja.

NOTA: escribir EN TU registro ORCID (agregar una obra) requiere OAuth 3-legged (Caso A,
app registrada) — eso es el flujo de ESCRITURA, follow-up. Esta lectura pública ya funciona.
"""
import json
import sys
import urllib.parse
import urllib.request

_BASE = "https://pub.orcid.org/v3.0"
_UA = "puppet-ai-toolbelt/0.1 (mailto:contact@example.invalid)"
_TIMEOUT = 25

TOOLS = [
    {
        "name": "orcid_search",
        "description": (
            "Busca investigadores en ORCID por nombre/texto. Devuelve su ORCID iD, nombre e "
            "institución. Lectura pública, sin credenciales."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nombre o texto a buscar."},
                "rows": {"type": "integer", "description": "Cuántos resultados (1-5).", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "orcid_works",
        "description": (
            "Trae las obras PÚBLICAS de un investigador por su ORCID iD "
            "(p. ej. '0000-0002-1825-0097'): título, año y DOI. Lectura, sin credenciales."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "orcid_id": {"type": "string", "description": "El ORCID iD (con guiones)."},
                "rows": {"type": "integer", "description": "Cuántas obras (1-10).", "default": 5},
            },
            "required": ["orcid_id"],
        },
    },
]


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _search(query: str, rows: int = 3) -> dict:
    rows = max(1, min(int(rows or 3), 5))
    qs = urllib.parse.urlencode({"q": query, "rows": rows})
    data = _get_json("%s/expanded-search/?%s" % (_BASE, qs))
    out = []
    for r in (data.get("expanded-result") or [])[:rows]:
        name = " ".join(x for x in [r.get("given-names"), r.get("family-names")] if x)
        inst = (r.get("institution-name") or [None])
        out.append({
            "orcid_id": r.get("orcid-id"),
            "name": name or r.get("credit-name"),
            "institution": inst[0] if inst else None,
            "url": "https://orcid.org/%s" % r.get("orcid-id") if r.get("orcid-id") else None,
        })
    return {"query": query, "total_results": data.get("num-found"), "results": out}


def _work_doi(ext) -> str:
    for e in ((ext or {}).get("external-id") or []):
        if e.get("external-id-type") == "doi":
            return e.get("external-id-value")
    return None


def _works(orcid_id: str, rows: int = 5) -> dict:
    rows = max(1, min(int(rows or 5), 10))
    oid = orcid_id.strip()
    data = _get_json("%s/%s/works" % (_BASE, urllib.parse.quote(oid, safe="-")))
    out = []
    for g in (data.get("group") or []):
        ws = (g.get("work-summary") or [{}])[0]
        title = (((ws.get("title") or {}).get("title") or {}).get("value")) or "(sin título)"
        yr = (((ws.get("publication-date") or {}).get("year") or {}).get("value"))
        out.append({"title": title, "year": int(yr) if yr and str(yr).isdigit() else None,
                    "type": ws.get("type"), "doi": _work_doi(ws.get("external-ids"))})
        if len(out) >= rows:
            break
    return {"orcid_id": oid, "count": len(out), "works": out}


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})
    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "orcid-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "orcid_search":
                val = _search(args.get("query", ""), args.get("rows", 3))
            elif name == "orcid_works":
                val = _works(args.get("orcid_id", ""), args.get("rows", 5))
            else:
                raise ValueError("unknown tool %s" % name)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}], "isError": False}})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": "error: %s" % exc}], "isError": True}})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": "Method not found: %s" % method}})


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
