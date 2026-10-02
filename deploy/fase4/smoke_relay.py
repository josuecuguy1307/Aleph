"""smoke_relay.py — SMOKE del puente cliente→control. [Casa 2 · Fase 4 · 4.2.d.0 + relay]

De-riesga las 2 mecánicas que d.1 necesita ANTES de cablearlo en dispatch:
  1. AUTH-FORWARD: el cliente reenvía `Authorization: Bearer <jwt>` y el control lo RECIBE.
  2. STREAMING: el SSE de la forja cruza frame-por-frame (no bufferizado).

Levanta un CONTROL-STANDIN local que mimetiza `POST /v1/inspect/forge` (exige Bearer → 401 si
falta; si viene → SSE con delay entre frames) y corre el RELAY-CLIENTE real (urllib streaming
POST, el MISMO patrón que va a usar dispatch). Verde = el primer frame cruza + el standin
confirma que recibió el Bearer, con timing que prueba streaming (no buffer).

NO toca dispatch todavía (eso es d.1). Es sólo la prueba de mecánica.
"""
import http.server
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "platform"))
import aleph_paths  # noqa: E402  (4.2.d.0: control_url con env override)

_FRAMES = [
    {"type": "sesion.ok", "detail": "conectado"},
    {"type": "observando", "requests": 1},
    {"type": "tool.propuesta", "name": "buscar"},
    {"type": "mcp.forjado", "ok": True},
]
_received_auth = {"value": None}


class _StandinControl(http.server.BaseHTTPRequestHandler):
    """Mimetiza POST /v1/inspect/forge del control: auth-required + SSE streaming."""
    protocol_version = "HTTP/1.0"   # Connection: close → el cliente lee-hasta-cierre (streaming)

    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path != "/v1/inspect/forge":
            self.send_response(404); self.end_headers(); return
        auth = self.headers.get("Authorization")
        _received_auth["value"] = auth
        if not auth or not auth.startswith("Bearer "):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"no_session"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        for ev in _FRAMES:
            self.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.25)   # delay entre frames → si el cliente los lee espaciados, streamea


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _relay_client(control_base, body, bearer):
    """EL RELAY (lo que hará dispatch): POST streaming a control/v1/inspect/forge, reenvía el
    Bearer, y lee el SSE frame por frame. Yield (t_relativo, status, linea)."""
    req = urllib.request.Request(
        control_base + "/v1/inspect/forge",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": bearer,
                 "Accept": "text/event-stream"},
        method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as resp:
        for raw in resp:                       # itera línea por línea a medida que llegan
            line = raw.decode("utf-8", "ignore").rstrip("\n")
            if line:
                yield (round(time.time() - t0, 3), resp.status, line)


def main():
    port = _free_port()
    srv = http.server.HTTPServer(("127.0.0.1", port), _StandinControl)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    os.environ["ALEPH_CONTROL_URL"] = f"http://127.0.0.1:{port}"
    base = aleph_paths.control_url()
    print(f"[smoke] control_url() = {base}", flush=True)
    print(f"[smoke] default sin env = {aleph_paths._CONTROL_URL_DEFAULT}", flush=True)

    body = {"url": "https://showcase.example.com", "forma": "abierto", "puppet_id": "smoke"}
    bearer = "Bearer smoke-session-token-xyz"

    print("[smoke] --- relay: POST streaming a control + Bearer ---", flush=True)
    n, first_t, last_t = 0, None, None
    for (t, status, line) in _relay_client(base, body, bearer):
        n += 1
        first_t = t if first_t is None else first_t
        last_t = t
        print(f"[smoke]  t={t}s status={status}  {line}", flush=True)

    srv.shutdown()
    print("[smoke] --- resultado ---", flush=True)
    print(f"[smoke] auth-forward → control recibió: {_received_auth['value']!r}", flush=True)
    print(f"[smoke] frames/líneas: {n}  ·  primero a t={first_t}s  ·  último a t={last_t}s", flush=True)

    ok_auth = _received_auth["value"] == bearer
    ok_stream = (n > 0 and last_t is not None and last_t >= 0.5)  # spread ≥ los delays acumulados
    if ok_auth and n > 0:
        verdict = "VERDE" if ok_stream else "VERDE (auth-forward ok; revisar timing de streaming)"
        print(f"[smoke] {verdict}: el primer frame SSE cruzó + auth-forward confirmado", flush=True)
        return 0
    print("[smoke] ROJO: ver arriba (auth-forward o streaming no cerraron)", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
