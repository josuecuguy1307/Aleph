#!/usr/bin/env python3
"""
test_login_suave.py — EVIDENCIA REAL del slice LOGIN SUAVE (la .app free trabaja
100% local SIN cuenta; el login se ofrece solo cuando el dato sale de la máquina).

Qué prueba (contra la app FastAPI REAL + Postgres puppet_ai vivo — cero mocks):

  (a) PUERTA SIN LOGIN · POST /v1/auth/local mint la sesión del EQUIPO (device user,
      email centinela device::, anon=true) sin credenciales; con ella se ARMA Y GUARDA
      un agente real (receta validada); "relanzar" (nueva llamada sin header) devuelve
      LA MISMA identidad y el token viejo sigue vivo (Fernet stateless) → el agente
      sigue ahí. Cero login. + tripwire estático: Home ya no tiene el gate duro.
  (b) PREMIUM SIN CUENTA · /v1/billing/checkout con sesión device → 403 tipado
      `account_required` (rechazo honesto que invita al login); el meter local sigue 200.
  (c) FUSIÓN · device user aislado con puppet+key → register cuenta → /v1/auth/merge-local
      (capability doble: Bearer cuenta + token local en el body) → todo aparece bajo la
      cuenta, el device user muere, re-merge da 400 honesto. Negativos anti-abuso:
      token basura → 400 · token de OTRA CUENTA como "local" → 400 not_a_device_user
      (jamás se traga una cuenta real).
  (d) FRONTERA · ALEPH_ROLE=control → /v1/auth/local y /v1/auth/merge-local NO existen
      (404): en el control plane multi-tenant no hay "usuario de equipo".
  (e) HIGIENE · register/login jamás alcanzan un email device:: (400).

    (cd product/backend && .venv/bin/python -m app.phase1.test_login_suave)
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("PUPPET_WORKERS", "0")   # la suite no spinnea workers
# [port a step5] En step5 el billing_router se monta SOLO en control (Casa 2 · 2.0: sus 4
# tablas NUNCA salen del plano de control; el cliente SQLite no las tiene). El bloque (b),
# muro premium, necesita /v1/billing/* montado → se IMPORTA la app en rol control (monta
# billing contra el Postgres real) y se vuelve a client en runtime: auth_local chequea el
# rol POR-REQUEST (_es_control_plane), no al importar, así que la sesión local sigue viva.
# El bloque (d) re-activa control en runtime para probar la frontera. (En reel billing se
# montaba en cualquier rol; en step5 hay que decir en qué rol vive cada endpoint.)
os.environ["ALEPH_ROLE"] = "control"           # IMPORT: monta billing (muro premium testeable)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app                    # noqa: E402  (la app REAL, wiring completo)
from app.phase1 import repo                 # noqa: E402

os.environ.pop("ALEPH_ROLE", None)             # RUNTIME: client → /v1/auth/local disponible (chequeo por-request)

client = TestClient(app, base_url="http://127.0.0.1")  # Host loopback = frontera real

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def _recipe(name: str) -> dict:
    """Receta v1 mínima VÁLIDA (misma forma que qa/verify_e2e_8080.py, belt real en repo)."""
    return {
        "schema_version": "v1",
        "meta": {"name": name, "nicho": "educacion"},
        "model": {"primary": "specialist", "base_url": "http://127.0.0.1:4000/v1",
                  "temperature": 0, "max_tokens": 512, "max_turns": 3},
        "belt": {"belt_ref": "catalog/belts/stem.md",
                 "tool_filters": {"units": ["units_check"]}},
        "framing": {"inline": "Tutor riguroso de prueba (login suave)."},
        "rag": {"enabled": False}, "keys": {},
        "gates": {"money_touch": "off", "send": "off"},
    }


def main() -> int:  # noqa: PLR0915
    cleanup_user_ids: list[str] = []
    cleanup_puppet_ids: list[str] = []

    # ── (e) HIGIENE: el centinela device:: es inalcanzable por register/login ──────
    print("── (e) higiene del centinela device:: ──")
    r = client.post("/v1/auth/register", json={"email": "device::x", "password": "123456"})
    check("register con email device:: → 400", r.status_code == 400, str(r.status_code))
    r = client.post("/v1/auth/login", json={"email": "device::loquesea"})
    check("login legacy (sin password) device:: → 400", r.status_code == 400, str(r.status_code))

    # ── (a) PUERTA SIN LOGIN: mint anónimo local + armar/guardar + relanzar ────────
    print("── (a) sesión local anónima: abrir → armar → relanzar ──")
    # DNS rebinding y procesos ajenos no conocen la capability efímera del launch.
    from app.launch_cap import install as install_launch_cap
    install_launch_cap("test-launch-capability")
    os.environ["ALEPH_SIDECAR_PORT"] = "80"
    r_bad_host = client.post("/v1/auth/local", headers={
        "Host": "attacker.example", "X-Aleph-Launch": "test-launch-capability"})
    check("auth/local rechaza Host no-loopback", r_bad_host.status_code == 403,
          r_bad_host.text[:200])
    r_bad_origin = client.post("/v1/auth/local", headers={
        "Origin": "https://attacker.example", "X-Aleph-Launch": "test-launch-capability"})
    check("auth/local rechaza Origin no-loopback", r_bad_origin.status_code == 403,
          r_bad_origin.text[:200])
    r_no_cap = client.post("/v1/auth/local")
    check("auth/local exige capability cuando el shell la configuró", r_no_cap.status_code == 403,
          r_no_cap.text[:200])
    r = client.post("/v1/auth/local", headers={"X-Aleph-Launch": "test-launch-capability"})
    client.headers.update({"X-Aleph-Launch": "test-launch-capability"})
    check("POST /v1/auth/local con frontera local válida → 200",
          r.status_code == 200, r.text[:200])
    if r.status_code != 200:
        print("❌ sin sesión local no hay nada más que probar");  return 1
    u1 = r.json()
    tok1 = u1.get("session_token") or ""
    check("la sesión viene anónima (anon=true)", u1.get("anon") is True)
    check("identidad = device user (email device::…)",
          str(u1.get("email") or "").startswith("device::"), str(u1.get("email")))
    check("sin password_hash en la respuesta", "password_hash" not in u1)

    # armar y GUARDAR un agente real con la sesión anónima (receta validada de verdad)
    pname = f"Aleph login-suave {uuid.uuid4().hex[:6]}"
    r = client.post("/v1/puppets", headers={"Authorization": f"Bearer {tok1}"},
                    json={"owner_id": u1["id"], "name": pname, "nicho": "educacion",
                          "config": _recipe(pname)})
    check("guardar agente con sesión anónima → 201", r.status_code == 201, r.text[:300])
    pid = r.json().get("id") if r.status_code == 201 else None
    if pid:
        cleanup_puppet_ids.append(pid)

    # "relanzar": nueva llamada SIN header → LA MISMA identidad de equipo
    r = client.post("/v1/auth/local")
    u2 = r.json() if r.status_code == 200 else {}
    check("relanzar (nuevo /auth/local) → misma identidad", u2.get("id") == u1["id"],
          f"{u2.get('id')} vs {u1['id']}")
    # el token PREVIO sigue vivo (stateless) y el agente SIGUE AHÍ — cero login
    r = client.get(f"/v1/users/{u1['id']}/puppets", headers={"Authorization": f"Bearer {tok1}"})
    names = [p.get("name") for p in (r.json().get("puppets") if isinstance(r.json(), dict)
                                     else r.json())] if r.status_code == 200 else []
    check("token pre-relaunch sigue válido y el agente sigue ahí",
          r.status_code == 200 and pname in names, f"{r.status_code} {names[:3]}")

    # tripwire estático: la puerta de Home ya no patea a Auth incondicionalmente
    home = (_BACKEND.parent / "app" / "design" / "Home.dc.html").read_text(encoding="utf-8")
    check("Home.dc.html: gate duro eliminado",
          "location.replace('Auth.dc.html'); return; } }catch(e){}" not in home)
    check("Home.dc.html: usa ensureLocal (sesión local primero)", "ensureLocal" in home)

    # ── (b) PREMIUM SIN CUENTA: rechazo honesto que invita al login ────────────────
    # [port a step5] El billing vive en el PLANO DE CONTROL (Postgres): sus 4 tablas NO
    # existen en el SQLite del cliente (Casa 2 · 2.0). El muro premium se prueba, entonces,
    # DONDE el billing corre — rol control — con un device user creado en ese plano. En reel
    # billing y usuarios compartían un plano; en step5 están separados a propósito, así que
    # se dice explícitamente en qué rol vive el muro. (La property es la misma: una sesión
    # local/anónima es válida para trabajar pero NO para comprar → 403 account_required.)
    print("── (b) muro premium con sesión anónima (plano de control) ──")
    os.environ["ALEPH_ROLE"] = "control"   # billing → Postgres (donde viven sus tablas)
    dev_pre = None
    try:
        conn = repo.get_conn()             # control → Postgres
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (email, display_name, tier) VALUES (%s,%s,%s) RETURNING id",
                            (f"device::premium-{uuid.uuid4().hex}", "Equipo (muro premium)", "free"))
                dev_pre = str(cur.fetchone()[0])
            conn.commit()
        finally:
            conn.close()
        tok_pre = repo.mint_session(dev_pre)
        r = client.post("/v1/billing/checkout", headers={"Authorization": f"Bearer {tok_pre}"},
                        json={"user_id": dev_pre, "amount_usd": 5})
        err = (r.json().get("detail") or {}).get("error") if r.status_code == 403 else None
        check("checkout con device user → 403 account_required",
              r.status_code == 403 and err == "account_required", f"{r.status_code} {r.text[:200]}")
        r = client.get(f"/v1/billing/meter/{dev_pre}", headers={"Authorization": f"Bearer {tok_pre}"})
        check("el meter local sigue funcionando para la sesión anónima", r.status_code == 200,
              str(r.status_code))
    finally:
        if dev_pre:
            try:
                conn = repo.get_conn()     # aún control → Postgres: limpiar el device de prueba
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id = %s", (dev_pre,))
                conn.commit(); conn.close()
            except Exception:
                pass
        os.environ.pop("ALEPH_ROLE", None)  # runtime vuelve a client (SQLite) para (c)/(d)

    # ── (c) FUSIÓN: device aislado → cuenta (capability doble) + negativos ─────────
    print("── (c) fusión device → cuenta ──")
    # device user AISLADO (no el compartido del equipo: el test no toca esa identidad)
    conn = repo.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (email, display_name, tier) VALUES (%s,%s,%s) RETURNING id",
                        (f"device::test-{uuid.uuid4().hex}", "Equipo de prueba", "free"))
            dev_id = str(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    tok_dev = repo.mint_session(dev_id)
    r = client.post("/v1/puppets", headers={"Authorization": f"Bearer {tok_dev}"},
                    json={"owner_id": dev_id, "name": "Aleph fusion", "nicho": "educacion",
                          "config": _recipe("Aleph fusion")})
    check("puppet bajo device aislado → 201", r.status_code == 201, r.text[:200])
    r = client.post("/v1/keys", headers={"Authorization": f"Bearer {tok_dev}"},
                    json={"user_id": dev_id, "provider": "prueba-fusion", "secret": "sk-local-123456"})
    check("key BYOK bajo device aislado → 200", r.status_code == 200, r.text[:200])

    email_a = f"login-suave-{uuid.uuid4().hex[:10]}@test.local"
    r = client.post("/v1/auth/register", json={"email": email_a, "password": "secreta9"})
    check("register cuenta A → 201", r.status_code == 201, r.text[:200])
    acc = r.json();  tok_a = acc.get("session_token") or "";  cleanup_user_ids.append(acc.get("id"))

    # negativos ANTES de fusionar
    r = client.post("/v1/auth/merge-local", headers={"Authorization": f"Bearer {tok_a}"},
                    json={"local_token": "basura"})
    check("merge con token basura → 400", r.status_code == 400, str(r.status_code))
    email_b = f"login-suave-{uuid.uuid4().hex[:10]}@test.local"
    rb = client.post("/v1/auth/register", json={"email": email_b, "password": "secreta9"})
    tok_b = rb.json().get("session_token") or "";  cleanup_user_ids.append(rb.json().get("id"))
    r = client.post("/v1/auth/merge-local", headers={"Authorization": f"Bearer {tok_a}"},
                    json={"local_token": tok_b})
    err = (r.json().get("detail") or {}).get("error") if r.status_code == 400 else None
    check("merge de una CUENTA como 'local' → 400 not_a_device_user (no se traga cuentas)",
          r.status_code == 400 and err == "not_a_device_user", f"{r.status_code} {err}")
    r = client.post("/v1/auth/merge-local", json={"local_token": tok_dev})
    check("merge sin sesión de cuenta → 401", r.status_code == 401, str(r.status_code))

    # la FUSIÓN real
    r = client.post("/v1/auth/merge-local", headers={"Authorization": f"Bearer {tok_a}"},
                    json={"local_token": tok_dev})
    body = r.json() if r.status_code == 200 else {}
    moved = body.get("moved") or {}
    check("merge-local → 200 merged", r.status_code == 200 and body.get("merged") is True,
          r.text[:300])
    check("movió el puppet y la key", moved.get("puppets", 0) >= 1 and moved.get("keys", 0) >= 1,
          str(moved))
    r = client.get(f"/v1/users/{acc['id']}/puppets", headers={"Authorization": f"Bearer {tok_a}"})
    names = [p.get("name") for p in (r.json().get("puppets") if isinstance(r.json(), dict)
                                     else r.json())] if r.status_code == 200 else []
    check("el agente del device aparece bajo la cuenta", "Aleph fusion" in names, str(names[:5]))
    r = client.get(f"/v1/users/{acc['id']}/keys", headers={"Authorization": f"Bearer {tok_a}"})
    provs = [k.get("provider") for k in (r.json() if isinstance(r.json(), list)
                                         else r.json().get("keys", []))] if r.status_code == 200 else []
    check("la key del device aparece bajo la cuenta", "prueba-fusion" in provs, str(provs[:5]))
    # el device user murió; re-merge da 400 honesto; su token viejo no resucita filas
    conn = repo.get_conn()
    try:
        gone = repo.get_user(conn, dev_id) is None
    finally:
        conn.close()
    check("el device user aislado ya no existe", gone)
    r = client.post("/v1/auth/merge-local", headers={"Authorization": f"Bearer {tok_a}"},
                    json={"local_token": tok_dev})
    err = (r.json().get("detail") or {}).get("error") if r.status_code == 400 else None
    check("re-merge del mismo token → 400 no_device_user (idempotencia honesta)",
          r.status_code == 400 and err == "no_device_user", f"{r.status_code} {err}")

    # ── (d) FRONTERA: en el control plane estos endpoints NO existen ───────────────
    print("── (d) frontera ALEPH_ROLE=control ──")
    os.environ["ALEPH_ROLE"] = "control"
    try:
        r1 = client.post("/v1/auth/local")
        r2 = client.post("/v1/auth/merge-local", headers={"Authorization": f"Bearer {tok_a}"},
                         json={"local_token": "x"})
        check("control: /v1/auth/local → 404", r1.status_code == 404, str(r1.status_code))
        check("control: /v1/auth/merge-local → 404", r2.status_code == 404, str(r2.status_code))
    finally:
        os.environ.pop("ALEPH_ROLE", None)

    # ── limpieza (solo lo que ESTE test creó; jamás el device user compartido) ─────
    conn = repo.get_conn()
    try:
        with conn.cursor() as cur:
            for pid in cleanup_puppet_ids:
                cur.execute("DELETE FROM puppets WHERE id = %s", (pid,))
            for uid in [x for x in cleanup_user_ids if x]:
                cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.commit()
    finally:
        conn.close()

    print()
    if FAILS:
        print(f"❌ LOGIN SUAVE: {len(FAILS)} chequeo(s) fallaron: {FAILS}")
        return 1
    print("✅ LOGIN SUAVE: puerta sin login + persistencia + muro premium honesto + "
          "fusión device→cuenta + frontera de rol — todo contra la app y la DB reales")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
