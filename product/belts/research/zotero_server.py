#!/usr/bin/env python3
"""
zotero_server.py — Zotero MCP server (stdio, JSON-RPC 2.0). Token BYOK.

Belt RESEARCH, leg "persistir la cita en TU biblioteca". Escribe DE VERDAD contra la
Zotero Web API (https://api.zotero.org) usando la llave personal del usuario, inyectada
por el broker al child_env como ${ZOTERO_API_KEY} (provider 'zotero' → canónico
ZOTERO_API_KEY). Sólo stdlib (urllib).

Tools:
  • whoami()                         → GET /keys/current. LECTURA. Deriva userID+username
                                       de la llave (el wizard NO pide el userID aparte).
  • create_item(...)                 → POST /users/{userID}/items. ESCRIBE una referencia
                                       (journalArticle) en la biblioteca. Devuelve la KEY
                                       real que asigna Zotero (prueba de que escribió).

CREDENCIAL: si ${ZOTERO_API_KEY} no llegó (no hay token de la cuenta de juguete), AMBAS
tools fallan CERRADO con un mensaje claro ("missing_credential") — nunca inventan un
resultado. Sin token no hay escritura: es el gate de credencial, honesto.

El nombre `create_item` no es un verbo money/send → el enforcer de gates lo deja
auto-ejecutar. Escribir add-only en TU propia biblioteca de juguete es baja consecuencia
(no es plata, no es envío externo, no borra). Aislamiento: la cuenta es de juguete.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

_BASE = "https://api.zotero.org"
_TIMEOUT = 25
_API_VERSION = "3"


def _key() -> str:
    """La key BYOK, o "" si no llegó.

    UNA sola variable: `ZOTERO_API_KEY`. Había un fallback a `ZOTERO_TOKEN` y se midió que
    NADIE lo escribía — ni el broker (`_PROVIDER_ENV_ALIASES` no tiene entrada 'zotero', así
    que `_provider_env_vars` devuelve sólo el canónico), ni un belt, ni un fixture, ni un
    test: la única aparición de ese nombre en todo el árbol era esta línea. Un fallback que
    nadie puebla no es tolerancia, es una variable no declarada más en la receta.

    El `${` es el literal SIN EXPANDIR: si el belt declara `${ZOTERO_API_KEY}` y el broker no
    resolvió la credencial, `_expand_str` deja el texto tal cual (semántica de expandvars) y
    el hijo recibe la cadena literal. Tomarla por una llave manda basura a la API y convierte
    un «falta credencial» honesto en un 403 confuso. Mismo guard que gmail/drive."""
    v = (os.environ.get("ZOTERO_API_KEY") or "").strip()
    return "" if v.startswith("${") else v


def _req(method: str, path: str, body: bytes | None = None) -> tuple[int, dict | list | str]:
    key = _key()
    if not key:
        return 0, {"error": "missing_credential",
                   "detail": "ZOTERO_API_KEY no inyectada — conecta la cuenta (BYOK) antes de escribir."}
    headers = {
        "Zotero-API-Key": key,
        "Zotero-API-Version": _API_VERSION,
        "Accept": "application/json",
        "User-Agent": "puppet-ai-toolbelt/0.1",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(_BASE + path, data=body, headers=headers, method=method)
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


def _whoami() -> dict:
    st, data = _req("GET", "/keys/current")
    if st == 0:
        return data if isinstance(data, dict) else {"error": "unknown"}
    if st != 200 or not isinstance(data, dict):
        return {"ok": False, "status": st, "detail": data}
    return {
        "ok": True,
        "userID": data.get("userID"),
        "username": data.get("username"),
        "access": data.get("access"),
    }


def _creators_from_authors(authors) -> list:
    creators = []
    for a in (authors or []):
        if isinstance(a, dict):
            given, family = a.get("given", ""), a.get("family", "")
        else:
            parts = str(a).strip().rsplit(" ", 1)
            if len(parts) == 2:
                given, family = parts[0], parts[1]
            else:
                given, family = "", parts[0]
        if given or family:
            creators.append({"creatorType": "author", "firstName": given, "lastName": family})
    return creators


def _create_item(args: dict) -> dict:
    # 1) derivar userID de la llave (whoami)
    who = _whoami()
    if not who.get("ok"):
        return {"ok": False, "stage": "whoami", "detail": who}
    user_id = who.get("userID")

    # 2) armar el item journalArticle desde los metadatos (que vienen de Crossref REAL)
    item = {
        "itemType": args.get("item_type", "journalArticle"),
        "title": args.get("title", ""),
        "creators": _creators_from_authors(args.get("authors")),
        "DOI": args.get("doi", ""),
        "url": args.get("url", ""),
        "publicationTitle": args.get("container", ""),
        "date": str(args.get("year", "") or ""),
        "abstractNote": args.get("abstract", ""),
        "extra": args.get("extra", ""),
    }
    # tags opcionales (p.ej. para aislar la data de juguete de este run)
    tags = args.get("tags") or []
    if tags:
        item["tags"] = [{"tag": str(t)} for t in tags]

    body = json.dumps([item]).encode("utf-8")
    st, data = _req("POST", f"/users/{user_id}/items", body=body)
    if st == 0:
        return {"ok": False, "stage": "post", "detail": data}
    # Zotero 200: {"successful": {"0": {...,"key": "ABCD"}}, "success": {"0":"ABCD"}, "failed": {}}
    ok = isinstance(data, dict) and bool(data.get("successful") or data.get("success"))
    new_key = None
    library = None
    if isinstance(data, dict):
        succ = data.get("successful") or {}
        if isinstance(succ, dict) and succ:
            first = next(iter(succ.values()))
            if isinstance(first, dict):
                new_key = first.get("key")
                library = (first.get("library") or {}).get("id")
        if not new_key:
            s2 = data.get("success") or {}
            if isinstance(s2, dict) and s2:
                new_key = next(iter(s2.values()))
    # READ-BACK: re-leemos NUESTRO propio write para confirmar que el item está realmente
    # ahí (no "guardado" a ciegas). El recibo se para sobre esto, no sobre la afirmación del POST.
    readback_ok, readback_title = False, None
    if ok and new_key:
        rst, rdata = _req("GET", f"/users/{user_id}/items/{new_key}")
        if rst == 200 and isinstance(rdata, dict):
            readback_ok = True
            readback_title = (rdata.get("data") or {}).get("title")
    return {
        "ok": ok,
        "status": st,
        "userID": user_id,
        "item_key": new_key,
        "library_id": library,
        "web_url": f"https://www.zotero.org/{who.get('username')}/items/{new_key}" if new_key and who.get("username") else None,
        "readback_ok": readback_ok,            # confirmado por re-lectura
        "readback_title": readback_title,
        "failed": data.get("failed") if isinstance(data, dict) else None,
        "title_written": item["title"],
        "doi_written": item["DOI"],
    }


def _list_items(args: dict) -> dict:
    """LECTURA real: trae los items de TU biblioteca (GET /users/{userID}/items). Devuelve
    títulos/DOIs reales de tu cuenta — no mock. Falla cerrado sin credencial."""
    who = _whoami()
    if not who.get("ok"):
        return {"ok": False, "stage": "whoami", "detail": who}
    user_id = who.get("userID")
    try:
        limit = max(1, min(int(args.get("limit", 10) or 10), 50))
    except Exception:
        limit = 10
    st, data = _req("GET", f"/users/{user_id}/items?limit={limit}&format=json")
    if st == 0:
        return {"ok": False, "stage": "get", "detail": data}
    if st != 200 or not isinstance(data, list):
        return {"ok": False, "status": st, "detail": data}
    items = []
    for it in data:
        d = (it or {}).get("data", {}) if isinstance(it, dict) else {}
        items.append({
            "key": (it or {}).get("key"),
            "title": d.get("title") or d.get("note") or "(sin título)",
            "itemType": d.get("itemType"),
            "DOI": d.get("DOI") or "",
            "date": d.get("date") or "",
        })
    return {"ok": True, "status": st, "userID": user_id, "count": len(items), "items": items}


TOOLS = [
    {
        "name": "whoami",
        "description": "Verifica la llave de Zotero y devuelve el userID y username de la cuenta (lectura, sin escribir).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_items",
        "description": (
            "Trae los items REALES de tu biblioteca de Zotero (lectura, GET). Devuelve título, "
            "DOI, tipo y key de cada uno. Usa `limit` para acotar (default 10). Nada de mocks: "
            "son las referencias que están de verdad en tu cuenta."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10, "description": "máximo de items a traer (1-50)."}},
            "required": [],
        },
    },
    {
        "name": "create_item",
        "description": (
            "Guarda UNA referencia académica (journalArticle) en tu biblioteca de Zotero. "
            "Pasa los metadatos EXACTOS que devolvió la herramienta de búsqueda (Crossref): "
            "title, doi, authors (lista 'Nombre Apellido'), year, container (revista), url. "
            "Devuelve la KEY que Zotero le asigna (prueba de que se escribió)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "doi": {"type": "string"},
                "authors": {"type": "array", "items": {"type": "string"}},
                "year": {"type": "integer"},
                "container": {"type": "string", "description": "Revista/journal."},
                "url": {"type": "string"},
                "abstract": {"type": "string"},
                "item_type": {"type": "string", "default": "journalArticle"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "doi"],
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
            "serverInfo": {"name": "zotero-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "whoami":
                val = _whoami()
            elif name == "list_items":
                val = _list_items(args)
            elif name == "create_item":
                val = _create_item(args)
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
