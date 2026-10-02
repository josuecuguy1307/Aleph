"""EL test del tier falsificado + los bordes del puente cliente→control. [Casa 2 · Fase 4 · 4.2.d.1]

LA PROPIEDAD DE SEGURIDAD (D1): el cliente NO puede autorizar construcción con su tier local.
  - el relay NO manda NINGÚN tier (el cliente no puede colar 'premium'), y
  - el control decide por SU tier autoritativo → si dice free/no-premium, 402 → el muro AGUANTA.
Un `users.tier='premium'` falsificado en el SQLite del cliente es irrelevante: no viaja, y el
control (que dice free) niega. Este test lo fija.

Usa un CONTROL-STANDIN tier-aware (mimetiza enforce_construction_premium: 402 si no-premium) +
el RELAY REAL (`dispatch_router._relay_forge_to_control`). Sin Postgres/uvicorn → rápido y en la
regresión. (El mismo property contra el control REAL vive en deploy/fase4/harness_falsified_tier.py.)
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
from app.phase1 import dispatch_router  # noqa: E402  (el relay REAL)

_TIER = {"value": "free"}        # el tier AUTORITATIVO del control (el test lo setea)
_last_payload = {"value": None}


class _StandinControl(http.server.BaseHTTPRequestHandler):
    """Mimetiza POST /v1/inspect/forge del control: auth-required + muro por tier autoritativo."""
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        _last_payload["value"] = json.loads(self.rfile.read(n) or b"{}")
        auth = self.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer ") or not auth[7:].strip():
            self.send_response(401); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"detail":{"error":"no_session"}}'); return
        if _TIER["value"] != "premium":     # EL MURO: control niega por SU tier (no el del cliente)
            self.send_response(402); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"detail": {"error": "premium", "feature": "mcp_construction",
                                                    "min_tier": "basico", "tier_gated": True}}).encode())
            return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        for ev in ({"type": "sesion.ok"}, {"type": "mcp.forjado", "ok": True}):
            self.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode()); self.wfile.flush()


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class _Body:
    """DispatchRequest-like: los campos que lee el relay (sin NINGÚN tier — no existe el campo)."""
    service = "servicio-inexistente"; url = "https://mi-api.example.com"; credential = "k"
    forma = "token"; puppet_id = "p"; slug = None; local_target = False
    auth_in = "query"; auth_param = "api_key"; auth_header = "Authorization"; auth_template = "Bearer {token}"
    validate_path = "/x"; validate_query = None; api_shape_hint = ""
    login_path = "/l"; login_credentials = None; login_token_where = "json"; login_token_key = "t"
    login_inject_where = "header"; login_inject_name = "Authorization"; login_inject_template = "Bearer {token}"
    login_body_format = "json"; session_key = None; login_url = None
    max_rounds = 3; max_calls = 30; max_tokens = 1000; synth_alias = "oss"; seed_probes = None


def _relay(port, tier="free", bearer="Bearer session-token"):
    os.environ["ALEPH_CONTROL_URL"] = f"http://127.0.0.1:{port}"
    _TIER["value"] = tier
    return "".join(dispatch_router._relay_forge_to_control(_Body(), bearer))


def _with_control():
    port = _free_port()
    srv = http.server.HTTPServer(("127.0.0.1", port), _StandinControl)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def test_falsified_local_premium_does_NOT_forge():
    """EL criterio de d.1: control dice free → 402 → dispatch.denied. El tier local no importa."""
    srv, port = _with_control()
    try:
        out = _relay(port, tier="free")
    finally:
        srv.shutdown()
    assert "dispatch.denied" in out and "tier_gated" in out, out
    assert "mcp.forjado" not in out, "NO debió forjar con control=free"


def test_relay_sends_NO_tier():
    """El cliente no puede colar su tier: el payload al control no tiene tier/premium."""
    srv, port = _with_control()
    try:
        _relay(port, tier="free")
    finally:
        srv.shutdown()
    keys = set((_last_payload["value"] or {}).keys())
    assert not (keys & {"tier", "premium", "account_tier", "role"}), keys


def test_premium_user_forge_is_relayed():
    """Si el control (autoritativo) dice premium → la forja fluye y el SSE se relaya."""
    srv, port = _with_control()
    try:
        out = _relay(port, tier="premium")
    finally:
        srv.shutdown()
    assert "mcp.forjado" in out, out


def test_honest_edge_bad_auth():
    srv, port = _with_control()
    try:
        out = _relay(port, tier="premium", bearer="")   # sin Bearer → control 401
    finally:
        srv.shutdown()
    assert "sesión inválida" in out and "mcp.forjado" not in out, out


def test_honest_edge_control_unreachable():
    dead = _free_port()   # nadie escucha
    out = _relay(dead, tier="free")
    assert "control-plane no disponible" in out and "mcp.forjado" not in out, out
