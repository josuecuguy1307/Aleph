#!/usr/bin/env python3
"""
gmail_stub.py — stub HTTP local de la API de Gmail (drafts + send).

PARA QUÉ: verificar la mitad GMAIL del belt COWORK SIN cuenta real. Imita las formas
reales de la API de Gmail y HACE CUMPLIR la auth: exige el `Authorization: Bearer <token>`
correcto y devuelve 401 si no llega → detector del invariante "construir≠inyectar".

Estado expuesto para aserciones (objeto `State`):
  - gmail_bearer_seen : el último bearer que llegó (prueba que la BYOK se inyectó de verdad).
  - gmail_drafts      : {draft_id: {to, subject, body}}
  - send_count        : cuántas veces se invocó /messages/send. DEBE quedar en 0: el gate
                        detiene send_email; si sube, el correo SALIÓ → fallo de gate.

Solo stdlib. Threading server; arrancalo en un hilo desde el harness.
"""

from __future__ import annotations

import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class State:
    def __init__(self, gmail_token: str):
        self.gmail_token = gmail_token
        self.gmail_bearer_seen: str | None = None
        self._d = 0
        self.send_count = 0
        self.lock = threading.Lock()
        self.gmail_drafts: dict[str, dict] = {}

    def next_draft_id(self) -> str:
        self._d += 1
        return f"draft{self._d:04d}"


def _b64url_decode(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii")).decode("utf-8", errors="replace")


def _parse_rfc822(text: str) -> tuple[str, str, str]:
    to = subject = ""
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines) and lines[i].strip():
        line = lines[i]
        if line.lower().startswith("to:"):
            to = line.split(":", 1)[1].strip()
        elif line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
        i += 1
    body = "\n".join(lines[i + 1:]) if i < len(lines) else ""
    return to, subject, body.strip()


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silencio
            return

        def _bearer(self) -> str:
            auth = self.headers.get("Authorization", "")
            return auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""

        def _json(self, code: int, obj: dict):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def _auth_ok(self) -> bool:
            tok = self._bearer()
            with state.lock:
                state.gmail_bearer_seen = tok
            if tok and tok == state.gmail_token:
                return True
            self._json(401, {"error": {"code": 401, "status": "UNAUTHENTICATED",
                                       "message": "stub: bearer ausente o incorrecto"}})
            return False

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if not path.startswith("/gmail/"):
                return self._json(404, {"message": "not found"})
            if not self._auth_ok():
                return
            if re.match(r"^/gmail/v1/users/[^/]+/drafts$", path):
                drafts = [{"id": did, "message": {"id": f"msg_{did}"}} for did in state.gmail_drafts]
                return self._json(200, {"drafts": drafts, "resultSizeEstimate": len(drafts)})
            m = re.match(r"^/gmail/v1/users/[^/]+/drafts/([^/]+)$", path)
            if m:
                did = m.group(1)
                d = state.gmail_drafts.get(did)
                if not d:
                    return self._json(404, {"error": {"code": 404, "message": "draft not found"}})
                return self._json(200, {"id": did, "message": {
                    "id": f"msg_{did}",
                    "payload": {"headers": [
                        {"name": "To", "value": d["to"]},
                        {"name": "Subject", "value": d["subject"]},
                    ]},
                }})
            return self._json(404, {"error": {"code": 404, "message": "unknown gmail path"}})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not path.startswith("/gmail/"):
                return self._json(404, {"message": "not found"})
            if not self._auth_ok():
                return
            body = self._read_body()
            if path.endswith("/drafts"):
                raw = ((body.get("message") or {}).get("raw")) or ""
                to, subject, text = _parse_rfc822(_b64url_decode(raw)) if raw else ("", "", "")
                with state.lock:
                    did = state.next_draft_id()
                    state.gmail_drafts[did] = {"to": to, "subject": subject, "body": text}
                return self._json(200, {"id": did, "message": {"id": f"msg_{did}"}})
            if re.match(r"^/gmail/v1/users/[^/]+/messages/send$", path):
                # ¡ESTO NO DEBERÍA OCURRIR! El gate detiene send_email. Si llegó acá, el
                # correo SALIÓ → fallo de gate. Lo contamos para que el harness lo cace.
                with state.lock:
                    state.send_count += 1
                return self._json(200, {"id": "SENT_should_not_happen", "labelIds": ["SENT"]})
            return self._json(404, {"message": "unknown post path"})

    return Handler


def start_stub(gmail_token: str, *, host: str = "127.0.0.1", port: int = 0):
    """Arranca el stub en un hilo. Devuelve (state, base_url, shutdown_fn)."""
    state = State(gmail_token)
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    actual_port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    def shutdown():
        httpd.shutdown()
        httpd.server_close()

    return state, f"http://{host}:{actual_port}", shutdown
