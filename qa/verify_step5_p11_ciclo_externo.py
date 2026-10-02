"""verify_step5_p11_ciclo_externo.py — EL ÚLTIMO CAMINO DE CASA 1.

Todo lo anterior se probó con `dodo wh listen` reenviando a localhost. Esto prueba lo
que eso NO puede: que Dodo alcance un servidor PÚBLICO de verdad, con su propio TLS, su
cold start y su timeout de 15 s, y que el tier cambie en la base de PRODUCCIÓN.

    python3 qa/verify_step5_p11_ciclo_externo.py preparar    → cuenta + checkout_url
    python3 qa/verify_step5_p11_ciclo_externo.py verificar   → el veredicto

Diferencias con la llave viva de P3 (que corrió local):
  · el checkout se pide al backend DESPLEGADO, no a localhost;
  · el webhook viaja por internet al endpoint público, firmado, sin CLI de por medio;
  · el tier se verifica en SUPABASE, la base de producción.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "product" / "backend"))
sys.path.insert(0, str(ROOT / "platform"))

BASE = os.environ.get("P11_BASE", "https://aleph-prod.onrender.com")
if not os.environ.get("ALEPH_QA_STATE_FILE"):
    raise SystemExit("BLOCKED: set ALEPH_QA_STATE_FILE to an isolated test-state file")
ESTADO = Path(os.environ["ALEPH_QA_STATE_FILE"]).resolve()

for line in (ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
# La base de PRODUCCIÓN. Sin esto apuntaríamos al Postgres local y el test mentiría.
os.environ["DATABASE_URL"] = os.environ["SUPABASE_DB_URL"]

# La MISMA clave Fernet que el servidor desplegado. `mint_session` cifra el token con
# ella (repo.mint_session → encrypt_secret → PUPPET_DB_ENC_KEY), así que un token
# firmado con la clave local es basura para producción: da 401 no_session. Este harness
# hace de CLIENTE de producción, y para eso necesita emitir sesiones que allá valgan.
#
# Es también la demostración de por qué esa clave tiene que ser FIJA y externa: si el
# contenedor la autogenerara, cada deploy invalidaría todas las sesiones vivas.
if not os.environ.get("PUPPET_DB_ENC_KEY"):
    _claves = Path("/tmp/claves-render.txt")
    if _claves.exists():
        for _l in _claves.read_text().splitlines():
            if _l.startswith("PUPPET_DB_ENC_KEY="):
                os.environ["PUPPET_DB_ENC_KEY"] = _l.split("=", 1)[1].strip()
if not os.environ.get("PUPPET_DB_ENC_KEY"):
    print("⚠ falta PUPPET_DB_ENC_KEY (la de producción): los tokens que emita este "
          "harness no van a valer en el servidor y todo dará 401.")

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def _req(metodo, ruta, cuerpo=None, token=None, timeout=120):
    r = urllib.request.Request(
        BASE + ruta,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
        method=metodo)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"_error": f"{type(e).__name__}: {e}"}


def preparar():
    from app.phase1 import repo

    st, cfg = _req("GET", "/v1/payments/status")
    print(f"servicio: {BASE}  status={st}  {cfg}")
    if not cfg.get("webhook_key_configurada"):
        print("\n⚠ webhook_key_configurada=false — el webhook NO va a poder verificar "
              "firmas. Agregá DODO_PAYMENTS_WEBHOOK_KEY y redeployá antes de pagar.")
        return 1

    conn = repo.get_conn()          # ← SUPABASE
    email = f"p11-{uuid.uuid4().hex[:8]}@probe.local"
    u = repo.get_or_create_user(conn, email, "Sonda P11 externa")
    uid = u["id"]
    tier_antes = repo.get_user(conn, uid)["tier"]
    token = repo.mint_session(uid)
    conn.close()

    st, s = _req("POST", "/v1/payments/checkout", {"plan": "lifetime"}, token=token)
    if st != 200 or not s.get("checkout_url"):
        print(f"ERROR: el checkout del servidor DESPLEGADO devolvió {st}: {s}")
        return 1

    ESTADO.write_text(json.dumps({"account_id": str(uid), "email": email,
                                  "tier_antes": tier_antes, "token": token,
                                  "checkout_url": s["checkout_url"]}, indent=2))
    print("\n── PREPARADO (contra el servidor PÚBLICO) ──")
    print(f"cuenta   : {uid}   tier ANTES: {tier_antes}")
    print(f"\nPAGAR ACÁ:\n{s['checkout_url']}\n")
    print("tarjeta 4242 4242 4242 4242 · 06/32 · CVV 123")
    return 0


def verificar():
    from app.phase1 import repo
    from gates import tier_gate

    st = json.loads(ESTADO.read_text())
    uid, token = st["account_id"], st["token"]
    conn = repo.get_conn()          # ← SUPABASE

    print("── EL CICLO EXTERNO ──")
    check("tier ANTES era free", st["tier_antes"] == "free")

    with conn.cursor() as cur:
        cur.execute("SELECT webhook_id, event_type, outcome, processed_at "
                    "FROM payment_webhook_events ORDER BY received_at DESC LIMIT 5")
        eventos = cur.fetchall()
    aplicados = [e for e in eventos if e[2] == "applied"]
    check("llegó un webhook desde INTERNET al servidor público y se aplicó",
          bool(aplicados), f"eventos en la DB de prod: {eventos}")
    if aplicados:
        print(f"      webhook-id={aplicados[0][0]}  tipo={aplicados[0][1]}")

    subs = repo.list_subscriptions(conn, uid)
    check("la suscripción quedó ligada a la cuenta", bool(subs), f"subs={subs}")

    tier = repo.get_user(conn, uid)["tier"]
    check(f"users.tier en PRODUCCIÓN pasó a premium (dio {tier!r})", tier == "basico")

    with conn.cursor() as cur:
        cur.execute("SELECT tier_before, tier_after, reason, webhook_id "
                    "FROM tier_audit WHERE account_id = %s::uuid ORDER BY at", (uid,))
        trail = cur.fetchall()
    check("con auditoría del webhook que lo causó",
          bool(trail) and trail[-1][3] is not None, f"trail={trail}")
    if trail:
        print(f"      {trail[-1][0]} → {trail[-1][1]}  ({trail[-1][2]})")

    live = tier_gate.resolve_account_tier(conn, uid, repo)
    check("el muro resuelve el tier desde la cuenta", live == "basico", f"dio {live!r}")

    # ── el muro, por HTTP, contra el servidor PÚBLICO ──────────────────────────
    cuerpo = {"url": "https://example.com", "forma": "abierto"}
    st_anon, _ = _req("POST", "/v1/inspect/forge", cuerpo)
    check("HTTP público · anónimo → 402", st_anon == 402, f"dio {st_anon}")

    st_pago, b_pago = _req("POST", "/v1/inspect/forge", cuerpo, token=token)
    check("HTTP público · la sesión que PAGÓ → ya no es 402",
          st_pago != 402, f"dio {st_pago} {str(b_pago)[:120]}")

    # ── el check de tier que consume el cliente ────────────────────────────────
    st_t, t = _req("GET", "/v1/payments/me/tier", token=token)
    check("GET /me/tier público devuelve premium", st_t == 200 and t.get("es_premium"),
          f"{st_t} {t}")
    if st_t == 200:
        print(f"      plan={t.get('plan')}  tier={t.get('tier')}")

    # ── limpieza: producción arranca vacía, y sigue vacía ──────────────────────
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s::uuid", (uid,))
    conn.commit()
    conn.close()
    print("\n[cuenta de sonda eliminada de producción]")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "verificar"
    sys.exit(preparar() if modo == "preparar" else verificar())
