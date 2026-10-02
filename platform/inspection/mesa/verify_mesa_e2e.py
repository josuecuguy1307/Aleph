"""
verify_mesa_e2e.py — e2e HTTP de la Mesa (determinista, $0: fixture local + cerebro-stub).

Levanta un app mínima con SOLO el router de la Mesa (sin DB ni lifespan) y la maneja por HTTP
(TestClient). El motor corre de verdad contra un FIXTURE HTTP local, con un CEREBRO-STUB local
que devuelve tools canónicas → las 6 estaciones se llenan, se construye un belt REAL, todo sin
Groq/shim ni red externa. Cubre los DONE-BAR sobre HTTP:

  DONE-BAR #1: crear → 6 estaciones se llenan en vivo → completar → pieza construida (belt_ref).
  §6 #2 (vivo): caso ambiguo (forma sin cred) → pausa P3; responder 'abierto' → termina verde.
  §6 #3 (vivo): pausa = borrador retomable → aparece en el listado → retomar → termina.
  §6 #4 (vivo): POST /tools/validar con tool buena + rota → verificada + RECHAZADA por el candado.
  DONE-BAR #4 (write): POST /tools/probar sobre un write → gateado, jamás ejecutado.

Corre: PYTHONPATH=platform:product/backend python platform/inspection/mesa/verify_mesa_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[3]
sys.path.insert(0, str(_REPO / "platform"))
sys.path.insert(0, str(_REPO / "product" / "backend"))

# aislar data/ del repo + cerebro-stub como 'brain'
_TMP = Path(tempfile.mkdtemp(prefix="mesa-e2e-"))
os.environ["PUPPET_VAULT_MASTER"] = "mesa-e2e-master"
os.environ["PUPPET_BRAIN_SHIM"] = "1"
os.environ["PUPPET_FORGE_HEARTBEAT_S"] = "0"

_PASS = 0
_FAIL = 0


def check(name, ok, extra=""):
    global _PASS, _FAIL
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {extra}" if extra else ""))
    if ok:
        _PASS += 1
    else:
        _FAIL += 1


# ── FIXTURE HTTP (el "software" a construir) ────────────────────────────────────
_FIXTURE_PORT = [0]


class _Fixture(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/configuration":
            self._send(200, {"images": {"base_url": "http://img"}, "change_keys": ["adult"]})
        elif path == "/good":
            self._send(200, {"id": 1, "title": "OK", "items": [1, 2, 3]})
        elif path == "/list":
            self._send(200, {"results": [{"id": 1}], "page": 1})
        else:
            self._send(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, OPTIONS")
        self.end_headers()


# ── CEREBRO-STUB (OpenAI chat-compat) — devuelve tools canónicas ────────────────
def _brain_handler(fixture_base):
    tools = {
        "tools": [
            {"name": "get_good", "endpoint": "/good", "method": "GET",
             "description": "trae el recurso bueno",
             "input_schema": {"type": "object"}, "sample_call": {"path_params": {}, "query": {}}},
            {"name": "get_list", "endpoint": "/list", "method": "GET",
             "description": "lista recursos",
             "input_schema": {"type": "object"}, "sample_call": {"path_params": {}, "query": {}}},
            {"name": "get_ghost", "endpoint": "/ghost", "method": "GET",
             "description": "endpoint alucinado (no existe → 404 → drop real)",
             "input_schema": {"type": "object"}, "sample_call": {"path_params": {}, "query": {}}},
        ]
    }

    class _Brain(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            # /health y /models por si algo los pinguea
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                self.rfile.read(n)
            except Exception:
                pass
            content = json.dumps(tools)
            resp = {"model": "stub-brain", "choices": [{"message": {"role": "assistant",
                    "content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
            body = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    return _Brain


def _start(server_cls):
    srv = HTTPServer(("127.0.0.1", 0), server_cls)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


def _poll(client, cid, want, timeout=25.0):
    """Poll GET snapshot hasta que el estado ∈ want o timeout."""
    t0 = time.monotonic()
    last = {}
    while time.monotonic() - t0 < timeout:
        r = client.get(f"/v1/construcciones/{cid}")
        if r.status_code == 200:
            last = r.json()
            if last.get("estado") in want:
                return last
        time.sleep(0.25)
    return last


def main():
    global _PASS, _FAIL
    print("=" * 68)
    print("VERIFY · Mesa de Construcción — e2e HTTP (fixture local + cerebro-stub)")
    print("=" * 68)

    fx_srv, fx_base = _start(_Fixture)
    br_srv, br_base = _start(_brain_handler(fx_base))
    os.environ["PUPPET_BRAIN_SHIM_BASE_URL"] = br_base + "/v1"

    # apuntar el almacén de borradores al tmp (monkeypatch del root por env no existe → patch dir)
    from inspection.mesa import almacen
    almacen.CONSTRUCCIONES_DIR = _TMP / "construcciones"

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1.mesa_router import build_mesa_router

    app = FastAPI()
    app.include_router(build_mesa_router())
    client = TestClient(app)

    comun = {"url": fx_base, "self_hosted": True, "validate_path": "/configuration",
             "synth_alias": "brain", "max_rounds": 2, "max_calls": 20}

    # ── DONE-BAR #1 · crear (forma abierta, caso claro) → 6 estaciones → pieza ──
    print("[DONE-BAR #1] crear → estaciones se llenan → pieza construida")
    r = client.post("/v1/construcciones", json={**comun, "forma": "abierto"})
    check("POST /construcciones → 200 + stream", r.status_code == 200 and "space_id" in r.json(),
          str(r.status_code))
    cid = r.json()["construccion_id"]
    snap = _poll(client, cid, {"terminada"})
    check("la construcción TERMINA", snap.get("estado") == "terminada", snap.get("estado"))
    inv = snap.get("inventario", {})
    check("se construyó un belt (pieza real)", bool(inv.get("belt_ref")), inv.get("belt_ref"))
    check("tools verificadas por el candado (≥2)", len(inv.get("tools_validadas") or []) >= 2,
          str([t.get("name") for t in inv.get("tools_validadas") or []]))
    check("el endpoint alucinado fue DESCARTADO (cero-teatro)",
          any("ghost" in (t.get("name") or "") for t in inv.get("tools_descartadas") or []),
          str([t.get("name") for t in inv.get("tools_descartadas") or []]))
    check("la estación final es 'equipar'", snap.get("estacion") == "equipar", snap.get("estacion"))
    # el stream del space existe y tiene los eventos reales
    space_id = "construccion-" + cid
    ev_path = (_REPO / "product" / "backend" / "data" / "espacios" / space_id / "events.jsonl")
    tipos = set()
    if ev_path.exists():
        for ln in ev_path.read_text().splitlines():
            try:
                tipos.add(json.loads(ln).get("type"))
            except Exception:
                pass
    for esperado in ("construccion.creada", "sesion.ok", "tool.validada", "mcp.forjado",
                     "estacion.cambio", "construccion.cerrada"):
        check(f"el stream emitió {esperado}", esperado in tipos)

    # ── §6 #2 vivo · caso ambiguo → P3; responder abierto → termina verde ──────
    print("[#2 vivo] ambiguo (token sin cred) → pausa P3 → responder → termina")
    r = client.post("/v1/construcciones", json={**comun, "forma": "token"})  # sin cred
    cid2 = r.json()["construccion_id"]
    snap2 = _poll(client, cid2, {"pausada"})
    preg = snap2.get("pregunta") or {}
    check("token sin cred → PAUSA con pregunta P3", snap2.get("estado") == "pausada"
          and preg.get("codigo") == "P3", preg.get("codigo"))
    # aparece como borrador retomable en el listado
    lst = client.get("/v1/construcciones").json().get("construcciones", [])
    check("[#3] el borrador aparece en el listado retomable",
          any(c.get("construccion_id") == cid2 for c in lst), str(len(lst)))
    # responder 'abierto' destraba y corre el motor
    rr = client.post(f"/v1/construcciones/{cid2}/respuesta", json={"opcion": "abierto"})
    check("responder 'abierto' reanuda", rr.status_code == 200 and rr.json().get("reanuda"),
          str(rr.json()))
    snap2b = _poll(client, cid2, {"terminada"})
    check("tras responder, la construcción TERMINA verde",
          snap2b.get("estado") == "terminada" and bool(snap2b.get("inventario", {}).get("belt_ref")),
          snap2b.get("estado"))

    # ── §6 #4 vivo · candado sobre tools a mano (buena + rota) ─────────────────
    print("[#4 vivo] manual = mismo gate (POST /tools/validar)")
    # usar la construcción abierta ya terminada (su sesión es 'abierta', sin cred)
    r = client.post("/v1/construcciones", json={**comun, "forma": "abierto"})
    cid3 = r.json()["construccion_id"]
    _poll(client, cid3, {"terminada", "pausada"})
    tools = [
        {"name": "manual_ok", "endpoint": "/good", "method": "GET", "kind": "read",
         "input_schema": {"type": "object", "x-sample-call": {"path_params": {}, "query": {}}}},
        {"name": "manual_rota", "endpoint": "/no-existe", "method": "GET", "kind": "read",
         "input_schema": {"type": "object", "x-sample-call": {"path_params": {}, "query": {}}}},
    ]
    rv = client.post(f"/v1/construcciones/{cid3}/tools/validar", json={"tools": tools, "forma": "abierto"})
    vb = rv.json()
    ver = [v["nombre"] for v in vb.get("verificadas", [])]
    des = [f["nombre"] for f in vb.get("descartadas", [])]
    check("tool a mano BUENA → verificada por el candado", "manual_ok" in ver, str(ver))
    check("tool a mano ROTA → RECHAZADA por el candado", "manual_rota" in des and "manual_rota" not in ver,
          str(des))
    # write gateado
    wr = client.post(f"/v1/construcciones/{cid3}/tools/probar", json={
        "tool": {"name": "borra", "endpoint": "/good", "method": "DELETE", "kind": "write",
                 "input_schema": {"type": "object"}}, "execute": True, "forma": "abierto"})
    wb = wr.json()
    check("[DONE-BAR write] probar write → gateado, jamás ejecutado",
          wb.get("gated") is True and wb.get("approval_required") is True, str(wb.get("kind")))

    fx_srv.shutdown()
    br_srv.shutdown()
    import shutil
    shutil.rmtree(_TMP, ignore_errors=True)

    print("-" * 68)
    print(f"RESULTADO: {_PASS} ✓ · {_FAIL} ✗")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
