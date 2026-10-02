#!/usr/bin/env python3
"""Vara determinista del primer OAuth real (sin necesitar consentimiento humano).

Ejercita el mismo router/listener/broker/gate/belt que producción contra un IdP
local estricto. La certificación con la cuenta real es un paso separado.
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "product" / "backend"
PLATFORM = ROOT / "platform"
for entry in (str(BACKEND), str(PLATFORM)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"  {'✅' if condition else '❌'} {label}"
          + (f" · {detail}" if detail not in ("", None) else ""))
    if not condition:
        FAILURES.append(label)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"sin loader para {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OAUTH = load("aleph_onshape_oauth_test",
             ROOT / "platform" / "connectors" / "oauth_flow.py")
LOOPBACK = load("aleph_onshape_loopback_test",
                ROOT / "platform" / "connectors" / "oauth_loopback.py")


class TokenStub:
    def __init__(self) -> None:
        self.mode = "ok"
        self.last_form: dict[str, str] = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _fmt, *_args):
                return

            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                parsed = urllib.parse.parse_qs(
                    self.rfile.read(size).decode("utf-8"))
                form = {key: values[0] for key, values in parsed.items()}
                outer.last_form = form
                if outer.mode == "invalid_client":
                    self._json(401, {"error": "invalid_client",
                                     "error_description": "Bad client credentials"})
                    return
                if outer.mode == "revoked":
                    self._json(400, {"error": "invalid_grant",
                                     "error_description": "Grant revoked"})
                    return
                if form.get("client_id") != "CATALOG-CLIENT" \
                        or form.get("client_secret") != "local-dev-secret":
                    self._json(401, {"error": "invalid_client"})
                    return
                grant = form.get("grant_type")
                if grant == "authorization_code":
                    verifier = form.get("code_verifier", "")
                    if not verifier:
                        self._json(400, {"error": "pkce_missing"})
                        return
                    payload = {
                        "access_token": "vault-access-token",
                        "refresh_token": "vault-refresh-token",
                        "expires_in": 3600,
                        "token_type": "bearer",
                        "scope": "OAuth2ReadPII OAuth2Read OAuth2Write",
                    }
                elif grant == "refresh_token":
                    payload = {
                        "access_token": "refreshed-access-token",
                        "refresh_token": "rotated-refresh-token",
                        "expires_in": 3600,
                        "scope": "OAuth2ReadPII OAuth2Read OAuth2Write",
                    }
                else:
                    self._json(400, {"error": "unsupported_grant_type"})
                    return
                self._json(200, payload)

            def _json(self, status: int, payload: dict):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def descriptor(token_stub: TokenStub, secret_path: Path) -> dict:
    return {
        "connector": "onshape", "provider": "Onshape",
        "auth_method": "oauth", "api_base": token_stub.base + "/api",
        "validate": {"method": "GET", "path": "/users/sessioninfo"},
        "oauth": {
            "client_id": "CATALOG-CLIENT",
            "authorize_url": token_stub.base + "/oauth/authorize",
            "token_url": token_stub.base + "/oauth/token",
            "redirect_uri": "http://localhost:8765/oauth/callback",
            "scopes": [
                {"id": "OAuth2ReadPII", "requested": True,
                 "tools": ["onshape_whoami"]},
                {"id": "OAuth2Read", "requested": True,
                 "tools": ["onshape_list_documents"]},
                {"id": "OAuth2Write", "requested": True,
                 "tools": ["onshape_create_document"]},
                {"id": "OAuth2Delete", "requested": True,
                 "tools": ["onshape_delete_document"]},
                {"id": "OAuth2Share", "requested": True,
                 "tools": ["onshape_share_document"]},
                {"id": "OAuth2Purchase", "requested": False,
                 "tools": ["onshape_consume_purchase"]},
            ],
            "loopback_ok": False,
            "pkce": {"required": True, "method": "S256"},
            "client_auth": "secret_post",
            "development_client_secret": {
                "file": str(secret_path), "field": "client_secret", "mode": "0600",
            },
        },
    }


def router_roundtrip(stub: TokenStub, temp: Path) -> None:
    print("\nA · router → loopback :8765 → PKCE → token → vault")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1 import connectors_router, repo

    secret_path = temp / "onshape.local.json"
    secret_path.write_text(json.dumps({"client_secret": "local-dev-secret"}),
                           encoding="utf-8")
    secret_path.chmod(0o600)
    onboarding = temp / "onboarding"
    onboarding.mkdir()
    (onboarding / "onshape.json").write_text(
        json.dumps(descriptor(stub, secret_path)), encoding="utf-8")

    store: dict[tuple[str, str], str] = {}

    class Conn:
        def close(self):
            return

    def upsert(_conn, *, user_id, provider, secret):
        store[(str(user_id), provider)] = secret
        return {"provider": provider}

    def get_key(_conn, user_id, provider):
        return store.get((str(user_id), provider))

    def delete_key(_conn, user_id, provider):
        return store.pop((str(user_id), provider), None) is not None

    originals = {
        "onb": connectors_router._ONB,
        "session_owner": repo.session_owner,
        "upsert_key": repo.upsert_key,
        "get_key": repo.get_key,
        "delete_key": repo.delete_key,
    }
    connectors_router._ONB = onboarding
    repo.session_owner = lambda token: "user-1" if token == "session" else None
    repo.upsert_key, repo.get_key, repo.delete_key = upsert, get_key, delete_key
    try:
        app = FastAPI()
        app.include_router(connectors_router.build_connectors_router(
            get_conn=lambda: Conn()))
        client = TestClient(app)
        headers = {"Authorization": "Bearer session"}

        response = client.post("/v1/connectors/onshape/oauth/start",
                               headers=headers)
        started = response.json()
        check("listener quedó esperando consentimiento",
              started.get("state") == "awaiting_consent", started.get("state"))
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(started.get("authorize_url", "")).query)
        check("authorize URL lleva PKCE S256",
              query.get("code_challenge_method") == ["S256"]
              and bool(query.get("code_challenge")))
        check("client_id salió del JSON", query.get("client_id") == ["CATALOG-CLIENT"])
        check("purchase no se pidió",
              "OAuth2Purchase" not in query.get("scope", [""])[0])
        check("redirect exacto :8765",
              query.get("redirect_uri") == [
                  "http://localhost:8765/oauth/callback"])

        callback = ("http://127.0.0.1:8765/oauth/callback?"
                    + urllib.parse.urlencode({
                        "code": "real-code",
                        "state": query["state"][0],
                    }))
        with urllib.request.urlopen(callback, timeout=3) as browser_response:
            check("callback del browser respondió", browser_response.status == 200)

        status = {}
        for _ in range(80):
            status = client.get("/v1/connectors/onshape/oauth/status",
                                headers=headers).json()
            if status.get("state") not in ("awaiting_consent", "exchanging"):
                break
            time.sleep(0.025)
        check("flujo terminó conectado", status.get("state") == "connected", status)
        check("access token llegó al vault", store.get(("user-1", "onshape"))
              == "vault-access-token")
        companion = json.loads(store[("user-1", "onshape__oauth")])
        check("refresh token llegó al companion cifrable",
              companion.get("refresh_token") == "vault-refresh-token")
        check("scope guardado = CONCEDIDO por token response",
              companion.get("granted_scopes")
              == ["OAuth2ReadPII", "OAuth2Read", "OAuth2Write"])
        check("scope omitido quita tools del belt",
              "onshape_delete_document" not in status.get("tools", [])
              and "onshape_share_document" not in status.get("tools", []))
        check("write concedido sí existe",
              "onshape_create_document" in status.get("tools", []))
        check("token exchange recibió code_verifier",
              bool(stub.last_form.get("code_verifier")))
        check("ninguna respuesta expuso el secreto",
              "local-dev-secret" not in json.dumps([started, status]))

        # El socket debe haber muerto al recibir el código.
        time.sleep(0.05)
        try:
            sock = socket.create_connection(("127.0.0.1", 8765), timeout=0.25)
        except OSError:
            closed = True
        else:
            closed = False
            sock.close()
        check("listener :8765 murió tras un callback", closed)

        print("\nB · calibración roja: client_id inválido")
        stub.mode = "invalid_client"
        bad = client.post("/v1/connectors/onshape/oauth/start",
                          headers=headers).json()
        bad_q = urllib.parse.parse_qs(
            urllib.parse.urlparse(bad["authorize_url"]).query)
        bad_callback = ("http://127.0.0.1:8765/oauth/callback?"
                        + urllib.parse.urlencode({
                            "code": "bad-client-code", "state": bad_q["state"][0],
                        }))
        urllib.request.urlopen(bad_callback, timeout=3).read()
        for _ in range(80):
            bad_status = client.get(
                "/v1/connectors/onshape/oauth/status", headers=headers).json()
            if bad_status.get("state") != "exchanging":
                break
            time.sleep(0.025)
        check("invalid client falla con causa accionable",
              bad_status.get("state") == "exchange_failed"
              and bad_status.get("cause") == "invalid_client_id"
              and "client_id" in bad_status.get("message", ""), bad_status)
        stub.mode = "ok"
    finally:
        connectors_router._ONB = originals["onb"]
        repo.session_owner = originals["session_owner"]
        repo.upsert_key = originals["upsert_key"]
        repo.get_key = originals["get_key"]
        repo.delete_key = originals["delete_key"]


def red_loopback_calibrations(stub: TokenStub, temp: Path) -> None:
    print("\nC · calibraciones rojas del transporte")
    secret_path = temp / "onshape.local.json"
    cfg = descriptor(stub, secret_path)["oauth"]

    no_pkce = dict(cfg)
    no_pkce.pop("pkce")
    manager = LOOPBACK.LoopbackFlowManager()
    try:
        manager.start(
            provider="onshape", owner="u", cfg=no_pkce,
            client_id="CATALOG-CLIENT",
            build_authorize_url=OAUTH.build_authorize_url,
            on_code=lambda _code, _verifier: {"state": "connected"},
        )
    except ValueError as exc:
        rejected = "pkce_required" in str(exc)
    else:
        rejected = False
        manager.stop()
    check("quitar PKCE hace fallar la vara", rejected)

    resilient = LOOPBACK.LoopbackFlowManager()
    started = resilient.start(
        provider="onshape", owner="u", cfg=cfg,
        client_id="CATALOG-CLIENT",
        build_authorize_url=OAUTH.build_authorize_url,
        on_code=lambda _code, _verifier: {"state": "connected"},
        timeout=5,
    )
    good_state = urllib.parse.parse_qs(
        urllib.parse.urlparse(started["authorize_url"]).query)["state"][0]
    for query in (
        {"code": "blind"},
        {"code": "blind", "state": "wrong"},
        {"error": "access_denied", "state": "wrong"},
    ):
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:8765/oauth/callback?" + urllib.parse.urlencode(query),
                timeout=2,
            )
        except urllib.error.HTTPError as exc:
            rejected_callback = exc.code == 400
        else:
            rejected_callback = False
        check("callback con state inválido no consume listener",
              rejected_callback and resilient.status().get("state") == "awaiting_consent",
              resilient.status())
    urllib.request.urlopen(
        "http://127.0.0.1:8765/oauth/callback?" + urllib.parse.urlencode({
            "code": "legitimate", "state": good_state,
        }), timeout=2).read()
    for _ in range(40):
        if resilient.status().get("state") == "connected":
            break
        time.sleep(0.025)
    check("callback legítimo posterior todavía completa", resilient.status().get("state") == "connected")

    manager2 = LOOPBACK.LoopbackFlowManager()
    manager2.start(
        provider="onshape", owner="u", cfg=cfg,
        client_id="CATALOG-CLIENT",
        build_authorize_url=OAUTH.build_authorize_url,
        on_code=lambda _code, _verifier: {"state": "connected"},
        timeout=5,
    )
    manager2.stop()
    t0 = time.monotonic()
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:8765/oauth/callback?code=x&state=x",
            timeout=1,
        )
        failed_fast = False
    except (urllib.error.URLError, TimeoutError, OSError):
        failed_fast = time.monotonic() - t0 < 1.2
    check("cortar listener falla con causa y no cuelga",
          failed_fast
          and manager2.status().get("cause") == "listener_stopped",
          manager2.status())


def encrypted_vault(temp: Path) -> None:
    print("\nC2 · vault global real (SQLite cliente + Fernet)")
    from cryptography.fernet import Fernet
    from app.phase1 import repo

    previous = {
        key: os.environ.get(key)
        for key in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH", "PUPPET_DB_ENC_KEY")
    }
    os.environ["ALEPH_ROLE"] = "client"
    os.environ["PUPPET_SQLITE_PATH"] = str(temp / "vault-real.db")
    os.environ["PUPPET_DB_ENC_KEY"] = Fernet.generate_key().decode("ascii")
    repo._db = None
    try:
        repo.asegurar_schema_cliente()
        conn = repo.get_conn()
        try:
            user = repo.get_or_create_user(
                conn, "onshape-vault-qa@local.invalid", "Onshape QA")
            uid = str(user["id"])
            repo.upsert_key(conn, user_id=uid, provider="onshape",
                            secret="vault-plaintext-proof")
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT ciphertext FROM keys WHERE user_id = %s AND provider = %s",
                    (uid, "onshape"),
                )
                row = cursor.fetchone()
            ciphertext = bytes(row[0]) if row else b""
            clear = repo.get_key(conn, uid, "onshape")
        finally:
            conn.close()
        check("repo devuelve el token al broker",
              clear == "vault-plaintext-proof")
        check("SQLite contiene Fernet, no plaintext",
              bool(ciphertext)
              and b"vault-plaintext-proof" not in ciphertext)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        repo._db = None


def refresh_and_revocation(stub: TokenStub, temp: Path) -> None:
    print("\nD · expiración, refresh rotativo y revocación")
    cfg = descriptor(stub, temp / "onshape.local.json")["oauth"]
    expired = {
        "refresh_token": "vault-refresh-token",
        "obtained_at": 1000, "expires_in": 60,
        "granted_scopes": ["OAuth2Read"],
    }
    stub.mode = "ok"
    refreshed = OAUTH.maybe_refresh(
        expired, cfg=cfg, now=2000, http_post=OAUTH._http_post_form)
    check("token expirado refresca sin molestar",
          refreshed.get("refreshed") is True
          and refreshed.get("access_token") == "refreshed-access-token")
    check("Onshape rota el refresh y Aleph lo conserva",
          refreshed.get("refresh_token") == "rotated-refresh-token")

    stub.mode = "revoked"
    revoked = OAUTH.maybe_refresh(
        expired, cfg=cfg, now=2000, http_post=OAUTH._http_post_form)
    check("invalid_grant cae en cubo OAuth revocado",
          revoked.get("reason") == "oauth_revoked", revoked)

    from app.phase1 import diagnostico_conectores as diagnostic
    verdict = diagnostic.producir({
        "tipo": "key", "ref": "onshape", "estado": "roto",
        "causa": "oauth_revocado",
        "evidencia": {"provider": "onshape"},
    })
    check("diagnosticador dice revocación, no llave ni red",
          verdict.get("patron", {}).get("codigo") == "oauth_revocado"
          and verdict.get("escalon") == "credencial"
          and "Revocaste el acceso desde Onshape"
          in verdict.get("patron", {}).get("mensaje", ""), verdict)
    stub.mode = "ok"


def mcp_surface(scopes: list[str]) -> tuple[list[str], dict]:
    env = dict(os.environ)
    env.update({
        "ONSHAPE_ACCESS_TOKEN": "fake-access",
        "ONSHAPE_OAUTH_META": json.dumps({
            "state": "connected", "granted_scopes": scopes,
        }),
    })
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "product" / "belts" / "ingenieria"
                             / "onshape_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
    }) + "\n")
    process.stdin.write(json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
    }) + "\n")
    process.stdin.write(json.dumps({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "onshape_delete_document",
                   "arguments": {"document_id": "x"}},
    }) + "\n")
    process.stdin.flush()
    responses = [json.loads(process.stdout.readline()) for _ in range(3)]
    process.terminate()
    process.wait(timeout=3)
    tools = [tool["name"] for tool in responses[1]["result"]["tools"]]
    denied = json.loads(responses[2]["result"]["content"][0]["text"])
    return tools, denied


def scope_and_gate() -> None:
    print("\nE · scope concedido → superficie; peligrosas → B4")
    tools, denied = mcp_surface(["OAuth2ReadPII", "OAuth2Read"])
    check("sin write/delete/share no existen en tools/list",
          tools == ["onshape_whoami", "onshape_list_documents"], tools)
    check("invocar una tool oculta falla cerrado",
          denied.get("error") == "tool_not_granted")
    tools_write, _ = mcp_surface(["OAuth2Read", "OAuth2Write"])
    check("write concedido hace aparecer sólo su tool",
          "onshape_create_document" in tools_write
          and "onshape_delete_document" not in tools_write, tools_write)

    from gates import recipe_enforcer
    recipe = {
        "meta": {"name": "onshape-gate-calibration"},
        "tier": "average", "autonomy": "balanceado",
        "belt": {"action_classes": {
            "onshape": {
                "onshape_whoami": "read",
                "onshape_list_documents": "read",
                "onshape_create_document": "write-world",
                "onshape_delete_document": "write-world",
                "onshape_share_document": "write-world",
                "onshape_consume_purchase": "money_touch",
            },
        }},
        "gates": {"money_touch": "off", "send": "off"},
    }
    gate = recipe_enforcer.build_enforced_gate(recipe)
    check("lectura concedida ejecuta",
          gate.evaluate("onshape", "onshape_list_documents", {}).action
          == "execute")
    for tool in (
        "onshape_create_document", "onshape_delete_document",
        "onshape_share_document", "onshape_consume_purchase",
    ):
        decision = gate.evaluate("onshape", tool, {})
        check(f"{tool} siempre frena en B4",
              decision.action == "needs_ok"
              and decision.payload.get("requiere_ok") is True,
              decision.action)


def static_contract() -> None:
    print("\nF · contrato de catálogo + secreto fuera del bundle")
    obj = json.loads((ROOT / "catalog" / "connectors" / "onboarding"
                      / "onshape.json").read_text(encoding="utf-8"))
    cfg = obj["oauth"]
    required = {
        "client_id", "authorize_url", "token_url", "scopes",
        "loopback_ok", "pkce", "revoke_url",
    }
    check("entrada declara todo el contrato OAuth",
          required <= set(cfg), sorted(required - set(cfg)))
    check("veredicto decisivo quedó false",
          cfg.get("loopback_ok") is False)
    check("catálogo no contiene un valor client_secret",
          "client_secret" not in cfg
          and set((cfg.get("development_client_secret") or {}).keys())
          <= {"file", "field", "mode"})
    check("belt deliberadamente no declara cards",
          "cards" not in json.loads((
              ROOT / "catalog" / "templates" / "ingenieria"
              / "belt-onshape.mcp.json").read_text(encoding="utf-8"))["_meta"])

    result = subprocess.run(
        [sys.executable, str(ROOT / "qa" / "assert_no_onshape_secret.py"),
         "--target", str(ROOT / "platform"),
         "--target", str(ROOT / "product" / "belts"),
         "--target", str(ROOT / "catalog")],
        text=True, capture_output=True,
    )
    check("gate anti-secreto pasa sobre el source",
          result.returncode == 0, result.stdout + result.stderr)


def main() -> int:
    print("══ ONSHAPE · OAuth loopback/PKCE/vault/scope/refresh ══")
    stub = TokenStub()
    try:
        with tempfile.TemporaryDirectory(prefix="aleph-onshape-qa-") as td:
            temp = Path(td)
            router_roundtrip(stub, temp)
            red_loopback_calibrations(stub, temp)
            encrypted_vault(temp)
            refresh_and_revocation(stub, temp)
        scope_and_gate()
        static_contract()
    finally:
        stub.close()
    print()
    if FAILURES:
        print(f"══ ❌ {len(FAILURES)} calibraciones fallaron: {FAILURES} ══")
        return 1
    print("══ ✅ TODAS LAS CALIBRACIONES OAUTH ONSHAPE PASARON ══")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
