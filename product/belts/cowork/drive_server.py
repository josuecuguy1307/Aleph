#!/usr/bin/env python3
"""
drive_server.py — Google Drive MCP server (stdio, JSON-RPC 2.0) para el belt COWORK.

FAMILIA 3 (OAuth Connect), gemelo de gmail_draft_server.py: el usuario autoriza SU cuenta
de Drive por el botón "Conectar Google Drive"; el credential-broker (B4) guarda/renueva el
OAuth por end-user y el runtime inyecta el access-token como ${GDRIVE_TOKEN} al entorno de
ESTE subprocess. El server sólo consume un bearer — es agnóstico a cómo se obtuvo (OAuth o
pegado). Multi-usuario por construcción; jamás la cuenta de dev.

SCOPES QUE ASUME (los que pide el descriptor google_drive.json):
  • drive.readonly → search_files / read_file_content ven TODO el Drive del usuario.
  • drive.file     → create_file crea SÓLO archivos que esta app creó (no toca los previos
                     del usuario). Crear un doc ≠ enviar/compartir: baja consecuencia
                     (FASE0 §7, cowork.md §2). NO existe share/invite acá — compartir pasaría
                     por el send-gate y no se cabla en este server.

IDEMPOTENCIA (bar: re-correr NO duplica el archivo)
  create_file: busca por nombre EXACTO (name = 'X' and trashed = false); si ya existe uno,
  lo devuelve con created=false en vez de crear otro. (Mismo contrato que create_draft.)

CONFIG (entorno)
  GDRIVE_TOKEN    (o GOOGLE_DRIVE_TOKEN / GDRIVE_ACCESS_TOKEN) — bearer OAuth (inyectado BYOK).
  GDRIVE_API_BASE (opcional) — default https://www.googleapis.com. Apuntalo a un stub local
                               para verificar el flujo SIN cuenta real.
"""

import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 25
_DEFAULT_BASE = "https://www.googleapis.com"
_READ_CAP = 200_000  # tope de bytes de contenido devuelto (no volcamos archivos enormes al LLM)

# [i18n-bi] bilingüe server-side (PUPPET_LANG, default es; no-op hasta que el runtime lo
# setee). Mismo patrón que gmail_draft_server.py.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
DRIVE_I18N = {
    "es": {
        "err.no_token": ("no hay credencial de Google Drive en el entorno del server (GDRIVE_TOKEN "
                         "ausente o sin expandir): la BYOK/OAuth no se inyectó. Conecta Google Drive "
                         "(Familia 3) y verifica la inyección (construir≠inyectar)."),
        "err.rejected": "Google Drive rechazó la credencial (%s): %s.",
        "err.api": "Google Drive API %s: %s",
        "err.unreachable": "no pude alcanzar Google Drive (%s): %s",
        "err.create_needs": "create_file necesita 'name'",
        "err.read_needs": "read_file_content necesita 'file_id'",
        "err.unknown_tool": "tool desconocida: %s",
        "note.idempotent": "ya existía un archivo con ese nombre — no se duplicó",
        "note.created": "archivo creado en tu Drive (privado — NO se compartió con nadie)",
        "note.truncated": "contenido recortado al tope de lectura",
        "tool.search.desc": "Busca archivos en tu Google Drive por nombre o texto. Sólo lectura.",
        "tool.read.desc": ("Lee el contenido de un archivo de tu Drive (los Google Docs se exportan a "
                           "texto plano). Sólo lectura."),
        "tool.create.desc": ("Crea un archivo de texto NUEVO en tu Drive (privado, no lo comparte). "
                             "Idempotente: si ya hay uno con el mismo nombre, no crea otro. Crear un "
                             "archivo no es enviarlo ni compartirlo."),
        "p.query": "Texto o nombre a buscar.",
        "p.file_id": "ID del archivo de Drive.",
        "p.name": "Nombre del archivo a crear.",
        "p.content": "Contenido de texto del archivo.",
    },
    "en": {
        "err.no_token": ("no Google Drive credential in the server environment (GDRIVE_TOKEN missing "
                         "or unexpanded): the BYOK/OAuth was not injected. Connect Google Drive "
                         "(Family 3) and verify the injection (build≠inject)."),
        "err.rejected": "Google Drive rejected the credential (%s): %s.",
        "err.api": "Google Drive API %s: %s",
        "err.unreachable": "could not reach Google Drive (%s): %s",
        "err.create_needs": "create_file needs 'name'",
        "err.read_needs": "read_file_content needs 'file_id'",
        "err.unknown_tool": "unknown tool: %s",
        "note.idempotent": "a file with that name already existed — not duplicated",
        "note.created": "file created in your Drive (private — NOT shared with anyone)",
        "note.truncated": "content truncated at the read cap",
        "tool.search.desc": "Search files in your Google Drive by name or text. Read-only.",
        "tool.read.desc": ("Read the content of a file in your Drive (Google Docs are exported to plain "
                           "text). Read-only."),
        "tool.create.desc": ("Create a NEW text file in your Drive (private, does not share it). "
                             "Idempotent: if one with the same name already exists, it does not create "
                             "another. Creating a file is not sending or sharing it."),
        "p.query": "Text or name to search for.",
        "p.file_id": "Drive file ID.",
        "p.name": "Name of the file to create.",
        "p.content": "Text content of the file.",
    },
}


