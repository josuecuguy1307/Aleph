#!/usr/bin/env python3
"""
test_a3_partial_oauth.py — EVIDENCIA REAL del gate A3: "Conectado" verifica COMPLETITUD de
la credencial OAuth. Mismo patrón que test_orcid_oauth_caso_a (router real + broker Postgres +
Fernet + stub del proveedor), variando si el flujo pide offline y si el proveedor devuelve
refresh_token.

Qué prueba:
  A. OFFLINE pedido + SIN refresh → 302 ?oauth=partial · marker "<name>__oauth_partial" GUARDADO ·
     companion "<name>__oauth" AUSENTE · access_token igual guardado (funciona ~1h).
  B. OFFLINE pedido + CON refresh → 302 ?oauth=ok · companion "<name>__oauth" presente ·
     marker AUSENTE.
  C. NO se pidió offline + SIN refresh → 302 ?oauth=ok (NO parcial: no pedimos durabilidad).
  D. RE-CONEXIÓN: un provider que quedó PARCIAL y luego conecta bien (offline+refresh) →
     marker LIMPIADO, companion presente.

Corre:  cd product/backend && python3 -m app.phase1.test_a3_partial_oauth
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_REPO_ROOT = _HERE.parents[4]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import repo  # noqa: E402
from app.phase1.connectors_router import build_connectors_router  # noqa: E402

_ONB = _REPO_ROOT / "catalog" / "connectors" / "onboarding"
_OAUTH_PY = _REPO_ROOT / "platform" / "connectors" / "oauth_flow.py"

PROVIDER = "a3test"
TEST_CID = "APP-A3CLIENT0001"
TEST_CSEC = "a3-secret-1a2b3c4d5e6f"
STUB_TOKEN = "a3-access-TESTTOKEN-abcd1234"
STUB_REFRESH = "a3-refresh-DURABLE-zzzz9999"
EMAIL = "a3-partial-oauth@toy.local"

_stub_give_refresh = False   # lo togglea cada caso


def _load_oauth():
    spec = importlib.util.spec_from_file_location("puppet_oauth_flow_a3", _OAUTH_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(n).decode("utf-8"))
        ok = (form.get("grant_type", [""])[0] == "authorization_code"
              and form.get("code", [""])[0] != "")
        if not ok:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error":"invalid_request"}'); return
        payload = {"access_token": STUB_TOKEN, "token_type": "bearer", "expires_in": 3600}
        if _stub_give_refresh:
            payload["refresh_token"] = STUB_REFRESH
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


def _start_stub():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _write_object(stub_base: str, *, offline: bool):
    oauth_cfg = {
        "authorize_url": stub_base + "/oauth/authorize",
        "token_url": stub_base + "/oauth/token",
        "scope": "/authenticate",
        "client_id_env": "A3_TEST_CLIENT_ID",
        "client_secret_env": "A3_TEST_CLIENT_SECRET",
        "identity_field": "sub",
    }
    if offline:
        oauth_cfg["authorize_params"] = {"access_type": "offline", "prompt": "consent"}
    obj = {"connector": PROVIDER, "auth_method": "oauth", "tier": "average",
           "provider": PROVIDER, "capability_line": "toy A3.", "oauth": oauth_cfg,
           "api_base": stub_base}
    p = _ONB / f"{PROVIDER}.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


_fails = []
def check(label, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {label}" + (f"  · {extra}" if extra else ""))
    if not cond:
        _fails.append(label)


def _keys(uid):
    c = repo.get_conn()
    try:
        return {k["provider"] for k in repo.list_keys(c, uid)}
    finally:
        c.close()


def main():
    global _stub_give_refresh
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    oauth = _load_oauth()
    os.environ["A3_TEST_CLIENT_ID"] = TEST_CID
    os.environ["A3_TEST_CLIENT_SECRET"] = TEST_CSEC
    srv, stub = _start_stub()

    conn = repo.get_conn()
    try:
        uid = repo.get_or_create_user(conn, EMAIL, "A3 Toy")["id"]
    finally:
        conn.close()

    def _clean():
        c = repo.get_conn()
        try:
            for p in (PROVIDER, f"{PROVIDER}__oauth", f"{PROVIDER}__oauth_partial"):
                with c.cursor() as cur:
                    cur.execute("DELETE FROM keys WHERE user_id=%s AND provider=%s", (uid, p))
            c.commit()
        finally:
            c.close()

    def _drive(offline: bool, give_refresh: bool):
        global _stub_give_refresh
        _stub_give_refresh = give_refresh
        _write_object(stub, offline=offline)
        app = FastAPI()
        app.include_router(build_connectors_router(get_conn=repo.get_conn))
        client = TestClient(app)
        st = oauth.mint_state(repo.encrypt_secret, user_id=uid, provider=PROVIDER)
        r = client.get(f"/v1/connectors/{PROVIDER}/callback",
                       params={"code": "CODE-a3", "state": st}, follow_redirects=False)
        return r.headers.get("location", ""), _keys(uid)

    print("\n══ A3 · completitud de credencial OAuth — EVIDENCIA EJECUTADA ══\n")
    try:
        # ── A. OFFLINE + SIN refresh → PARCIAL ───────────────────────────────────────
        print("A) offline pedido + proveedor NO devuelve refresh → PARCIAL:")
        _clean()
        loc, ks = _drive(offline=True, give_refresh=False)
        check("redirect → ?oauth=partial (no ok)", "oauth=partial" in loc, loc)
        check("marker '<name>__oauth_partial' GUARDADO", f"{PROVIDER}__oauth_partial" in ks, str(sorted(ks)))
        check("companion '<name>__oauth' AUSENTE (no hay refresh)", f"{PROVIDER}__oauth" not in ks)
        check("access_token igual guardado (funciona ~1h)", PROVIDER in ks)

        # ── B. OFFLINE + CON refresh → OK completo ───────────────────────────────────
        print("\nB) offline pedido + proveedor SÍ devuelve refresh → OK completo:")
        _clean()
        loc, ks = _drive(offline=True, give_refresh=True)
        check("redirect → ?oauth=ok", "oauth=ok" in loc and "partial" not in loc, loc)
        check("companion '<name>__oauth' presente (refresh guardado)", f"{PROVIDER}__oauth" in ks)
        check("marker parcial AUSENTE", f"{PROVIDER}__oauth_partial" not in ks, str(sorted(ks)))

        # ── C. NO offline + SIN refresh → OK (no parcial: no pedimos durabilidad) ─────
        print("\nC) NO se pidió offline + sin refresh → OK (no parcial):")
        _clean()
        loc, ks = _drive(offline=False, give_refresh=False)
        check("redirect → ?oauth=ok", "oauth=ok" in loc and "partial" not in loc, loc)
        check("marker parcial AUSENTE (no pedimos offline)", f"{PROVIDER}__oauth_partial" not in ks)

        # ── D. RE-CONEXIÓN: parcial → conecta bien → marker limpiado ─────────────────
        print("\nD) re-conexión tras parcial (offline+refresh) → marker limpiado:")
        _clean()
        _drive(offline=True, give_refresh=False)                       # deja PARCIAL
        pre = _keys(uid)
        loc, ks = _drive(offline=True, give_refresh=True)              # reconecta bien
        check("antes estaba el marker parcial", f"{PROVIDER}__oauth_partial" in pre)
        check("tras reconectar → ?oauth=ok", "oauth=ok" in loc and "partial" not in loc, loc)
        check("marker parcial LIMPIADO", f"{PROVIDER}__oauth_partial" not in ks, str(sorted(ks)))
        check("companion refresh presente", f"{PROVIDER}__oauth" in ks)

        # ── unidad: wants_offline ────────────────────────────────────────────────────
        print("\n(unidad) wants_offline:")
        check("access_type=offline → True", oauth.wants_offline({"authorize_params": {"access_type": "offline"}}))
        check("scope offline_access → True", oauth.wants_offline({"scope": "openid profile offline_access"}))
        check("sin offline → False", not oauth.wants_offline({"scope": "openid profile"}))
    finally:
        srv.shutdown()
        try:
            (_ONB / f"{PROVIDER}.json").unlink()
        except OSError:
            pass
        _clean()

    print()
    if _fails:
        print(f"══ ❌ {len(_fails)} CHECK(S) FALLARON: {_fails} ══\n")
        sys.exit(1)
    print("══ ✅ TODOS LOS CHECKS A3 (partial-store) PASARON ══\n")


if __name__ == "__main__":
    main()
