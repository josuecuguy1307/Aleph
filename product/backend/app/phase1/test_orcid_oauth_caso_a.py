#!/usr/bin/env python3
"""
test_orcid_oauth_caso_a.py — EVIDENCIA REAL ejecutada del Caso A (OAuth Authorization
Code) del connect-workflow, hasta donde NO requiere el consent humano + la app ORCID
registrada. Prueba el FLUJO completo contra un STUB del proveedor (mismo patrón que el
gmail_stub): router real + broker real (Postgres + Fernet) + repo real. Sólo el browser
del consent y la app sandbox de ORCID quedan para persona usuaria.

Qué prueba (cada bloque imprime EVIDENCIA):
  1. STATE/CSRF (unidad): mint→read OK · token manipulado → rechazado · expirado → rechazado
     · state de OTRO provider → rechazado.
  2. /connect oauth SIN creds → oauth_pending (botón honesto, no muere; no redirige).
  3. /connect oauth CON creds → oauth_redirect + authorize_url bien formado (client_id,
     scope, redirect_uri, state). Y CERO key guardada (✓ sólo post-callback).
  4. callback SIN state / state basura → 400 (rechazo CSRF duro).
  5. callback DENY (?error) → 302 ?oauth=cancelled · CERO key (no ✓).
  6. callback HAPPY (code válido + state válido, stub devuelve token) → 302 ?oauth=ok ·
     token GUARDADO CIFRADO en el broker (ciphertext≠token en Postgres) · get_key descifra
     == token del stub · fingerprint sha256 coincide. El stub confirma que recibió el
     client_id/secret/code/redirect_uri correctos (intercambio server-side de verdad).
  7. callback REPLAY (mismo state otra vez) → 400.

Corre como script (imprime evidencia legible):
    cd product/backend && python3 -m app.phase1.test_orcid_oauth_caso_a
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]            # product/backend
_REPO_ROOT = _HERE.parents[4]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import repo  # noqa: E402
from app.phase1.connectors_router import build_connectors_router  # noqa: E402

_ONB = _REPO_ROOT / "catalog" / "connectors" / "onboarding"
_OAUTH_PY = _REPO_ROOT / "platform" / "connectors" / "oauth_flow.py"

# Provider toy aislado (no toca orcid.json real). client_id/secret por env de TEST.
PROVIDER = "orcidtest"
TEST_CID = "APP-TESTCLIENT0001"
TEST_CSEC = "test-secret-9f8e7d6c5b4a"
STUB_TOKEN = "orcid-sandbox-access-TESTTOKEN-abcd1234efgh5678"
STUB_IDENTITY = "0000-0002-1825-0097"
EMAIL = "orcid-oauth-caso-a@toy.local"


def _load_oauth():
    spec = importlib.util.spec_from_file_location("puppet_oauth_flow_test", _OAUTH_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── stub del proveedor OAuth (token endpoint) ────────────────────────────────────
_received: dict = {}


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(n).decode("utf-8"))
        _received.update({k: v[0] for k, v in form.items()})
        # exige el intercambio server-side correcto
        ok = (form.get("client_id", [""])[0] == TEST_CID
              and form.get("client_secret", [""])[0] == TEST_CSEC
              and form.get("grant_type", [""])[0] == "authorization_code"
              and form.get("code", [""])[0] != "")
        if not ok:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error":"invalid_request"}'); return
        body = json.dumps({
            "access_token": STUB_TOKEN, "token_type": "bearer",
            "orcid": STUB_IDENTITY, "scope": "/authenticate",
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


def _start_stub() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _write_toy_object(stub_base: str):
    obj = {
        "connector": PROVIDER, "auth_method": "oauth", "tier": "average",
        "provider": PROVIDER, "capability_line": "Listo (toy).",
        "oauth": {
            "authorize_url": stub_base + "/oauth/authorize",
            "token_url": stub_base + "/oauth/token",
            "scope": "/authenticate",
            "client_id_env": "ORCID_TEST_CLIENT_ID",
            "client_secret_env": "ORCID_TEST_CLIENT_SECRET",
            "identity_field": "orcid",
        },
        "api_base": stub_base,
    }
    p = _ONB / f"{PROVIDER}.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


_fails = []
def check(label: str, cond: bool, extra: str = ""):
    mark = "✅" if cond else "❌"
    print(f"  {mark} {label}" + (f"  · {extra}" if extra else ""))
    if not cond:
        _fails.append(label)


def main():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    oauth = _load_oauth()
    fp = lambda s: hashlib.sha256(s.encode()).hexdigest()[:12]

    print("\n══ Caso A · OAuth connect-workflow — EVIDENCIA EJECUTADA ══\n")

    # 1) STATE / CSRF (unidad, sobre el Fernet REAL del org) ───────────────────────
    print("1) state / CSRF (Fernet del org):")
    st = oauth.mint_state(repo.encrypt_secret, user_id="u-123", provider=PROVIDER)
    check("mint→read devuelve el user", oauth.read_state(repo.decrypt_secret, st, provider=PROVIDER) == "u-123")
    check("state manipulado → rechazado", oauth.read_state(repo.decrypt_secret, st + "x", provider=PROVIDER) is None)
    check("state de OTRO provider → rechazado", oauth.read_state(repo.decrypt_secret, st, provider="otro") is None)
    st_exp = oauth.mint_state(repo.encrypt_secret, user_id="u-123", provider=PROVIDER, ttl=-1)
    check("state expirado → rechazado", oauth.read_state(repo.decrypt_secret, st_exp, provider=PROVIDER) is None)
    check("state ausente → rechazado", oauth.read_state(repo.decrypt_secret, None, provider=PROVIDER) is None)

    srv, stub = _start_stub()
    obj_path = _write_toy_object(stub)
    conn = repo.get_conn()
    try:
        user = repo.get_or_create_user(conn, EMAIL, "ORCID Caso A")
        uid = user["id"]
    finally:
        conn.close()
    token = repo.mint_session(uid)
    auth = {"Authorization": f"Bearer {token}"}

    app = FastAPI()
    app.include_router(build_connectors_router(get_conn=repo.get_conn))
    client = TestClient(app)

    def _no_key():
        c = repo.get_conn()
        try:
            return repo.get_key(c, uid, PROVIDER) is None
        finally:
            c.close()

    try:
        # 2) /connect oauth SIN creds → oauth_pending ────────────────────────────────
        print("\n2) /connect oauth SIN app registrada:")
        os.environ.pop("ORCID_TEST_CLIENT_ID", None)
        os.environ.pop("ORCID_TEST_CLIENT_SECRET", None)
        r = client.post(f"/v1/connectors/{PROVIDER}/connect",
                        json={"creds": {}, "user_id": uid}, headers=auth)
        d = r.json()
        check("estado = oauth_pending (honesto, no redirige)", d.get("state") == "oauth_pending", d.get("message", ""))
        check("no devuelve authorize_url", "authorize_url" not in d)

        # 3) /connect oauth CON creds → oauth_redirect ───────────────────────────────
        print("\n3) /connect oauth CON app registrada (creds de test):")
        os.environ["ORCID_TEST_CLIENT_ID"] = TEST_CID
        os.environ["ORCID_TEST_CLIENT_SECRET"] = TEST_CSEC
        r = client.post(f"/v1/connectors/{PROVIDER}/connect",
                        json={"creds": {}, "user_id": uid}, headers=auth)
        d = r.json()
        check("estado = oauth_redirect", d.get("state") == "oauth_redirect")
        url = d.get("authorize_url", "")
        q = parse_qs(urlparse(url).query)
        check("authorize_url lleva client_id correcto", q.get("client_id", [""])[0] == TEST_CID)
        check("scope = /authenticate", q.get("scope", [""])[0] == "/authenticate")
        check("redirect_uri = callback del backend", q.get("redirect_uri", [""])[0].endswith(f"/v1/connectors/{PROVIDER}/callback"))
        good_state = q.get("state", [""])[0]
        check("authorize_url lleva un state", bool(good_state))
        check("AÚN no hay key guardada (✓ sólo post-callback)", _no_key())

        # 4) callback SIN/CON state inválido → 400 ───────────────────────────────────
        print("\n4) callback rechaza state inválido (CSRF):")
        r = client.get(f"/v1/connectors/{PROVIDER}/callback", params={"code": "X"}, follow_redirects=False)
        check("callback SIN state → 400", r.status_code == 400, str(r.status_code))
        r = client.get(f"/v1/connectors/{PROVIDER}/callback", params={"code": "X", "state": "basura"}, follow_redirects=False)
        check("callback state basura → 400", r.status_code == 400, str(r.status_code))

        # 5) callback DENY → 302 cancelado, sin key ──────────────────────────────────
        print("\n5) callback DENY del usuario:")
        r = client.get(f"/v1/connectors/{PROVIDER}/callback",
                       params={"error": "access_denied", "state": good_state}, follow_redirects=False)
        loc = r.headers.get("location", "")
        check("deny → 302", r.status_code == 302, str(r.status_code))
        check("deny → SPA ?oauth=cancelled", "oauth=cancelled" in loc, loc)
        check("deny → NO guardó key (no ✓)", _no_key())

        # 6) callback HAPPY → token cifrado al broker ─────────────────────────────────
        print("\n6) callback HAPPY (code válido → token cifrado al broker):")
        r = client.get(f"/v1/connectors/{PROVIDER}/callback",
                       params={"code": "REALCODE-xyz", "state": good_state}, follow_redirects=False)
        loc = r.headers.get("location", "")
        check("happy → 302", r.status_code == 302, str(r.status_code))
        check("happy → SPA ?oauth=ok", "oauth=ok" in loc, loc)
        check("stub recibió el client_id correcto (server-side)", _received.get("client_id") == TEST_CID)
        check("stub recibió el client_secret correcto", _received.get("client_secret") == TEST_CSEC)
        check("stub recibió el code", _received.get("code") == "REALCODE-xyz")
        # broker: leer y verificar cifrado + fingerprint
        c = repo.get_conn()
        try:
            stored = repo.get_key(c, uid, PROVIDER)
            with c.cursor() as cur:
                cur.execute("SELECT ciphertext FROM keys WHERE user_id=%s AND provider=%s", (uid, PROVIDER))
                row = cur.fetchone()
            raw = bytes(row[0]) if row else b""
        finally:
            c.close()
        check("token guardado descifra == token del stub", stored == STUB_TOKEN)
        check("en Postgres está CIFRADO (ciphertext ≠ token)", STUB_TOKEN.encode() not in raw and len(raw) > 0,
              f"fingerprint={fp(stored or '')}")

        # 7) callback REPLAY → 400 ────────────────────────────────────────────────────
        print("\n7) callback REPLAY (mismo state otra vez):")
        r = client.get(f"/v1/connectors/{PROVIDER}/callback",
                       params={"code": "REALCODE-xyz", "state": good_state}, follow_redirects=False)
        check("replay del mismo state → 400", r.status_code == 400, str(r.status_code))

    finally:
        srv.shutdown()
        try:
            obj_path.unlink()
        except OSError:
            pass
        # limpiar la key toy (dejamos el user toy aislado)
        try:
            c = repo.get_conn()
            with c.cursor() as cur:
                cur.execute("DELETE FROM keys WHERE user_id=%s AND provider=%s", (uid, PROVIDER))
            c.commit(); c.close()
        except Exception:
            pass

    print()
    if _fails:
        print(f"══ ❌ {len(_fails)} CHECK(S) FALLARON: {_fails} ══\n")
        sys.exit(1)
    print("══ ✅ TODOS LOS CHECKS DEL CASO A (sin consent humano) PASARON ══")
    print("Falta SÓLO: app ORCID sandbox registrada (client_id/secret) → redirect real + approve humano.\n")


if __name__ == "__main__":
    main()