def _t(key):
    return DRIVE_I18N.get(PUPPET_LANG, {}).get(key) or DRIVE_I18N["es"].get(key) or key


def _token() -> str:
    for var in ("GDRIVE_TOKEN", "GOOGLE_DRIVE_TOKEN", "GDRIVE_ACCESS_TOKEN", "GDRIVE_API_KEY"):
        val = (os.environ.get(var) or "").strip()
        if val and not val.startswith("${"):
            return val
    return ""


def _base() -> str:
    b = (os.environ.get("GDRIVE_API_BASE") or "").strip()
    if not b or b.startswith("${"):
        return _DEFAULT_BASE
    return b.rstrip("/")


class DriveError(Exception):
    pass


def _request(method: str, path: str, body: dict | None = None, *, raw_out: bool = False):
    token = _token()
    if not token:
        raise DriveError(_t("err.no_token"))
    url = _base() + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Bearer " + token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            if raw_out:
                # review F9 · CAP AL LEER, no después: r.read() sin límite metería un archivo de
                # 3 GB entero a RAM antes del tope → OOM/DoS. Leemos a lo sumo _READ_CAP+1 bytes
                # (el +1 deja detectar que hubo recorte). _read_file_content marca truncated.
                return r.read(_READ_CAP + 1)
            raw = r.read()
            text = raw.decode("utf-8", errors="replace")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
            msg = (err.get("error") or {}).get("message") if isinstance(err.get("error"), dict) else err.get("error", raw)
        except json.JSONDecodeError:
            msg = raw
        if e.code in (401, 403):
            raise DriveError(_t("err.rejected") % (e.code, msg))
        raise DriveError(_t("err.api") % (e.code, msg))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DriveError(_t("err.unreachable") % (_base(), e))


def _search_files(query: str = "", page_size: int = 20) -> dict:
    q_parts = ["trashed = false"]
    query = (query or "").strip()
    if query:
        # fullText cubre nombre + contenido; escapamos comillas simples del literal Drive.
        esc = query.replace("\\", "\\\\").replace("'", "\\'")
        q_parts.append(f"(name contains '{esc}' or fullText contains '{esc}')")
    q = urllib.parse.quote(" and ".join(q_parts))
    fields = urllib.parse.quote("files(id,name,mimeType,modifiedTime,size,owners(displayName))")
    ps = max(1, min(int(page_size or 20), 100))
    out = _request("GET", f"/drive/v3/files?q={q}&fields={fields}&pageSize={ps}")
    files = []
    for f in (out.get("files") or []):
        files.append({"id": f.get("id"), "name": f.get("name"),
                      "mimeType": f.get("mimeType"), "modifiedTime": f.get("modifiedTime"),
                      "size": f.get("size")})
    return {"files": files, "count": len(files)}


def _read_file_content(file_id: str) -> dict:
    file_id = (file_id or "").strip()
    if not file_id:
        raise DriveError(_t("err.read_needs"))
    fid = urllib.parse.quote(file_id, safe="")
    meta = _request("GET", f"/drive/v3/files/{fid}?fields=id,name,mimeType,modifiedTime,size")
    mime = meta.get("mimeType") or ""
    truncated = False
    if mime.startswith("application/vnd.google-apps."):
        # Google Docs/Sheets/Slides no tienen bytes crudos: se EXPORTAN. Texto plano cubre docs.
        export_mime = "text/plain"
        if "spreadsheet" in mime:
            export_mime = "text/csv"
        raw = _request("GET", f"/drive/v3/files/{fid}/export?mimeType={urllib.parse.quote(export_mime)}",
                       raw_out=True)
    else:
        raw = _request("GET", f"/drive/v3/files/{fid}?alt=media", raw_out=True)
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > _READ_CAP:
            raw = raw[:_READ_CAP]
            truncated = True
        content = raw.decode("utf-8", errors="replace")
    else:
        content = str(raw)
    out = {"id": meta.get("id"), "name": meta.get("name"), "mimeType": mime,
           "content": content, "truncated": truncated}
    if truncated:
        out["note"] = _t("note.truncated")
    return out


