#!/usr/bin/env python3
"""
OpenAlex MCP server (stdio, JSON-RPC 2.0) — keyless, read-only.

Wrapper MCP delgado sobre la API pública de OpenAlex (api.openalex.org), SIN key.
  • search_works(query, rows) → busca trabajos académicos por texto libre.
Dato REAL en vivo (no stub). Sólo stdlib (urllib). Read-only → el enforcer lo deja.
"""
import json
import sys
import urllib.parse
import urllib.request

_BASE = "https://api.openalex.org"
_MAILTO = "contact@example.invalid"   # polite pool de OpenAlex
_UA = "puppet-ai-toolbelt/0.1 (mailto:%s)" % _MAILTO
_TIMEOUT = 20

TOOLS = [
    {
        "name": "openalex_search",
        "description": (
            "Busca trabajos académicos en OpenAlex por texto libre (título, tema, autor). "
            "Devuelve título, DOI, autores, año, revista y nº de citas de los primeros "
            "resultados. Lectura, sin credenciales."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto a buscar."},
                "rows": {"type": "integer", "description": "Cuántos resultados (1-5).", "default": 3},
            },
            "required": ["query"],
        },
    },
]


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _doi(work: dict):
    d = work.get("doi")
    if d and d.startswith("https://doi.org/"):
        return d[len("https://doi.org/"):]
    return d


def _fmt(work: dict) -> dict:
    authors = [(a.get("author") or {}).get("display_name") for a in (work.get("authorships") or [])[:5]]
    authors = [a for a in authors if a]
    venue = (((work.get("primary_location") or {}).get("source") or {}).get("display_name"))
    return {
        "title": work.get("display_name") or "(sin título)",
        "doi": _doi(work),
        "authors": authors,
        "year": work.get("publication_year"),
        "container": venue,
        "cited_by": work.get("cited_by_count"),
        "openalex_id": work.get("id"),
        "type": work.get("type"),
    }


def _search_works(query: str, rows: int = 3) -> dict:
    rows = max(1, min(int(rows or 3), 5))
    qs = urllib.parse.urlencode({"search": query, "per-page": rows, "mailto": _MAILTO})
    data = _get_json("%s/works?%s" % (_BASE, qs))
    results = data.get("results", []) or []
    total = (data.get("meta") or {}).get("count")
    return {"query": query, "total_results": total, "results": [_fmt(w) for w in results]}


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
            "serverInfo": {"name": "openalex-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "openalex_search":
                val = _search_works(args.get("query", ""), args.get("rows", 3))
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
