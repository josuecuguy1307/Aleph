"""d.3 — /me/tier autoritativo (refleja el tier de CONTROL, no solo el local). [Casa 2 · Fase 4]

El cliente consulta el tier al control (autoritativo: users.tier lo escribe el webhook de Dodo)
con TTL —respeta D1: NO llama a casa en cada check— y cae a la caché local si el control no
responde. Prueba `_fetch_control_tier`, el mecanismo nuevo.
"""
import http.server
import json
import os
import socket
import sys
import threading
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
for p in (_REPO / "product" / "backend", _REPO / "platform", _REPO / "platform" / "db"):
    sys.path.insert(0, str(p))
from app.phase1 import payments_router  # noqa: E402

_TIER = {"value": "basico"}


class _Control(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path != "/v1/payments/me/tier":
            self.send_response(404); self.end_headers(); return
        if not (self.headers.get("Authorization") or "").startswith("Bearer "):
            self.send_response(401); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"error":"no_session"}'); return
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"account_id": "u", "tier": _TIER["value"],
                                     "es_premium": _TIER["value"] in ("basico", "tecnico")}).encode())


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _with_control():
    port = _free_port()
    srv = http.server.HTTPServer(("127.0.0.1", port), _Control)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def test_fetches_authoritative_tier_from_control():
    payments_router._control_tier_cache.clear(); _TIER["value"] = "basico"
    srv, port = _with_control()
    try:
        os.environ["ALEPH_CONTROL_URL"] = f"http://127.0.0.1:{port}"
        got = payments_router._fetch_control_tier("Bearer tok", "owner-A")
    finally:
        srv.shutdown()
    assert got and got["tier"] == "basico" and got["source"] == "control", got


def test_falls_back_to_local_when_control_unreachable():
    payments_router._control_tier_cache.clear()
    os.environ["ALEPH_CONTROL_URL"] = f"http://127.0.0.1:{_free_port()}"   # nadie escucha
    assert payments_router._fetch_control_tier("Bearer tok", "owner-B") is None  # → caché local


def test_ttl_caches_one_query_respects_D1():
    payments_router._control_tier_cache.clear(); _TIER["value"] = "tecnico"
    srv, port = _with_control()
    try:
        os.environ["ALEPH_CONTROL_URL"] = f"http://127.0.0.1:{port}"
        a = payments_router._fetch_control_tier("Bearer tok", "owner-C")
        _TIER["value"] = "free"   # el control cambia, pero el TTL NO re-consulta (D1: no en cada check)
        b = payments_router._fetch_control_tier("Bearer tok", "owner-C")
    finally:
        srv.shutdown()
    assert a["tier"] == "tecnico" and b["tier"] == "tecnico", (a, b)