# review F4 · marcador appProperties: la idempotencia se acota a archivos que ESTA app creó.
# Con drive.readonly el server ve TODO el Drive; sin este filtro, un archivo PREVIO del usuario
# con el mismo nombre dispararía el camino "ya existía" (descarta el content nuevo y devuelve un
# file_id ajeno). appProperties es privado por-app (otras apps no lo ven).
_APP_MARK_KEY = "puppet_created"
_APP_MARK_VAL = "1"


def _find_existing_by_name(name: str) -> dict | None:
    esc = (name or "").replace("\\", "\\\\").replace("'", "\\'")
    # SÓLO archivos creados por esta app (appProperties has {...}), no todo el Drive del usuario.
    q = urllib.parse.quote(
        f"name = '{esc}' and trashed = false and "
        f"appProperties has {{ key='{_APP_MARK_KEY}' and value='{_APP_MARK_VAL}' }}")
    fields = urllib.parse.quote("files(id,name,mimeType,modifiedTime)")
    out = _request("GET", f"/drive/v3/files?q={q}&fields={fields}&pageSize=1")
    files = out.get("files") or []
    if files:
        f = files[0]
        return {"file_id": f.get("id"), "name": f.get("name")}
    return None


def _create_file(name: str, content: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise DriveError(_t("err.create_needs"))
    existing = _find_existing_by_name(name)
    if existing:
        return {**existing, "created": False, "idempotent": True, "note": _t("note.idempotent")}
    content = content or ""
    # Metadata: nombra el archivo Y lo marca como creado-por-esta-app (para la idempotencia F4).
    meta = json.dumps({"name": name, "appProperties": {_APP_MARK_KEY: _APP_MARK_VAL}})
    # review F3 · BOUNDARY ALEATORIO por request + verificación de colisión: un boundary fijo con
    # el content interpolado crudo dejaba que un content con "--<boundary>--" cerrara la parte media
    # antes de tiempo (trunca el archivo, o inyecta una parte de metadata). Regeneramos hasta que el
    # delimitador NO aparezca en metadata ni content.
    for _ in range(8):
        boundary = "puppetdrive-" + secrets.token_hex(16)
        if boundary not in meta and boundary not in content:
            break
    else:
        raise DriveError("no pude generar un límite multipart seguro para este contenido")
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    token = _token()
    if not token:
        raise DriveError(_t("err.no_token"))
    url = _base() + "/upload/drive/v3/files?uploadType=multipart&fields=id,name,mimeType"
    headers = {"Authorization": "Bearer " + token,
               "Content-Type": f"multipart/related; boundary={boundary}"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            raw = r.read().decode("utf-8", errors="replace")
            out = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
            msg = (err.get("error") or {}).get("message") if isinstance(err.get("error"), dict) else err.get("error", raw)
        except json.JSONDecodeError:
            msg = raw
        if e.code in (401, 403):
            raise DriveError(_t("err.rejected") % (e.code, msg))
        raise DriveError(_t("err.api") % (e.code, msg))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DriveError(_t("err.unreachable") % (_base(), e))
    return {"file_id": out.get("id"), "name": out.get("name") or name,
            "mimeType": out.get("mimeType"), "created": True, "idempotent": False,
            "note": _t("note.created")}


TOOLS = [
    {
        "name": "search_files",
        "description": _t("tool.search.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": _t("p.query")}},
        },
    },
    {
        "name": "read_file_content",
        "description": _t("tool.read.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {"file_id": {"type": "string", "description": _t("p.file_id")}},
            "required": ["file_id"],
        },
    },
    {
        "name": "create_file",
        "description": _t("tool.create.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": _t("p.name")},
                "content": {"type": "string", "description": _t("p.content")},
            },
            "required": ["name"],
        },
    },
]

_DISPATCH = {
    "search_files": lambda a: _search_files(a.get("query", ""), a.get("page_size", 20)),
    "read_file_content": lambda a: _read_file_content(a.get("file_id", "")),
    "create_file": lambda a: _create_file(a.get("name", ""), a.get("content", "")),
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
            "serverInfo": {"name": "drive-server", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            fn = _DISPATCH.get(name)
            if fn is None:
                raise DriveError(_t("err.unknown_tool") % name)
            val = fn(args)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": False,
            }})
        except Exception as exc:  # noqa: BLE001
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
