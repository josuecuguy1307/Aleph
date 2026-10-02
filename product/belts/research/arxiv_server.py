#!/usr/bin/env python3
"""
arXiv MCP server (stdio, JSON-RPC 2.0) — keyless, read-only.

Wrapper MCP delgado sobre la API pública de arXiv (export.arxiv.org/api), SIN key.
  • search(query, rows) → busca preprints en arXiv por texto libre.
Devuelve título, arXiv id/URL, autores, año, categoría y DOI (si lo declara). Dato
REAL en vivo (ATOM XML parseado con stdlib). Read-only → el enforcer lo deja.
"""
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_BASE = "http://export.arxiv.org/api/query"
_UA = "puppet-ai-toolbelt/0.1 (mailto:contact@example.invalid)"
_TIMEOUT = 25
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARX = "{http://arxiv.org/schemas/atom}"

TOOLS = [
    {
        "name": "arxiv_search",
        "description": (
            "Busca preprints en arXiv por texto libre (título, autor, tema). Devuelve "
            "título, id de arXiv, URL, autores, año, categoría y DOI si está. Lectura, "
            "sin credenciales."
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


def _text(node):
    return node.text.strip() if node is not None and node.text else None


def _fmt(entry) -> dict:
    arxiv_url = _text(entry.find(_ATOM + "id"))
    arxiv_id = arxiv_url.rsplit("/abs/", 1)[-1] if arxiv_url and "/abs/" in arxiv_url else arxiv_url
    pub = _text(entry.find(_ATOM + "published"))
    year = int(pub[:4]) if pub and pub[:4].isdigit() else None
    authors = []
    for a in entry.findall(_ATOM + "author"):
        n = _text(a.find(_ATOM + "name"))
        if n:
            authors.append(n)
    cat = entry.find(_ARX + "primary_category")
    return {
        "title": (_text(entry.find(_ATOM + "title")) or "(sin título)").replace("\n", " ").strip(),
        "arxiv_id": arxiv_id,
        "url": arxiv_url,
        "authors": authors[:5],
        "year": year,
        "category": cat.get("term") if cat is not None else None,
        "doi": _text(entry.find(_ARX + "doi")),
    }


def _search(query: str, rows: int = 3) -> dict:
    rows = max(1, min(int(rows or 3), 5))
    qs = urllib.parse.urlencode({"search_query": "all:%s" % query, "start": 0, "max_results": rows})
    req = urllib.request.Request("%s?%s" % (_BASE, qs),
                                 headers={"User-Agent": _UA, "Accept": "application/atom+xml"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        root = ET.fromstring(resp.read().decode("utf-8"))
    entries = root.findall(_ATOM + "entry")
    total_node = root.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
    total = int(total_node.text) if total_node is not None and total_node.text else None
    return {"query": query, "total_results": total, "results": [_fmt(e) for e in entries]}


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
            "serverInfo": {"name": "arxiv-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "arxiv_search":
                val = _search(args.get("query", ""), args.get("rows", 3))
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
