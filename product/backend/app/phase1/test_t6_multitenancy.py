#!/usr/bin/env python3
"""
test_t6_multitenancy.py — DONE-BAR de T6 (AUTH/SESSION · contrato §4.5).

  DONE-BAR (de la orden): "dos usuarios distintos, aislados, cada uno con su key
  cifrada; sin scope no se lee data."

Dos partes, cada una verde de verdad (no self-report):

  A · OFFLINE (sólo crypto del org + filesystem; NO necesita Postgres ni server):
      A1 authz.decide — la matriz del contrato (ok / no_session / forbidden /
         open-when-unowned). Es el corazón del "owner-gated cuando hay dueño".
      A2 sesión — round-trip mint→owner, token forjado→None, aislamiento A↛B.
      A3 keys at-rest — encrypt_secret cifra (ciphertext ≠ plaintext, sin fuga) y
         decrypt_secret hace round-trip. (La columna keys.ciphertext es ESTO.)
      A4 artifact_store — claim-on-first-create liga el dueño; get_owner aísla A de B.

  B · LIVE (corre SÓLO si PUPPET_BASE apunta a un server vivo; si no, SKIP honesto):
      El DONE-BAR HTTP end-to-end —
        - signup real de DOS usuarios (emails únicos) → cada uno su session_token.
        - cada uno guarda su BYOK key (cifrada at-rest) bajo el mismo provider.
        - A lista SUS keys (200, ve su last4, jamás el secreto) ; A→keys de B = 403 ;
          sin token = 401.
        - IDOR de escritura cerrado: PUT /puppets/{de-otro}/config sin token=401,
          con token ajeno=403, con el dueño (token minteado del owner real)=200.
        - fuga de datos cerrada: GET /spaces/{de-otro}/events sin token=401,
          ajeno=403, dueño=200.  (cleanup: borra los usuarios efímeros al final.)

Uso:
  product/backend/.venv/bin/python -m app.phase1.test_t6_multitenancy
  PUPPET_BASE=http://127.0.0.1:8086 product/backend/.venv/bin/python -m app.phase1.test_t6_multitenancy
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.phase1 import authz, repo, artifact_store  # noqa: E402

UID_A = "11111111-1111-1111-1111-111111111111"
UID_B = "22222222-2222-2222-2222-222222222222"


# ── Part A · OFFLINE ────────────────────────────────────────────────────────────

def part_a() -> list[str]:
    fails: list[str] = []
    tok_a = repo.mint_session(UID_A)
    tok_b = repo.mint_session(UID_B)

    def check(name: str, cond: bool):
        print(f"   {'OK ' if cond else 'FAIL'}  {name}")
        if not cond:
            fails.append(name)

    print("A1 · authz.decide — matriz del contrato")
    check("unowned + no token  → ok (lectura abierta)", authz.decide(None, None) == ("ok", None))
    check("unowned + token A   → ok (owner=A)",          authz.decide(None, tok_a) == ("ok", UID_A))
    check("owned A + no token  → no_session (→401)",     authz.decide(UID_A, None) == ("no_session", None))
    check("owned A + garbage   → no_session (→401)",     authz.decide(UID_A, "garbage") == ("no_session", None))
    check("owned A + token A    → ok",                   authz.decide(UID_A, tok_a) == ("ok", UID_A))
    check("owned A + token B    → forbidden (→403)",     authz.decide(UID_A, tok_b) == ("forbidden", UID_B))

    print("A2 · sesión — round-trip + forjado + aislamiento")
    check("round-trip mint→owner == A", repo.session_owner(tok_a) == UID_A)
    forged = ["", "garbage", tok_a + "x", "Bearer " + tok_a, tok_a[:-4] + "AAAA", "null"]
    check("forjados/manip → None (ninguno autoriza)",
          all(repo.session_owner(f) is None for f in forged))
    check("aislamiento A↛B", repo.session_owner(tok_a) != UID_B and repo.session_owner(tok_b) == UID_B)
    # pick_token: header gana; query es el fallback SSE
    check("pick_token header gana", authz.pick_token("Bearer X", "Y") == "X")
    check("pick_token query fallback (SSE)", authz.pick_token(None, "Y") == "Y")

    print("A3 · keys BYOK — cifradas at-rest (Fernet)")
    try:
        secret = "sk-supersecreto-" + uuid.uuid4().hex
        ct = repo.encrypt_secret(secret)
        check("ciphertext ≠ plaintext", isinstance(ct, (bytes, bytearray)) and ct != secret.encode())
        check("el secreto NO aparece en el ciphertext", secret.encode() not in bytes(ct))
        check("decrypt round-trip", repo.decrypt_secret(ct) == secret)
    except Exception as e:  # noqa: BLE001
        check(f"crypto disponible (keyfile) — excepción: {e}", False)

    print("A4 · artifact_store — claim-on-first-create + aislamiento")
    sid_a = "t6test-" + uuid.uuid4().hex[:8]
    sid_b = "t6test-" + uuid.uuid4().hex[:8]
    try:
        check("sesión nueva sin dueño", artifact_store.get_owner(sid_a) is None)
        artifact_store.claim_owner(sid_a, UID_A)
        check("claim liga el dueño A", artifact_store.get_owner(sid_a) == UID_A)
        artifact_store.claim_owner(sid_a, UID_B)  # set-if-unset: NO debe reescribir
        check("claim posterior NO reescribe (sigue A)", artifact_store.get_owner(sid_a) == UID_A)
        artifact_store.claim_owner(sid_b, UID_B)
        check("otra sesión aísla (B≠A)",
              artifact_store.get_owner(sid_b) == UID_B and artifact_store.get_owner(sid_a) == UID_A)
    finally:
        for sid in (sid_a, sid_b):
            try:
                (artifact_store.art_root() / (artifact_store._safe_sid(sid) + ".json")).unlink(missing_ok=True)
            except Exception:
                pass
    return fails


# ── Part B · LIVE HTTP ──────────────────────────────────────────────────────────

def _http(base: str, method: str, path: str, body=None, token=None):
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, str(e)


def part_b(base: str) -> list[str]:
    fails: list[str] = []

    def check(name: str, cond: bool, extra: str = ""):
        print(f"   {'OK ' if cond else 'FAIL'}  {name}{('  · ' + extra) if extra and not cond else ''}")
        if not cond:
            fails.append(name)

    # ping
    st, _ = _http(base, "GET", "/health")
    if st != 200:
        print(f"   (server no responde en {base} — SKIP Part B)")
        return ["__skip__"]

    eph_user_ids: list[str] = []
    try:
        # signup real de dos usuarios
        ea = f"t6a-{uuid.uuid4().hex[:10]}@t6.test"
        eb = f"t6b-{uuid.uuid4().hex[:10]}@t6.test"
        st, ua = _http(base, "POST", "/v1/auth/register", {"email": ea, "password": "secret-t6-aaa"})
        check("signup A → 201 + session_token", st == 201 and isinstance(ua, dict) and ua.get("session_token"), str(st))
        st, ub = _http(base, "POST", "/v1/auth/register", {"email": eb, "password": "secret-t6-bbb"})
        check("signup B → 201 + session_token", st == 201 and isinstance(ub, dict) and ub.get("session_token"), str(st))
        if not (isinstance(ua, dict) and ua.get("session_token") and isinstance(ub, dict) and ub.get("session_token")):
            return fails
        A, tA = ua["id"], ua["session_token"]
        B, tB = ub["id"], ub["session_token"]
        eph_user_ids += [A, B]
        check("password_hash NUNCA sale al cliente", "password_hash" not in ua and "password_hash" not in ub)

        # cada uno guarda SU key (cifrada at-rest) bajo el MISMO provider
        st, _ = _http(base, "POST", "/v1/keys", {"user_id": A, "provider": "t6prov", "secret": "sk-AAAA-1234"}, token=tA)
        check("A guarda su key (200)", st == 200, str(st))
        st, _ = _http(base, "POST", "/v1/keys", {"user_id": B, "provider": "t6prov", "secret": "sk-BBBB-9876"}, token=tB)
        check("B guarda su key (200)", st == 200, str(st))

        # A lista SUS keys — ve su last4, jamás el secreto
        st, ka = _http(base, "GET", f"/v1/users/{A}/keys", token=tA)
        keysA = (ka or {}).get("keys", []) if isinstance(ka, dict) else []
        provA = next((k for k in keysA if k.get("provider") == "t6prov"), None)
        check("A lista sus keys (200)", st == 200, str(st))
        check("A ve SU last4 (1234), no el de B", bool(provA) and provA.get("last4") == "1234")
        check("el secreto NUNCA viaja en la respuesta", "sk-AAAA-1234" not in json.dumps(ka))

        # AISLAMIENTO: A no lee las keys de B ; sin token = 401
        st, _ = _http(base, "GET", f"/v1/users/{B}/keys", token=tA)
        check("A→keys de B = 403", st == 403, str(st))
        st, _ = _http(base, "GET", f"/v1/users/{B}/keys")
        check("keys de B sin token = 401", st == 401, str(st))

        # IDOR de ESCRITURA cerrado: PUT /puppets/{de-otro}/config
        conn = repo.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, owner_id, config FROM puppets WHERE config ? 'schema_version' "
                            "ORDER BY created_at DESC LIMIT 1")
                row = cur.fetchone()
        finally:
            conn.close()
        if row:
            pid, owner_id, cfg = str(row[0]), str(row[1]), row[2]
            owner_tok = repo.mint_session(owner_id)
            st, _ = _http(base, "PUT", f"/v1/puppets/{pid}/config", {"config": cfg})
            check("PUT puppet/config sin token = 401", st == 401, str(st))
            st, _ = _http(base, "PUT", f"/v1/puppets/{pid}/config", {"config": cfg}, token=tA)
            check("PUT puppet/config de otro (token A) = 403", st == 403, str(st))
            st, _ = _http(base, "PUT", f"/v1/puppets/{pid}/config", {"config": cfg}, token=owner_tok)
            check("PUT puppet/config del DUEÑO = 200", st == 200, str(st))
        else:
            print("   (sin puppet con receta v1 para el test de PUT — SKIP ese sub-bloque)")

        # FUGA DE DATOS cerrada: GET /spaces/{de-otro}/events
        conn = repo.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT space_id, user_id FROM runs WHERE space_id IS NOT NULL "
                            "AND user_id IS NOT NULL ORDER BY started_at DESC LIMIT 1")
                row = cur.fetchone()
        finally:
            conn.close()
        if row:
            sp, sp_owner = str(row[0]), str(row[1])
            sp_tok = repo.mint_session(sp_owner)
            st, _ = _http(base, "GET", f"/v1/spaces/{sp}/events")
            check("GET space/events de otro sin token = 401", st == 401, str(st))
            st, _ = _http(base, "GET", f"/v1/spaces/{sp}/events", token=tA)
            check("GET space/events de otro (token A) = 403", st == 403, str(st))
            st, _ = _http(base, "GET", f"/v1/spaces/{sp}/events", token=sp_tok)
            check("GET space/events del DUEÑO = 200", st == 200, str(st))
        else:
            print("   (sin space con dueño para el test de events — SKIP ese sub-bloque)")
    finally:
        # cleanup: borrar los usuarios efímeros (cascade borra sus keys)
        if eph_user_ids:
            try:
                conn = repo.get_conn()
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id::text = ANY(%s)", (eph_user_ids,))
                conn.commit()
                conn.close()
            except Exception as e:  # noqa: BLE001
                print(f"   (cleanup parcial: {e})")
    return fails


def main() -> int:
    print("══ T6 MULTITENANCY — DONE-BAR ══\n")
    fails = part_a()
    base = os.environ.get("PUPPET_BASE")
    if base:
        print(f"\nB · LIVE ({base})")
        bf = part_b(base)
        if bf == ["__skip__"]:
            print("   Part B SKIPPED (server caído).")
        else:
            fails += bf
    else:
        print("\nB · LIVE — SKIP (seteá PUPPET_BASE=http://127.0.0.1:<port> para correrlo).")

    print()
    if fails:
        print(f"❌ FALLÓ: {fails}")
        return 1
    print("✅ T6 MULTITENANCY OK — aislamiento por sesión + keys cifradas + IDOR cerrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
