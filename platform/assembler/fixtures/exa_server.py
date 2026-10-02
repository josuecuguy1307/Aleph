#!/usr/bin/env python3
"""
exa_server.py — Exa (web search) MCP server (stdio, JSON-RPC 2.0). API key BYOK.

Belt RESEARCH, leg "buscar en la WEB abierta" (complementa la literatura académica:
Crossref/arXiv/PubMed cubren papers; Exa cubre el resto de la web con búsqueda neural).
Pega DE VERDAD contra https://api.exa.ai con la key del usuario, inyectada por el broker
al child_env como ${EXA_API_KEY} (provider 'exa' → alias EXA_API_KEY). Sólo stdlib (urllib).

Tools:
  • exa_search(query, num_results, type, include_text) → POST /search. Búsqueda web real;
                                              devuelve título, url, fecha, autor y (opcional)
                                              un extracto del texto de cada resultado.
  • exa_get_contents(urls, max_chars)        → POST /contents. Trae el texto completo (o
                                              acotado) de URLs específicas (las que devolvió
                                              search, o cualquier URL).

CREDENCIAL: si ${EXA_API_KEY} no llegó, AMBAS fallan CERRADO con "missing_credential" —
nunca inventan un resultado. Exa cobra por búsqueda; el `costDollars` real se devuelve para
que el costo sea visible y honesto.
"""

import json
import os
import sys
import urllib.error
import urllib.request

_BASE = "https://api.exa.ai"
_TIMEOUT = 30


def _key() -> str:
    return os.environ.get("EXA_API_KEY") or os.environ.get("EXA_TOKEN") or ""


def _post(path: str, payload: dict) -> tuple[int, dict | list | str]:
    key = _key()
    if not key:
        return 0, {"error": "missing_credential",
                   "detail": "EXA_API_KEY no inyectada — conectá Exa (BYOK) antes de buscar."}
    headers = {
        "x-api-key": key,
        "Content-Type": "application/json",
        "User-Agent": "puppet-ai-toolbelt/0.1",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(_BASE + path, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return e.code, parsed
    except urllib.error.URLError as e:
        return 0, {"error": "network", "detail": str(e.reason)}


def _fmt_results(data: dict, want_text: bool) -> list:
    out = []
    for r in (data.get("results") or []):
        if not isinstance(r, dict):
            continue
        item = {
            "title": r.get("title"),
            "url": r.get("url"),
            "published_date": r.get("publishedDate"),
            "author": r.get("author"),
        }
        if want_text and r.get("text"):
            txt = r["text"]
            item["text"] = txt if len(txt) <= 4000 else txt[:4000] + "…"
        out.append(item)
    return out


def _search(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "bad_args", "detail": "query es obligatorio."}
    try:
        n = max(1, min(int(args.get("num_results", 5) or 5), 20))
    except Exception:
        n = 5
    typ = args.get("type", "auto")
    if typ not in ("auto", "neural", "keyword", "fast"):
        typ = "auto"
    include_text = bool(args.get("include_text", True))
    payload: dict = {"query": query, "numResults": n, "type": typ}
    if include_text:
        payload["contents"] = {"text": {"maxCharacters": 2000}}
    st, data = _post("/search", payload)
    if st == 0:
        return {"ok": False, "stage": "post", "detail": data}
    if st != 200 or not isinstance(data, dict):
        return {"ok": False, "status": st, "detail": data}
    return {
        "ok": True, "status": st,
        "results": _fmt_results(data, include_text),
        "cost_dollars": (data.get("costDollars") or {}).get("total"),
    }


def _get_contents(args: dict) -> dict:
    urls = args.get("urls") or args.get("ids") or []
    if isinstance(urls, str):
        urls = [urls]
    urls = [str(u).strip() for u in urls if str(u).strip()]
    if not urls:
        return {"ok": False, "error": "bad_args", "detail": "pasá al menos una URL en 'urls'."}
    try:
        max_chars = max(200, min(int(args.get("max_chars", 4000) or 4000), 12000))
    except Exception:
        max_chars = 4000
    st, data = _post("/contents", {"ids": urls, "text": {"maxCharacters": max_chars}})
    if st == 0:
        return {"ok": False, "stage": "post", "detail": data}
    if st != 200 or not isinstance(data, dict):
        return {"ok": False, "status": st, "detail": data}
    docs = []
    for r in (data.get("results") or []):
        if not isinstance(r, dict):
            continue
        docs.append({
            "url": r.get("url"),
            "title": r.get("title"),
            "text": r.get("text"),
        })
    return {"ok": True, "status": st, "count": len(docs), "documents": docs,
            "cost_dollars": (data.get("costDollars") or {}).get("total")}


TOOLS = [
    {
        "name": "exa_search",
        "description": (
            "Busca en la WEB abierta con Exa (búsqueda neural). Para fuentes que NO son papers "
            "académicos (blogs, docs, noticias, repos, sitios). Devuelve título, url, fecha y un "
            "extracto del texto de cada resultado. Usá `num_results` para acotar (default 5). Para "
            "literatura científica usá las tools académicas (Crossref/arXiv/PubMed), no esta."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer", "default": 5, "description": "máximo de resultados (1-20)."},
                "type": {"type": "string", "default": "auto", "description": "auto|neural|keyword|fast."},
                "include_text": {"type": "boolean", "default": True, "description": "incluir extracto del texto."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "exa_get_contents",
        "description": (
            "Trae el texto de URLs específicas (las que devolvió exa_search, o cualquier URL). Útil "
            "para leer una página a fondo antes de citarla. `max_chars` acota el largo (default 4000)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "lista de URLs a leer."},
                "max_chars": {"type": "integer", "default": 4000, "description": "máximo de caracteres por doc (200-12000)."},
            },
            "required": ["urls"],
        },
    },
]


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
            "serverInfo": {"name": "exa-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "exa_search":
                val = _search(args)
            elif name == "exa_get_contents":
                val = _get_contents(args)
            else:
                raise ValueError(f"unknown tool {name}")
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": not bool(val.get("ok", False)),
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
