#!/usr/bin/env python3
"""
verify_oauth_refresh_ticket9.py — el REFRESH del access_token OAuth realmente se cablea.

Cubre el hueco real del ticket 9: hasta ahora refresh_access_token tenía CERO callers, así
que a la ~1h Google devolvía 401 a mitad del run. Este harness prueba, sin cuenta real:

  A) oauth_flow.token_expired / maybe_refresh (unidad, http_post inyectado):
       still_valid · expired→refresh · refresh_failed · sin refresh_token · sin creds.
  B) credential_broker._maybe_refresh_oauth con un repo EN MEMORIA:
       token vencido → renueva, DEVUELVE el token nuevo y RE-PERSISTE (access + companion);
       companion actualizado ⇒ el 2º lookup ve still_valid (no re-renueva);
       refresh fallido → conserva el token viejo (degrada a 401 honesto, no finge éxito).

Corre: python qa/verify_oauth_refresh_ticket9.py   (sin Postgres, sin red)
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "product" / "backend"))

_fails = []


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + (f"  · {detail}" if detail else ""))
    if not cond:
        _fails.append(name)


def _load_oauth_flow():
    p = _REPO / "platform" / "connectors" / "oauth_flow.py"
    spec = importlib.util.spec_from_file_location("puppet_oauth_flow_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    oauth = _load_oauth_flow()
    NOW = 1_000_000.0

    print("\nA) oauth_flow.token_expired / maybe_refresh (unidad):")
    fresh = {"obtained_at": NOW, "expires_in": 3600, "refresh_token": "r1",
             "token_url": "https://t/x", "client_id_env": "CID", "client_secret_env": "CSEC"}
    old = {**fresh, "obtained_at": NOW - 4000}          # vencido (obtained + 3600 < now)
    check("fresco → no vencido", oauth.token_expired(fresh, now=NOW) is False)
    check("viejo → vencido", oauth.token_expired(old, now=NOW) is True)
    check("sin expires_in → vencido (renovar de más)",
          oauth.token_expired({"obtained_at": NOW, "refresh_token": "r"}, now=NOW) is True)
    # skew: vence dentro de 120s → ya se considera vencido
    edge = {**fresh, "obtained_at": NOW - 3500}          # quedan 100s < skew 120
    check("dentro del skew → vencido", oauth.token_expired(edge, now=NOW) is True)

    env = {"CID": "the-client-id", "CSEC": "the-secret"}
    calls = []

    def http_ok(url, form, timeout=20):
        calls.append({"url": url, "form": form})
        return 200, {"access_token": "NEW-TOKEN-xyz", "expires_in": 3600}

    def http_fail(url, form, timeout=20):
        return 400, {"error": "invalid_grant"}

    r_valid = oauth.maybe_refresh(fresh, env=env, now=NOW, http_post=http_ok)
    check("still_valid → refreshed False", r_valid.get("refreshed") is False, r_valid.get("reason"))
    check("still_valid NO llamó al token endpoint", len(calls) == 0)

    r_exp = oauth.maybe_refresh(old, env=env, now=NOW, http_post=http_ok)
    check("expired → refreshed True", r_exp.get("refreshed") is True, r_exp.get("reason"))
    check("expired → token nuevo", r_exp.get("access_token") == "NEW-TOKEN-xyz")
    check("expired → obtained_at = now", r_exp.get("obtained_at") == NOW)
    check("expired → conserva refresh_token (Google no re-emite)", r_exp.get("refresh_token") == "r1")
    check("refresh mandó grant_type=refresh_token", calls and calls[-1]["form"].get("grant_type") == "refresh_token")
    check("refresh mandó el client_secret server-side", calls and calls[-1]["form"].get("client_secret") == "the-secret")

    r_failed = oauth.maybe_refresh(old, env=env, now=NOW, http_post=http_fail)
    check("refresh_failed → refreshed False", r_failed.get("refreshed") is False, r_failed.get("reason"))
    check("refresh_failed NO expone token", "access_token" not in r_failed)

    # review F1 · el proveedor NO re-emite expires_in en el refresh (válido per RFC 6749) → NO debe
    # quedar None (dispararía renew-loop): cae a un TTL sano y NUMÉRICO.
    def http_ok_no_ttl(url, form, timeout=20):
        return 200, {"access_token": "NEW-NO-TTL"}   # sin expires_in
    r_nottl = oauth.maybe_refresh(old, env=env, now=NOW, http_post=http_ok_no_ttl)
    check("refresh sin expires_in → refreshed True", r_nottl.get("refreshed") is True, r_nottl.get("reason"))
    check("refresh sin expires_in → expires_in numérico (default sano, no None)",
          isinstance(r_nottl.get("expires_in"), (int, float)) and r_nottl["expires_in"] > 0,
          r_nottl.get("expires_in"))
    # y el companion resultante NO se considera vencido de inmediato (no hay renew-loop)
    _comp_after = {"obtained_at": NOW, "expires_in": r_nottl.get("expires_in"), "refresh_token": "r1"}
    check("tras refresh sin TTL, token_expired(now)=False (no renew-loop)",
          oauth.token_expired(_comp_after, now=NOW) is False)

    r_nort = oauth.maybe_refresh({"obtained_at": NOW - 4000, "expires_in": 3600}, env=env, now=NOW, http_post=http_ok)
    check("sin refresh_token → refreshed False", r_nort.get("refreshed") is False and r_nort.get("reason") == "no_refresh_token")

    r_nocred = oauth.maybe_refresh(old, env={}, now=NOW, http_post=http_ok)
    check("sin client creds en env → refreshed False", r_nocred.get("refreshed") is False and r_nocred.get("reason") == "no_client_creds")

    # ── B) broker._maybe_refresh_oauth con repo EN MEMORIA ──
    print("\nB) credential_broker._maybe_refresh_oauth (repo en memoria):")
    from app.phase1 import credential_broker as cb
    from app.phase1 import repo as _repo

    store = {("u1", "gmail"): "OLD-TOKEN",
             ("u1", "gmail__oauth"): json.dumps({**old})}  # companion con token vencido

    def fake_get_key(conn, user_id, provider):
        return store.get((user_id, provider))

    def fake_upsert(conn, *, user_id, provider, secret):
        store[(user_id, provider)] = secret
        return {"provider": provider}

    orig_get, orig_up = _repo.get_key, _repo.upsert_key
    orig_env = dict(os.environ)
    _repo.get_key, _repo.upsert_key = fake_get_key, fake_upsert
    os.environ["CID"], os.environ["CSEC"] = "the-client-id", "the-secret"
    # El broker llama mod.maybe_refresh(companion) SIN inyectar http_post (usa el _http_post_form
    # real, ligado como default en la firma). Para stubbear el intercambio sin red parcheamos
    # mod.refresh_access_token — maybe_refresh lo resuelve como global del módulo en cada llamada,
    # así que el parche SÍ toma (a diferencia del default de http_post). El gating de maybe_refresh
    # (token_expired, token_url, client creds del env) sigue corriendo REAL.
    mod = cb._oauth_flow()
    orig_refresh = mod.refresh_access_token

    def stub_refresh_ok(cfg, *, client_id, client_secret, refresh_token, http_post=None):
        return {"ok": True, "access_token": "NEW-TOKEN-xyz", "expires_in": 3600,
                "refresh_token": refresh_token, "status": 200}

    def stub_refresh_fail(cfg, *, client_id, client_secret, refresh_token, http_post=None):
        return {"ok": False, "status": 400}

    mod.refresh_access_token = stub_refresh_ok  # type: ignore
    try:
        out1 = cb._maybe_refresh_oauth(conn=None, user_id="u1", provider="gmail", access_token="OLD-TOKEN")
        check("broker devuelve el token NUEVO", out1 == "NEW-TOKEN-xyz", out1)
        check("re-persistió el access_token nuevo", store[("u1", "gmail")] == "NEW-TOKEN-xyz")
        comp2 = json.loads(store[("u1", "gmail__oauth")])
        # el broker no inyecta `now` → estampa time.time() real; sólo verificamos que AVANZÓ
        # respecto del obtained_at viejo (996000) — no que sea un valor de test fijo.
        check("companion re-persistido con obtained_at nuevo (avanzó)",
              isinstance(comp2.get("obtained_at"), (int, float)) and comp2["obtained_at"] > old["obtained_at"],
              comp2.get("obtained_at"))
        # 2º lookup: companion ahora fresco → still_valid → NO re-renueva (devuelve el mismo token guardado)
        out2 = cb._maybe_refresh_oauth(conn=None, user_id="u1", provider="gmail", access_token="NEW-TOKEN-xyz")
        check("2º lookup NO re-renueva (still_valid)", out2 == "NEW-TOKEN-xyz")

        # refresh fallido → conserva el token viejo
        store[("u1", "slack")] = "OLD-SLACK"
        store[("u1", "slack__oauth")] = json.dumps({**old})
        mod.refresh_access_token = stub_refresh_fail  # type: ignore
        out3 = cb._maybe_refresh_oauth(conn=None, user_id="u1", provider="slack", access_token="OLD-SLACK")
        check("refresh fallido → conserva token viejo", out3 == "OLD-SLACK")
        check("refresh fallido → NO tocó el vault", store[("u1", "slack")] == "OLD-SLACK")

        # sin companion → devuelve el token tal cual (no-op)
        store[("u1", "exa")] = "EXA-KEY"
        out4 = cb._maybe_refresh_oauth(conn=None, user_id="u1", provider="exa", access_token="EXA-KEY")
        check("sin companion → no-op (token intacto)", out4 == "EXA-KEY")
    finally:
        _repo.get_key, _repo.upsert_key = orig_get, orig_up
        mod.refresh_access_token = orig_refresh  # restaurar
        for k in ("CID", "CSEC"):
            if k not in orig_env:
                os.environ.pop(k, None)

    print()
    if _fails:
        print(f"══ ❌ {len(_fails)} CHECK(S) FALLARON: {_fails} ══\n")
        sys.exit(1)
    print("══ ✅ TODOS LOS CHECKS DEL REFRESH (ticket 9) PASARON ══\n")


if __name__ == "__main__":
    main()
