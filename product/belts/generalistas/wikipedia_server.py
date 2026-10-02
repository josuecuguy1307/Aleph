#!/usr/bin/env python3
"""
Wikipedia / Wikimedia MCP server (stdio, JSON-RPC 2.0) — keyless, read-only.

Tier B / Caso 1 (drop-in): wrapper MCP delgado sobre las REST APIs públicas de
Wikimedia, SIN key y SIN OAuth. Recurso educativo abierto (OER). Expone DOS tools
de LECTURA, parametrizadas por idioma (default 'es' para el wedge hispanohablante):

  • search_pages(query, lang, limit) → busca artículos por texto (Core REST search).
  • get_summary(title, lang)         → extracto/resumen de un artículo (REST summary).

Sólo stdlib (urllib). Read-only: ninguna tool escribe, manda ni toca plata, así
que el enforcer de gates las clasifica como lectura (auto-ejecuta). Dato REAL en
vivo desde wikipedia.org / api.wikimedia.org, no hay stub.
"""

import json
import sys
import urllib.parse
import urllib.request

_UA = "puppet-ai-toolbelt/0.1 (mailto:contact@example.invalid)"
_TIMEOUT = 20


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


TOOLS = [
    {
        "name": "search_pages",
        "description": (
            "Busca artículos de Wikipedia por texto libre. Devuelve título, "
            "descripción corta y extracto de los primeros resultados. Recurso "
            "educativo abierto, lectura, sin credenciales."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto a buscar."},
                "lang": {"type": "string", "description": "Código de idioma (es, en, ...).", "default": "es"},
                "limit": {"type": "integer", "description": "Cuántos resultados (1-5).", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_summary",
        "description": (
            "Trae el resumen/extracto de un artículo de Wikipedia por su título "
            "exacto. Recurso educativo abierto, lectura, sin credenciales."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título exacto del artículo."},
                "lang": {"type": "string", "description": "Código de idioma (es, en, ...).", "default": "es"},
            },
            "required": ["title"],
        },
    },
]


def _search_pages(query: str, lang: str = "es", limit: int = 3) -> dict:
    lang = (lang or "es").strip() or "es"
    limit = max(1, min(int(limit or 3), 5))
    qs = urllib.parse.urlencode({"q": query, "limit": limit})
    url = f"https://api.wikimedia.org/core/v1/wikipedia/{urllib.parse.quote(lang)}/search/page?{qs}"
    data = _get_json(url)
    results = []
    for p in data.get("pages", []):
        results.append({
            "title": p.get("title"),
            "description": p.get("description"),
            "excerpt": p.get("excerpt"),
            "key": p.get("key"),
        })
    return {"query": query, "lang": lang, "results": results}


def _get_summary(title: str, lang: str = "es") -> dict:
    lang = (lang or "es").strip() or "es"
    t = urllib.parse.quote(title.strip().replace(" ", "_"), safe="")
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{t}"
    data = _get_json(url)
    return {
        "title": data.get("title"),
        "lang": lang,
        "description": data.get("description"),
        "extract": data.get("extract"),
        "url": (data.get("content_urls", {}) or {}).get("desktop", {}).get("page"),
    }


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
            "serverInfo": {"name": "wikipedia-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "search_pages":
                val = _search_pages(args.get("query", ""), args.get("lang", "es"), args.get("limit", 3))
            elif name == "get_summary":
                val = _get_summary(args.get("title", ""), args.get("lang", "es"))
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
