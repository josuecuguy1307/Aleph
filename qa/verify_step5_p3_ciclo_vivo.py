"""verify_step5_p3_ciclo_vivo.py — LA LLAVE VIVA DE CASA 1.

El ciclo completo, punta a punta, sin nada simulado salvo que la tarjeta es de prueba:

    checkout REAL en test_mode → pago → webhook FIRMADO de Dodo → el endpoint lo procesa
    → users.tier pasa a premium → el MURO YA CERTIFICADO abre
    → y una cuenta free golpea el MISMO muro y recibe 402

Dos fases, porque el pago lo hace un humano en el browser:

    python3 qa/verify_step5_p3_ciclo_vivo.py preparar   → crea cuenta + checkout_url
    python3 qa/verify_step5_p3_ciclo_vivo.py verificar  → corre el veredicto

Requiere el backend en :8155 y `dodo wh listen` apuntándole.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "product" / "backend"))
sys.path.insert(0, str(ROOT / "platform"))

if not os.environ.get("ALEPH_QA_STATE_FILE"):
    raise SystemExit("BLOCKED: set ALEPH_QA_STATE_FILE to an isolated test-state file")
ESTADO = Path(os.environ["ALEPH_QA_STATE_FILE"]).resolve()
BACKEND = os.environ.get("P3_BACKEND", "http://127.0.0.1:8155")

for line in (ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def preparar():
    from app.phase1 import repo

    conn = repo.get_conn()
    email = f"p3-vivo-{uuid.uuid4().hex[:8]}@probe.local"
    u = repo.get_or_create_user(conn, email, "Sonda P3 viva")
    uid = u["id"]
    tier_antes = repo.get_user(conn, uid)["tier"]

    # cuenta de CONTRASTE: nunca paga, tiene que seguir mordiendo el muro al final
    ufree = repo.get_or_create_user(conn, f"p3-free-{uuid.uuid4().hex[:8]}@probe.local", "Sonda free")
    conn.close()

    # P4: el harness usa el ENDPOINT REAL, como lo usará el front — ya no importa el
    # SDK. El account_id ni se manda: sale de la sesión, que es justo lo que queremos
    # ejercitar. (Antes esto llamaba al SDK directo y era una excepción del §4-bis.)
    token = repo.mint_session(uid)
    st_code, s = _post("/v1/payments/checkout", {"plan": "lifetime"}, token=token)
    if st_code != 200 or not s.get("checkout_url"):
        print(f"ERROR: el endpoint de checkout devolvió {st_code}: {s}")
        return 1

    ESTADO.write_text(json.dumps({
        "account_id": str(uid), "email": email, "tier_antes": tier_antes,
        "free_account_id": str(ufree["id"]),
        "session_id": s.get("session_id"), "checkout_url": s.get("checkout_url"),
    }, indent=2))

    print("── PREPARADO ──")
    print(f"cuenta de prueba : {uid}")
    print(f"tier ANTES       : {tier_antes}")
    print(f"cuenta free      : {ufree['id']} (contraste, nunca paga)")
    print(f"\nPAGAR ACÁ:\n{s.get('checkout_url')}\n")
    print("tarjeta 4242 4242 4242 4242 · 06/32 · CVV 123")


def _post(path, body, token=None):
    req = urllib.request.Request(
        f"{BACKEND}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST")
    def _leer(resp):
        crudo = resp.read() or b""
        try:
            return json.loads(crudo or b"{}")
        except Exception:
            # La forja real no siempre responde JSON (puede ser SSE o cuerpo vacío).
            # Acá sólo nos importa el CÓDIGO, así que el cuerpo se devuelve tal cual.
            return {"_crudo": crudo[:200].decode("utf-8", "replace")}

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, _leer(r)
    except urllib.error.HTTPError as e:
        return e.code, _leer(e)
    except Exception as e:
        return -1, {"_error": f"{type(e).__name__}: {e}"}


ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def verificar():
    from app.phase1 import repo
    from gates import tier_gate

    st = json.loads(ESTADO.read_text())
    uid, ufree = st["account_id"], st["free_account_id"]
    conn = repo.get_conn()

    print("── EL CICLO ──")
    check("tier ANTES del pago era free", st["tier_antes"] == "free")

    # 1 · el webhook llegó, verificado y aplicado
    with conn.cursor() as cur:
        cur.execute(
            "SELECT webhook_id, event_type, outcome, processed_at "
            "FROM payment_webhook_events ORDER BY received_at DESC LIMIT 5")
        eventos = cur.fetchall()
    aplicados = [e for e in eventos if e[2] == "applied"]
    check("llegó un webhook REAL de Dodo y se aplicó", bool(aplicados),
          f"últimos eventos: {eventos}")
    if aplicados:
        print(f"      webhook-id={aplicados[0][0]}  tipo={aplicados[0][1]}")

    # 2 · la suscripción quedó registrada contra ESTA cuenta
    subs = repo.list_subscriptions(conn, uid)
    check("la suscripción quedó ligada a la cuenta (metadata → account_id)", bool(subs),
          f"subs={subs}")
    if subs:
        print(f"      plan={subs[0]['plan']}  status={subs[0]['status']}  "
              f"external_id={subs[0]['external_id']}")

    # 3 · EL MOMENTO: users.tier ascendió
    tier = repo.get_user(conn, uid)["tier"]
    check(f"users.tier pasó de free a premium (dio {tier!r})", tier == "basico")

    # 4 · con rastro de por qué
    with conn.cursor() as cur:
        cur.execute("SELECT tier_before, tier_after, reason, webhook_id "
                    "FROM tier_audit WHERE account_id = %s ORDER BY at", (uid,))
        trail = cur.fetchall()
    check("y quedó auditado con el webhook que lo causó",
          bool(trail) and trail[-1][3] is not None, f"trail={trail}")
    if trail:
        print(f"      {trail[-1][0]} → {trail[-1][1]}  ({trail[-1][2]})")

    # 5 · EL MURO YA CERTIFICADO ABRE
    live = tier_gate.resolve_account_tier(conn, uid, repo)
    check("el muro resuelve el tier desde la CUENTA", live == "basico", f"dio {live!r}")
    check("→ MURO DE CONSTRUCCIÓN ABRE (mcp_construction)",
          tier_gate.require_feature("mcp_construction", live) is None)
    check("→ MURO DE EXPORT TOTAL ABRE (method_export_total)",
          tier_gate.require_feature("method_export_total", live) is None)
    check("→ BUS DE MEMORIA COMPARTIDA ABRE (shared_memory_bus)",
          tier_gate.require_feature("shared_memory_bus", live) is None)

    # 6 · CONTRASTE: el mismo muro sigue mordiendo a una cuenta free
    tfree = tier_gate.resolve_account_tier(conn, ufree, repo)
    check("la cuenta de contraste sigue free", tfree == "free", f"dio {tfree!r}")
    rej = tier_gate.require_feature("mcp_construction", tfree)
    check("→ y el MISMO muro la RECHAZA (el muro no se abrió para todos)",
          rej is not None and rej.get("tier_gated") is True)
    if rej:
        print(f"      rechazo honesto: {rej.get('error', '')[:90]}…")
        check("→ el rechazo nombra el tier mínimo (upsell honesto, no error mudo)",
              rej.get("min_tier") == "basico")

    # 7 · y el muro muerde de verdad por HTTP, no sólo en la función.
    #     El body tiene que ser COMPLETO: forge_router valida la forma (url/cred/login)
    #     ANTES del gate de tier (:610-624 vs :628), así que un body incompleto muere
    #     en 400/422 sin llegar al muro y no probaría nada. `forma="abierto"` es la
    #     única que no pide credencial. (No es bypass: con 400 tampoco se forja nada.)
    cuerpo_valido = {"url": "https://example.com", "forma": "abierto"}
    st_code, body = _post("/v1/inspect/forge", cuerpo_valido)
    check("HTTP /v1/inspect/forge ANÓNIMO → 402 (fail-closed en el borde)",
          st_code == 402, f"dio {st_code} {str(body)[:140]}")

    # 8 · y el mismo endpoint, con la sesión de quien PAGÓ, pasa el gate.
    #     (No pedimos 200: la forja real necesita un servicio de verdad. Pedimos que
    #     NO sea 402 — o sea, que el muro dejó pasar a quien pagó.)
    token = repo.mint_session(uid)
    st_pago, body_pago = _post("/v1/inspect/forge", cuerpo_valido, token=token)
    check("HTTP mismo endpoint CON la sesión que pagó → ya no es 402",
          st_pago != 402, f"dio {st_pago} {str(body_pago)[:140]}")

    conn.close()
    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "verificar"
    sys.exit(preparar() if modo == "preparar" else verificar())
