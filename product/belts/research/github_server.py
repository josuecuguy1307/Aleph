#!/usr/bin/env python3
"""
github_server.py — GitHub MCP server (stdio, JSON-RPC 2.0). Token BYOK, READ-ONLY.

Belt RESEARCH, leg "leer código/repos reales". Lee DE VERDAD contra la GitHub REST API
(https://api.github.com) con el PAT del usuario, inyectado por el broker al child_env como
${GITHUB_PERSONAL_ACCESS_TOKEN} (provider 'github' → alias GITHUB_PERSONAL_ACCESS_TOKEN /
GITHUB_TOKEN). Sólo stdlib (urllib).

Tools (TODAS lectura — v1 read-only; commits/escritura es follow-up con su gate):
  • github_whoami()                         → GET /user. Identidad de la cuenta del token.
  • github_list_repos(limit, sort)          → GET /user/repos. Tus repos (privados+públicos
                                              según el alcance del token), más recientes primero.
  • github_get_file(owner, repo, path, ref) → GET /repos/{o}/{r}/contents/{path}. Devuelve el
                                              contenido del archivo (decodifica base64, cap 200KB).
  • github_list_commits(owner, repo, limit, path) → GET .../commits. Commits recientes (sha,
                                              autor, fecha, mensaje).
  • github_search_repos(query, limit)       → GET /search/repositories. Busca repos públicos.

CREDENCIAL: si ${GITHUB_PERSONAL_ACCESS_TOKEN} no llegó, TODAS fallan CERRADO con
"missing_credential" — nunca inventan. Es el gate de credencial, honesto.

User-Agent OBLIGATORIO (GitHub 403ea sin él). Bearer acepta fine-grained (github_pat_) y
classic (ghp_). NO hay tools de escritura acá: leer repos es baja consecuencia.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

_BASE = "https://api.github.com"
_TIMEOUT = 25
_MAX_FILE_BYTES = 200_000


def _key() -> str:
    return (os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or os.environ.get("GITHUB_API_KEY") or "")


def _req(method: str, path: str, body: bytes | None = None) -> tuple[int, dict | list | str]:
    key = _key()
    if not key:
        return 0, {"error": "missing_credential",
                   "detail": "GITHUB_PERSONAL_ACCESS_TOKEN no inyectado — conecta GitHub (BYOK) antes de usar."}
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": "puppet-ai-toolbelt/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github+json",
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
    st, data = _req("GET", "/user")
    if st == 0:
        return data if isinstance(data, dict) else {"ok": False, "error": "unknown"}
    if st != 200 or not isinstance(data, dict):
        return {"ok": False, "status": st, "detail": data}
    return {
        "ok": True,
        "login": data.get("login"),
        "id": data.get("id"),
        "name": data.get("name"),
        "public_repos": data.get("public_repos"),
        "html_url": data.get("html_url"),
    }


def _list_repos(args: dict) -> dict:
    try:
        limit = max(1, min(int(args.get("limit", 20) or 20), 100))
    except Exception:
        limit = 20
    sort = args.get("sort", "updated")
    if sort not in ("updated", "created", "pushed", "full_name"):
        sort = "updated"
    st, data = _req("GET", f"/user/repos?per_page={limit}&sort={sort}")
    if st == 0:
        return {"ok": False, "stage": "get", "detail": data}
    if st != 200 or not isinstance(data, list):
        return {"ok": False, "status": st, "detail": data}
    repos = [{
        "full_name": r.get("full_name"),
        "private": r.get("private"),
        "description": r.get("description"),
        "default_branch": r.get("default_branch"),
        "language": r.get("language"),
        "pushed_at": r.get("pushed_at"),
        "html_url": r.get("html_url"),
    } for r in data if isinstance(r, dict)]
    return {"ok": True, "status": st, "count": len(repos), "repos": repos}


def _get_file(args: dict) -> dict:
    owner = (args.get("owner") or "").strip()
    repo = (args.get("repo") or "").strip()
    path = (args.get("path") or "").strip().lstrip("/")
    ref = (args.get("ref") or "").strip()
    if not owner or not repo or not path:
        return {"ok": False, "error": "bad_args", "detail": "owner, repo y path son obligatorios."}
    q = f"?ref={urllib.parse.quote(ref)}" if ref else ""
    st, data = _req("GET", f"/repos/{owner}/{repo}/contents/{urllib.parse.quote(path)}{q}")
    if st == 0:
        return {"ok": False, "stage": "get", "detail": data}
    if st != 200 or not isinstance(data, dict):
        return {"ok": False, "status": st, "detail": data}
    if data.get("type") != "file":
        return {"ok": False, "status": st, "error": "not_a_file",
                "detail": f"'{path}' es {data.get('type')} (usa un path de archivo)."}
    enc = data.get("encoding")
    content, truncated = None, False
    if enc == "base64" and data.get("content"):
        raw = base64.b64decode(data["content"])
        if len(raw) > _MAX_FILE_BYTES:
            raw, truncated = raw[:_MAX_FILE_BYTES], True
        content = raw.decode("utf-8", "replace")
    return {
        "ok": True, "status": st,
        "path": data.get("path"), "size": data.get("size"),
        "sha": data.get("sha"), "html_url": data.get("html_url"),
        "truncated": truncated, "content": content,
    }


def _list_commits(args: dict) -> dict:
    owner = (args.get("owner") or "").strip()
    repo = (args.get("repo") or "").strip()
    if not owner or not repo:
        return {"ok": False, "error": "bad_args", "detail": "owner y repo son obligatorios."}
    try:
        limit = max(1, min(int(args.get("limit", 10) or 10), 50))
    except Exception:
        limit = 10
    qp = {"per_page": str(limit)}
    if args.get("path"):
        qp["path"] = str(args["path"])
    if args.get("sha"):
        qp["sha"] = str(args["sha"])
    st, data = _req("GET", f"/repos/{owner}/{repo}/commits?{urllib.parse.urlencode(qp)}")
    if st == 0:
        return {"ok": False, "stage": "get", "detail": data}
    if st != 200 or not isinstance(data, list):
        return {"ok": False, "status": st, "detail": data}
    commits = []
    for c in data:
        if not isinstance(c, dict):
            continue
        commit = c.get("commit") or {}
        author = commit.get("author") or {}
        commits.append({
            "sha": (c.get("sha") or "")[:10],
            "author": author.get("name"),
            "date": author.get("date"),
            "message": (commit.get("message") or "").splitlines()[0][:200],
            "html_url": c.get("html_url"),
        })
    return {"ok": True, "status": st, "count": len(commits), "commits": commits}


def _search_repos(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "bad_args", "detail": "query es obligatorio."}
    try:
        limit = max(1, min(int(args.get("limit", 10) or 10), 30))
    except Exception:
        limit = 10
    qp = urllib.parse.urlencode({"q": query, "per_page": str(limit), "sort": "stars", "order": "desc"})
    st, data = _req("GET", f"/search/repositories?{qp}")
    if st == 0:
        return {"ok": False, "stage": "get", "detail": data}
    if st != 200 or not isinstance(data, dict):
        return {"ok": False, "status": st, "detail": data}
    items = [{
        "full_name": r.get("full_name"),
        "description": r.get("description"),
        "stars": r.get("stargazers_count"),
        "language": r.get("language"),
        "html_url": r.get("html_url"),
    } for r in (data.get("items") or []) if isinstance(r, dict)]
    return {"ok": True, "status": st, "total": data.get("total_count"), "count": len(items), "repos": items}


TOOLS = [
    {
        "name": "github_whoami",
        "description": "Verifica el token de GitHub y devuelve la identidad de la cuenta (login, id, name). Lectura, no escribe.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "github_list_repos",
        "description": (
            "Lista TUS repositorios de GitHub (los que el token puede ver), más recientes primero. "
            "Devuelve full_name (owner/repo), si es privado, descripción, lenguaje, rama default y "
            "último push. Usa esto para descubrir el owner/repo exactos antes de leer archivos."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "máximo de repos (1-100)."},
                "sort": {"type": "string", "default": "updated", "description": "updated|created|pushed|full_name."},
            },
            "required": [],
        },
    },
    {
        "name": "github_get_file",
        "description": (
            "Lee el contenido de UN archivo de un repo (decodifica texto, hasta 200KB). Pasa owner, "
            "repo y path (ej. 'src/main.py'); 'ref' opcional (rama/tag/sha, default la rama default)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string", "description": "ruta del archivo dentro del repo."},
                "ref": {"type": "string", "description": "rama/tag/sha opcional."},
            },
            "required": ["owner", "repo", "path"],
        },
    },
    {
        "name": "github_list_commits",
        "description": (
            "Trae los commits recientes de un repo (sha, autor, fecha, primera línea del mensaje). "
            "owner+repo obligatorios; 'path' opcional acota a los commits que tocaron ese archivo."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "limit": {"type": "integer", "default": 10, "description": "máximo de commits (1-50)."},
                "path": {"type": "string", "description": "acotar a commits que tocaron este archivo."},
                "sha": {"type": "string", "description": "rama o sha de inicio (opcional)."},
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "github_search_repos",
        "description": (
            "Busca repositorios públicos en GitHub por palabras clave / sintaxis de búsqueda de GitHub "
            "(ej. 'language:python topic:llm'). Devuelve full_name, descripción, estrellas y lenguaje."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10, "description": "máximo de resultados (1-30)."},
            },
            "required": ["query"],
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
            "serverInfo": {"name": "github-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "github_whoami":
                val = _whoami()
            elif name == "github_list_repos":
                val = _list_repos(args)
            elif name == "github_get_file":
                val = _get_file(args)
            elif name == "github_list_commits":
                val = _list_commits(args)
            elif name == "github_search_repos":
                val = _search_repos(args)
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
