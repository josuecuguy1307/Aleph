#!/usr/bin/env python3
"""
verify_drive_server_ticket9.py — el MCP server de Google Drive (bearer, gemelo de gmail) funciona
por el path real JSON-RPC, SIN cuenta real: un stub HTTP local emula la Drive REST v3.

Cubre: init + tools/list (3 tools) · search_files (lectura) · create_file (crea) · create_file
otra vez con el MISMO nombre (IDEMPOTENTE: no duplica) · read_file_content (Google Doc → export a
texto) · error honesto sin token. Confirma la inyección construir≠inyectar (GDRIVE_TOKEN).

Run: python qa/verify_drive_server_ticket9.py
"""
import json
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SERVER = _REPO / "product" / "belts" / "cowork" / "drive_server.py"

_fails = []
def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  · {detail}" if detail else ""))
    if not cond:
        _fails.append(name)

# ── STUB Drive REST v3 (en memoria) ──────────────────────────────────────────────
_FILES = {}          # id -> {"name","mimeType","content","app"}  (app=True si lo creó la app)
_next_id = {"n": 1}
_TOKEN = "stub-drive-bearer-xyz"


def _extract_quoted(q):
    # saca el primer '...' del query Drive (name = 'X' / name contains 'X')
    a = q.find("'")
    if a < 0:
        return ""
    b = q.find("'", a + 1)
    return q[a + 1:b] if b > a else ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _auth_ok(self):
        return self.headers.get("Authorization") == "Bearer " + _TOKEN

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _raw(self, code, data: bytes, ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._auth_ok():
            return self._json(401, {"error": {"message": "bad token"}})
        pr = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(pr.query)
        # listar/buscar
        if pr.path == "/drive/v3/files":
            q = (qs.get("q") or [""])[0]
            term = _extract_quoted(q).lower()
            # el server acota la idempotencia a archivos de la app: q trae "appProperties has {...}"
            app_only = "appproperties has" in q.lower()
            out = []
            for fid, f in _FILES.items():
                nm = f["name"].lower()
                if app_only and not f.get("app"):
                    continue
                if not term or term in nm:
                    out.append({"id": fid, "name": f["name"], "mimeType": f["mimeType"],
                                "modifiedTime": "2026-07-16T00:00:00Z", "size": str(len(f["content"]))})
            return self._json(200, {"files": out})
        # export google-doc → texto
        if pr.path.endswith("/export"):
            fid = pr.path.split("/")[4]
            f = _FILES.get(fid)
            if not f:
                return self._json(404, {"error": {"message": "no such file"}})
            return self._raw(200, f["content"].encode())
        # media (alt=media) o metadata
        if pr.path.startswith("/drive/v3/files/"):
            fid = pr.path.split("/")[4]
            f = _FILES.get(fid)
            if not f:
                return self._json(404, {"error": {"message": "no such file"}})
            if (qs.get("alt") or [""])[0] == "media":
                return self._raw(200, f["content"].encode())
            return self._json(200, {"id": fid, "name": f["name"], "mimeType": f["mimeType"],
                                    "modifiedTime": "2026-07-16T00:00:00Z", "size": str(len(f["content"]))})
        return self._json(404, {"error": {"message": "unhandled GET"}})

    def do_POST(self):
        if not self._auth_ok():
            return self._json(401, {"error": {"message": "bad token"}})
        pr = urllib.parse.urlparse(self.path)
        if pr.path == "/upload/drive/v3/files":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8", "replace")
            # parse multipart honrando la metadata JSON anidada (appProperties) — cortamos el bloque
            # JSON entre su content-type y el siguiente boundary, NO por la 1ra "}".
            name, is_app = "untitled", False
            mparts = body.split("application/json; charset=UTF-8\r\n\r\n")
            if len(mparts) > 1:
                meta_json = mparts[1].split("\r\n--")[0]
                try:
                    meta = json.loads(meta_json)
                    name = meta.get("name", name)
                    is_app = (meta.get("appProperties") or {}).get("puppet_created") == "1"
                except Exception:
                    pass
            content = ""
            parts = body.split("text/plain; charset=UTF-8\r\n\r\n")
            if len(parts) > 1:
                content = parts[-1].split("\r\n--")[0]
            fid = f"file-{_next_id['n']}"; _next_id["n"] += 1
            _FILES[fid] = {"name": name, "mimeType": "text/plain", "content": content, "app": is_app}
            return self._json(200, {"id": fid, "name": name, "mimeType": "text/plain"})
        return self._json(404, {"error": {"message": "unhandled POST"}})


def rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line) if line.strip() else {}


def tool_call(proc, rid, name, args):
    r = rpc(proc, {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                   "params": {"name": name, "arguments": args}})
    res = r.get("result", {})
    txt = (res.get("content") or [{}])[0].get("text", "")
    is_err = res.get("isError", False)
    try:
        return json.loads(txt), is_err
    except Exception:
        return txt, is_err


