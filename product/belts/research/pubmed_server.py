#!/usr/bin/env python3
"""
PubMed MCP server (stdio, JSON-RPC 2.0) — keyless, read-only.

Wrapper MCP delgado sobre E-utilities de NCBI/PubMed (eutils.ncbi.nlm.nih.gov), SIN key.
  • search(query, rows) → busca artículos biomédicos por texto libre.
Dos pasos REALES: esearch (ids) → esummary (metadatos). Devuelve título, PMID, autores,
año, revista y DOI. Sólo stdlib (urllib + json). Read-only → el enforcer lo deja.
"""
import json
import sys
import urllib.parse
import urllib.request

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TOOL = "puppet-ai-toolbelt"
_EMAIL = "contact@example.invalid"   # cortesía NCBI
_UA = "puppet-ai-toolbelt/0.1 (mailto:%s)" % _EMAIL
_TIMEOUT = 25

TOOLS = [
    {
        "name": "pubmed_search",
        "description": (
            "Busca artículos biomédicos en PubMed por texto libre (título, autor, tema). "
            "Devuelve título, PMID, autores, año, revista y DOI. Lectura, sin credenciales."
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


def _doi(ids) -> str:
    for x in (ids or []):
        if x.get("idtype") == "doi":
            return x.get("value")
    return None


def _fmt(rec: dict) -> dict:
    authors = [a.get("name") for a in (rec.get("authors") or [])[:5] if a.get("name")]
    pub = rec.get("pubdate") or ""
    year = int(pub[:4]) if pub[:4].isdigit() else None
    return {
        "title": rec.get("title") or "(sin título)",
        "pmid": rec.get("uid"),
        "authors": authors,
        "year": year,
        "container": rec.get("source") or rec.get("fulljournalname"),
        "doi": _doi(rec.get("articleids")),
    }


def _search(query: str, rows: int = 3) -> dict:
    rows = max(1, min(int(rows or 3), 5))
    qs = urllib.parse.urlencode({"db": "pubmed", "term": query, "retmax": rows,
                                 "retmode": "json", "tool": _TOOL, "email": _EMAIL})
    es = _get_json("%s/esearch.fcgi?%s" % (_BASE, qs)).get("esearchresult", {})
    ids = es.get("idlist", []) or []
    total = es.get("count")
    if not ids:
        return {"query": query, "total_results": total, "results": []}
    sq = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json",
                                 "tool": _TOOL, "email": _EMAIL})
    summ = _get_json("%s/esummary.fcgi?%s" % (_BASE, sq)).get("result", {})
    out = []
    for uid in summ.get("uids", ids):
        rec = summ.get(uid)
        if isinstance(rec, dict):
            out.append(_fmt(rec))
    return {"query": query, "total_results": total, "results": out}


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
            "serverInfo": {"name": "pubmed-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "pubmed_search":
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
