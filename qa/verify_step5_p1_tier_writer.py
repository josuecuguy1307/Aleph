"""verify_step5_p1_tier_writer.py — LLAVE VIVA de P1 contra Postgres real.

Prueba lo que la función pura NO puede probar: que el puente pago→tier existe de
verdad en la base. Crea una cuenta desechable, la mueve por el ciclo de vida completo
y verifica que `users.tier` la sigue — y que la muralla ya certificada la reconoce.

    python3 qa/verify_step5_p1_tier_writer.py

Limpia lo que crea (ON DELETE CASCADE se lleva suscripciones y auditoría).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "product" / "backend"))
sys.path.insert(0, str(ROOT / "platform"))

from app.phase1 import repo  # noqa: E402
from gates import tier_gate  # noqa: E402

NOW = _dt.datetime.now(_dt.timezone.utc)
FUT = NOW + _dt.timedelta(days=30)
PAS = NOW - _dt.timedelta(days=30)

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def main():
    conn = repo.get_conn()
    email = f"step5-p1-{uuid.uuid4().hex[:10]}@probe.local"
    user = repo.get_or_create_user(conn, email, "Sonda P1")
    uid = user["id"]
    print(f"cuenta de sonda: {uid}\n")

    try:
        # ── 1. Punto de partida: toda cuenta nace free ──────────────────────────
        check("cuenta nueva nace free", repo.get_user(conn, uid)["tier"] == "free")

        # ── 2. EL PUENTE: una suscripción viva asciende el tier ─────────────────
        repo.upsert_subscription(
            conn, account_id=uid, processor="dodo", external_id="sub_probe_p1",
            plan="monthly", status="alta", current_period_end=FUT, event_at=NOW,
        )
        t = repo.resync_account_tier(conn, uid, reason="test:alta")
        check("suscripción viva → tier basico", t == "basico", f"dio {t!r}")
        check("persistió en users.tier", repo.get_user(conn, uid)["tier"] == "basico")

        # ── 3. La muralla YA CERTIFICADA reconoce lo que escribimos ─────────────
        # (si esto falla, escribimos premium sobre una cerca que no lo entiende)
        live = tier_gate.resolve_account_tier(conn, uid, repo)
        check("tier_gate resuelve el tier escrito", live == "basico", f"dio {live!r}")
        check("require_feature ABRE la construcción de MCPs",
              tier_gate.require_feature("mcp_construction", live) is None)
        check("require_feature ABRE el export total",
              tier_gate.require_feature("method_export_total", live) is None)

        # ── 4. Ciclo de vida: cancelación respeta el período pagado ─────────────
        repo.upsert_subscription(
            conn, account_id=uid, processor="dodo", external_id="sub_probe_p1",
            plan="monthly", status="baja", current_period_end=FUT,
            event_at=NOW + _dt.timedelta(seconds=1),
        )
        t = repo.resync_account_tier(conn, uid, reason="test:baja-con-periodo")
        check("cancelada pero con período pagado → sigue premium", t == "basico", f"dio {t!r}")

        # ── 5. Vencido el período pagado → cae a free ───────────────────────────
        repo.upsert_subscription(
            conn, account_id=uid, processor="dodo", external_id="sub_probe_p1",
            plan="monthly", status="baja", current_period_end=PAS,
            event_at=NOW + _dt.timedelta(seconds=2),
        )
        t = repo.resync_account_tier(conn, uid, reason="test:baja-vencida")
        check("período vencido → free", t == "free", f"dio {t!r}")
        rej = tier_gate.require_feature("mcp_construction", repo.get_user(conn, uid)["tier"])
        check("y la muralla vuelve a NEGAR construcción", rej is not None and rej.get("tier_gated"))

        # ── 6. ANTI-DESORDEN: un evento viejo NO pisa el estado nuevo ───────────
        # (regla 4 del §2: los webhooks no llegan en orden)
        repo.upsert_subscription(
            conn, account_id=uid, processor="dodo", external_id="sub_probe_p1",
            plan="monthly", status="alta", current_period_end=FUT,
            event_at=NOW - _dt.timedelta(days=5),      # ← MÁS VIEJO que lo aplicado
        )
        subs = repo.list_subscriptions(conn, uid)
        cur = [s for s in subs if s["external_id"] == "sub_probe_p1"][0]
        check("evento viejo NO pisa el estado nuevo", cur["status"] == "baja",
              f"quedó status={cur['status']!r} (el viejo lo pisó)")
        t = repo.resync_account_tier(conn, uid, reason="test:desorden")
        check("y el tier sigue free tras el evento desordenado", t == "free", f"dio {t!r}")

        # ── 7. El CONJUNTO manda: un lifetime convive con el mensual muerto ─────
        repo.upsert_subscription(
            conn, account_id=uid, processor="dodo", external_id="pay_probe_lifetime",
            plan="lifetime", status="alta", current_period_end=None, event_at=NOW,
        )
        t = repo.resync_account_tier(conn, uid, reason="test:lifetime")
        check("lifetime rescata a la cuenta pese al mensual vencido", t == "basico", f"dio {t!r}")

        # ── 8. IDEMPOTENCIA del webhook, decidida por el motor ─────────────────
        wid = f"msg_probe_{uuid.uuid4().hex[:12]}"
        first = repo.claim_webhook_event(
            conn, webhook_id=wid, processor="dodo", event_type="payment.succeeded",
            payload=json.dumps({"probe": True}), event_at=NOW)
        second = repo.claim_webhook_event(
            conn, webhook_id=wid, processor="dodo", event_type="payment.succeeded",
            payload=json.dumps({"probe": True}), event_at=NOW)
        check("mismo webhook-id: la 1ra vez reclama", first is True)
        check("mismo webhook-id: la 2da NO reprocesa", second is False)
        repo.close_webhook_event(conn, wid, "applied")

        # ── 9. El escritor RECHAZA un tier no escribible ────────────────────────
        try:
            repo.set_tier(conn, uid, "premium", reason="test:invalido")  # ← no es un tier real
            check("set_tier rechaza tier inválido", False, "lo aceptó")
        except ValueError:
            check("set_tier rechaza tier inválido ('premium' no es un tier)", True)

        # ── 10. AUDITORÍA: todo cambio dejó rastro ──────────────────────────────
        with conn.cursor() as cur_:
            cur_.execute(
                "SELECT tier_before, tier_after, reason FROM tier_audit "
                "WHERE account_id = %s ORDER BY at", (uid,))
            trail = cur_.fetchall()
        check("tier_audit registró los cambios reales", len(trail) >= 3,
              f"filas={len(trail)}")
        check("y ninguna fila es un no-cambio",
              all(b != a for b, a, _ in trail),
              f"trail={trail}")
        print(f"\n  rastro de auditoría: {[(b, a, r) for b, a, r in trail]}")

    finally:
        with conn.cursor() as cur_:
            cur_.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.commit()
        conn.close()
        print("\n[cuenta de sonda eliminada — cascade limpió subs y auditoría]")

    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