def main():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    # pre-seed un Google Doc para probar read_file_content (export a texto)
    _FILES["doc-seed"] = {"name": "Notas de reunión",
                          "mimeType": "application/vnd.google-apps.document",
                          "content": "línea 1 del doc\nlínea 2"}

    env = dict(os.environ, GDRIVE_TOKEN=_TOKEN, GDRIVE_API_BASE=base, PUPPET_LANG="es")
    proc = subprocess.Popen([sys.executable, str(_SERVER)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        ini = rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        check("initialize responde serverInfo drive-server",
              (ini.get("result", {}).get("serverInfo", {}).get("name")) == "drive-server", str(ini)[:120])

        lst = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = [t["name"] for t in lst.get("result", {}).get("tools", [])]
        check("tools/list expone las 3 tools",
              set(tools) == {"search_files", "read_file_content", "create_file"}, str(tools))

        # search (encuentra el doc pre-seed)
        s, err = tool_call(proc, 3, "search_files", {"query": "reunión"})
        check("search_files encuentra el doc pre-seed", (not err) and s.get("count", 0) >= 1, str(s)[:160])

        # create (nuevo)
        c1, err1 = tool_call(proc, 4, "create_file", {"name": "plan-q3.txt", "content": "objetivos Q3"})
        check("create_file crea (created=true)", (not err1) and c1.get("created") is True and c1.get("file_id"), str(c1)[:160])

        # create otra vez, MISMO nombre → idempotente (no duplica)
        c2, err2 = tool_call(proc, 5, "create_file", {"name": "plan-q3.txt", "content": "otra vez"})
        check("create_file idempotente (created=false, mismo id)",
              (not err2) and c2.get("created") is False and c2.get("idempotent") is True and c2.get("file_id") == c1.get("file_id"),
              str(c2)[:160])
        # y NO se duplicó en el store del stub
        plan_count = sum(1 for f in _FILES.values() if f["name"] == "plan-q3.txt")
        check("el stub NO tiene duplicado de plan-q3.txt", plan_count == 1, f"count={plan_count}")

        # read (google doc → export a texto)
        r, errr = tool_call(proc, 6, "read_file_content", {"file_id": "doc-seed"})
        check("read_file_content exporta el Google Doc a texto",
              (not errr) and "línea 1 del doc" in (r.get("content") or ""), str(r)[:160])

        # review F4 · un archivo PREVIO del usuario (NO de la app) con el mismo nombre NO dispara
        # el camino idempotente → create hace uno NUEVO de la app (no descarta el content ni filtra
        # el file_id ajeno).
        _FILES["user-owned"] = {"name": "reporte.txt", "mimeType": "text/plain",
                                "content": "documento privado del usuario", "app": False}
        c3, err3 = tool_call(proc, 7, "create_file", {"name": "reporte.txt", "content": "lo que armó el agente"})
        check("create_file NO colisiona con un archivo previo del usuario (F4)",
              (not err3) and c3.get("created") is True and c3.get("file_id") != "user-owned", str(c3)[:160])

        # review F9 · un archivo > _READ_CAP se RECORTA (y no revienta la RAM): el server lee a lo
        # sumo _READ_CAP+1 bytes. Verificamos truncated=True y contenido acotado.
        _READ_CAP = 200_000
        _FILES["huge"] = {"name": "backup.txt", "mimeType": "text/plain",
                          "content": "A" * (_READ_CAP + 5000), "app": True}
        rbig, errbig = tool_call(proc, 8, "read_file_content", {"file_id": "huge"})
        check("read_file_content recorta un archivo enorme (F9 · cap al leer)",
              (not errbig) and rbig.get("truncated") is True and len(rbig.get("content") or "") <= _READ_CAP,
              f"truncated={rbig.get('truncated')} len={len(rbig.get('content') or '')}")

        # error honesto sin token: reiniciar el server SIN GDRIVE_TOKEN
        env2 = dict(os.environ, GDRIVE_API_BASE=base, PUPPET_LANG="es")
        env2.pop("GDRIVE_TOKEN", None); env2.pop("GDRIVE_ACCESS_TOKEN", None); env2.pop("GOOGLE_DRIVE_TOKEN", None)
        p2 = subprocess.Popen([sys.executable, str(_SERVER)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env2)
        try:
            rpc(p2, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            e, eerr = tool_call(p2, 2, "search_files", {"query": "x"})
            check("sin GDRIVE_TOKEN → error honesto (no finge éxito)",
                  eerr is True and "credencial" in str(e).lower(), str(e)[:160])
        finally:
            p2.terminate()
    finally:
        proc.terminate()
        srv.shutdown()

    print()
    if _fails:
        print(f"══ ❌ {len(_fails)} CHECK(S) FALLARON: {_fails} ══\n")
        sys.exit(1)
    print("══ ✅ TODOS LOS CHECKS DEL DRIVE SERVER (ticket 9) PASARON ══\n")


if __name__ == "__main__":
    main()
