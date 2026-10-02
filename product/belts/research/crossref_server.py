#!/usr/bin/env python3
"""
Crossref MCP server (stdio, JSON-RPC 2.0) — keyless, read-only.

Tier B / Caso 1 (drop-in): wrapper MCP delgado sobre la API pública de Crossref
(api.crossref.org), SIN key y SIN OAuth. Expone DOS tools de LECTURA:

  • search_works(query, rows)  → busca publicaciones académicas por texto libre.
  • get_work(doi)              → trae los metadatos de un DOI concreto.

Sólo stdlib (urllib). Read-only: ninguna tool escribe, manda ni toca plata, así
que el enforcer de gates las clasifica como lectura (auto-ejecuta). El dato que
devuelve es REAL: viene de api.crossref.org en vivo, no hay stub.

Etiqueta de cortesía de Crossref: mandamos User-Agent con un mailto (su "polite
pool"), tal como pide su doc pública.
"""

import json
import sys
import urllib.parse
import urllib.request

_BASE = "https://api.crossref.org"
_UA = "puppet-ai-toolbelt/0.1 (mailto:contact@example.invalid)"
_TIMEOUT = 20

TOOLS = [
    {
        "name": "search_works",
        "description": (
            "Busca publicaciones académicas en Crossref por texto libre "
            "(título, autor, tema). Devuelve título, DOI, autores, año y revista "
            "de los primeros resultados. Lectura, sin credenciales."
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
    {
        "name": "get_work",
        "description": (
            "Trae los metadatos de una publicación por su DOI exacto "
            "(p. ej. '10.1038/nphys1170'). Lectura, sin credenciales."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "El DOI exacto de la obra."},
            },
            "required": ["doi"],
        },
    },
]


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fmt_item(it: dict) -> dict:
    title = (it.get("title") or ["(sin título)"])[0]
    authors = []
    for a in it.get("author", [])[:5]:
        name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if name:
            authors.append(name)
    year = None
    for k in ("published-print", "published-online", "issued", "created"):
        parts = (it.get(k) or {}).get("date-parts")
        if parts and parts[0]:
            year = parts[0][0]
            break
    container = (it.get("container-title") or [None])[0]
    return {
        "title": title,
        "doi": it.get("DOI"),
        "authors": authors,
        "year": year,
        "container": container,
        "type": it.get("type"),
        "url": it.get("URL"),
    }


def _search_works(query: str, rows: int = 3) -> dict:
    rows = max(1, min(int(rows or 3), 5))
    qs = urllib.parse.urlencode({"query": query, "rows": rows})
    data = _get_json(f"{_BASE}/works?{qs}")
    items = data.get("message", {}).get("items", [])
    total = data.get("message", {}).get("total-results")
    return {"query": query, "total_results": total, "results": [_fmt_item(it) for it in items]}


def _get_work(doi: str) -> dict:
    doi_enc = urllib.parse.quote(doi.strip(), safe="")
    data = _get_json(f"{_BASE}/works/{doi_enc}")
    item = data.get("message", {})
    if not item:
        return {"doi": doi, "found": False}
    out = _fmt_item(item)
    out["found"] = True
    out["abstract"] = item.get("abstract")
    out["referenced_by_count"] = item.get("is-referenced-by-count")
    return out


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
            "serverInfo": {"name": "crossref-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "search_works":
                val = _search_works(args.get("query", ""), args.get("rows", 3))
            elif name == "get_work":
                val = _get_work(args.get("doi", ""))
            else:
                raise ValueError(f"unknown tool {name}")
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": False,
            }})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error: {exc}"}], "isError": True,
            }})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": f"Method not found: {method}"}})


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
