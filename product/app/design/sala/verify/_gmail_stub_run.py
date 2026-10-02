#!/usr/bin/env python3
"""_gmail_stub_run.py — corre el stub de la API de Gmail (fixture del belt cowork) como
proceso standalone para el caso N2, + un endpoint de ESTADO para asserts cross-proceso.

El stub exige el bearer EXACTO (prueba la inyección BYOK real) y cuenta /messages/send:
send_count DEBE quedar en 0 — si sube, el gate dejó salir un correo.

Uso:  python3 _gmail_stub_run.py <token_dummy>
Escribe {base_url, state_url} en .gmail_stub.json (junto a este archivo) y sirve hasta SIGTERM.
El backend del caso debe bootear con GMAIL_API_BASE=<base_url>.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[4]
sys.path.insert(0, str(_REPO / "platform" / "belts" / "cowork" / "fixtures"))
import gmail_stub  # noqa: E402

TOKEN = sys.argv[1] if len(sys.argv) > 1 else "ya29.DUMMY_sala_n2"

state, base_url, _shutdown = gmail_stub.start_stub(TOKEN)


class StateHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({
            "drafts": len(state.gmail_drafts),
            "draft_list": [{"id": k, **v} for k, v in state.gmail_drafts.items()],
            "send_count": state.send_count,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


st_srv = ThreadingHTTPServer(("127.0.0.1", 0), StateHandler)
state_url = f"http://127.0.0.1:{st_srv.server_address[1]}"
threading.Thread(target=st_srv.serve_forever, daemon=True).start()

out = {"base_url": base_url, "state_url": state_url, "pid": os.getpid()}
(_THIS / ".gmail_stub.json").write_text(json.dumps(out))
print(json.dumps(out), flush=True)

try:
    threading.Event().wait()
except KeyboardInterrupt:
    pass
