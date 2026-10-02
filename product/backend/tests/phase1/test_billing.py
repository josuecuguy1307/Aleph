"""
test_billing.py — T7-billing: metering + cap + Stripe. Tests REALES (cero mocks de comportamiento).

Tres capas:
  1. OFFLINE — normalización del COST-EVENT (§4.6) al ledger + mapeo de Stripe + caps por tier.
     No tocan DB ni red.
  2. DB — contra el Postgres real puppet_ai (skip honesto si no está): metering, idempotencia
     por run_id, corte por cap, top-up de crédito, anónimo no-factura, usd null no suma.
  3. HTTP — vía TestClient sobre el router real: authz (§4.5) 401/403/200, preflight 402, y
     EL DONE-BAR sobre el endpoint REAL de run: un usuario sobre el cap → POST /v1/puppets/run
     responde 402 ANTES de gastar cognición (no funde la cuenta).
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.phase1 import billing, stripe_billing
from app.phase1.router import build_phase1_router
from app.phase1.billing_router import build_billing_router


def _db_available() -> bool:
    try:
        from app.phase1 import repo
        conn = repo.get_conn(); conn.close()
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


# ════════════════════════ 1. OFFLINE ════════════════════════

def test_ledger_row_normalizes_model_event():
    evt = {"type": "cost", "kind": "model", "user_id": "u", "run_id": "r",
           "model": "openai/gpt-oss-120b",
           "tokens": {"prompt": 562, "completion": 119, "total": 681},
           "tokens_measured": True, "usd": 0.0001557, "price_source": "groq"}
    row = billing._ledger_row_from_event(evt)
    assert row["kind"] == "model" and row["model"] == "openai/gpt-oss-120b"
    assert row["prompt_tokens"] == 562 and row["total_tokens"] == 681
    assert row["usd"] == "0.0001557" and row["tokens_measured"] is True


def test_ledger_row_tool_event_and_null_usd():
    tool = billing._ledger_row_from_event(
        {"type": "cost", "kind": "tool", "tool": "get_financials", "server": "secedgar",
         "tokens": {"prompt": 0, "completion": 0, "total": 0}, "usd": 0.0})
    assert tool["kind"] == "tool" and tool["tool"] == "get_financials" and tool["usd"] == "0.0"
    # modelo sin tarifa → usd None se RESPETA (no se inventa)
    nul = billing._ledger_row_from_event(
        {"type": "cost", "kind": "model", "model": "x", "tokens": {"total": 5}, "usd": None})
    assert nul["usd"] is None


def test_ledger_row_ignores_non_cost_events():
    assert billing._ledger_row_from_event({"type": "tool_call", "tool": "x"}) is None
    assert billing._ledger_row_from_event({"type": "cost", "kind": "weird"}) is None
    assert billing._ledger_row_from_event("not a dict") is None


def test_base_cap_for_tier():
    assert float(billing.base_cap_for_tier("free")) == 1.0
    assert float(billing.base_cap_for_tier("tecnico")) == 100.0
    assert float(billing.base_cap_for_tier("desconocido")) == billing.DEFAULT_CAP_USD


def test_stripe_not_configured_degrades_honest(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert stripe_billing.is_configured() is False
    res = stripe_billing.create_checkout_session(
        user_id="u", amount_usd=5.0, success_url="x", cancel_url="y")
    assert res["configured"] is False  # NO finge un checkout


def test_stripe_credit_from_event_maps_paid_checkout():
    event = {"id": "evt_1", "type": "checkout.session.completed",
             "data": {"object": {"payment_status": "paid", "amount_total": 500,
                                  "metadata": {"user_id": "u-9", "credit_usd": "5.00000000"}}}}
    credit = stripe_billing.credit_from_event(event)
    assert credit == {"event_id": "evt_1", "user_id": "u-9", "usd": 5.0}
    # un evento no-pago → None
    assert stripe_billing.credit_from_event(
        {"id": "evt_2", "type": "payment_intent.created", "data": {"object": {}}}) is None
    # falta user_id → None (no acreditamos a nadie)
    assert stripe_billing.credit_from_event(
        {"id": "e", "type": "checkout.session.completed",
         "data": {"object": {"payment_status": "paid", "amount_total": 100, "metadata": {}}}}) is None


# ════════════════════════ 2. DB (real) ════════════════════════

pytestmark_db = pytest.mark.skipif(not DB_AVAILABLE, reason="Postgres puppet_ai no disponible")


def _new_user(conn, tier="free"):
    email = f"t7-test-{uuid.uuid4().hex[:10]}@aleph.ai"
    from app.phase1 import repo
    u = repo.register_user(conn, email, "secret123", "T7 Test")
    if tier != "free":
        repo.set_tier(conn, u["id"], tier)
    return u["id"]


def _frozen_events(uid, run_id):
    """Cost-events en la FORMA CONGELADA §5 — exactamente lo que emite T5."""
    return [
        {"type": "cost", "kind": "model", "user_id": uid, "run_id": run_id,
         "model": "openai/gpt-oss-120b",
         "tokens": {"prompt": 562, "completion": 119, "total": 681},
         "tokens_measured": True, "usd": 0.0001557, "price_source": "groq.com/pricing"},
        {"type": "cost", "kind": "tool", "user_id": uid, "run_id": run_id,
         "tool": "get_financials", "server": "secedgar", "executed": True,
         "tokens": {"prompt": 0, "completion": 0, "total": 0}, "usd": 0.0},
    ]


@pytestmark_db
def test_metering_and_idempotency(db_conn):
    billing.apply_billing_schema(db_conn)
    uid = _new_user(db_conn)
    run_id = str(uuid.uuid4())
    r1 = billing.record_run_cost(db_conn, run_id=run_id, user_id=uid,
                                 cost_events=_frozen_events(uid, run_id))
    assert r1["ingested"] == 2 and r1["already"] is False
    m = billing.get_meter(db_conn, uid)
    assert m["spent_usd"] == 0.0001557 and m["events"] == 2 and m["total_tokens"] == 681
    # idempotente: re-ingestar el MISMO run no duplica el cobro
    r2 = billing.record_run_cost(db_conn, run_id=run_id, user_id=uid,
                                 cost_events=_frozen_events(uid, run_id))
    assert r2["already"] is True
    assert billing.get_meter(db_conn, uid)["spent_usd"] == 0.0001557


@pytestmark_db
def test_usd_null_not_summed(db_conn):
    billing.apply_billing_schema(db_conn)
    uid = _new_user(db_conn)
    run_id = str(uuid.uuid4())
    events = [{"type": "cost", "kind": "model", "user_id": uid, "run_id": run_id,
               "model": "sin/tarifa", "tokens": {"prompt": 10, "completion": 5, "total": 15},
               "tokens_measured": True, "usd": None}]
    billing.record_run_cost(db_conn, run_id=run_id, user_id=uid, cost_events=events)
    m = billing.get_meter(db_conn, uid)
    assert m["spent_usd"] == 0.0 and m["events"] == 1 and m["total_tokens"] == 15  # token sí, usd no


@pytestmark_db
def test_cap_cutoff_and_credit_topup(db_conn):
    billing.apply_billing_schema(db_conn)
    uid = _new_user(db_conn)
    run_id = str(uuid.uuid4())
    billing.record_run_cost(db_conn, run_id=run_id, user_id=uid,
                            cost_events=_frozen_events(uid, run_id))
    # bajo el cap free ($1) → permitido
    assert billing.preflight(db_conn, uid)["allowed"] is True
    # me pongo un self-limit al ras del gasto → CORTA
    billing.set_self_limit(db_conn, uid, 0.0001557)
    pf = billing.preflight(db_conn, uid)
    assert pf["allowed"] is False and pf["reason"] == "over_budget"
    # comprar crédito sube el techo, pero el self-limit sigue capando hasta que lo quito
    billing.add_credit(db_conn, uid, 5.0)
    assert billing.get_meter(db_conn, uid)["cap_usd"] == 0.0001557
    billing.set_self_limit(db_conn, uid, None)
    m = billing.get_meter(db_conn, uid)
    assert m["cap_usd"] == 6.0 and billing.preflight(db_conn, uid)["allowed"] is True


@pytestmark_db
def test_anonymous_never_billed(db_conn):
    billing.apply_billing_schema(db_conn)
    assert billing.preflight(db_conn, None)["allowed"] is True
    r = billing.record_run_cost(db_conn, run_id="anon-x", user_id=None,
                                cost_events=_frozen_events("u", "anon-x"))
    assert r["ingested"] == 0 and r["reason"] == "anonymous"


# ════════════════════════ 3. HTTP (TestClient sobre el router real) ════════════════════════

@pytest.fixture
def billing_app(tmp_path):
    """App real: router phase1 (run path) + router billing, ambos con get_conn REAL."""
    if not DB_AVAILABLE:
        pytest.skip("Postgres puppet_ai no disponible")
    from app.phase1 import repo
    events_root = tmp_path / "spaces"; events_root.mkdir()
    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=repo.get_conn, events_dir=lambda: events_root))
    app.include_router(build_billing_router(get_conn=repo.get_conn))
    # asegura el schema de billing aplicado
    conn = repo.get_conn(); billing.apply_billing_schema(conn); conn.close()
    return app


def _seed(repo, tier="free"):
    email = f"t7-http-{uuid.uuid4().hex[:10]}@aleph.ai"
    conn = repo.get_conn()
    try:
        u = repo.register_user(conn, email, "secret123", "T7 HTTP")
        if tier != "free":
            repo.set_tier(conn, u["id"], tier)
    finally:
        conn.close()
    return u["id"], repo.mint_session(u["id"])


def test_meter_authz_owner_gated(billing_app):
    from app.phase1 import repo
    client = TestClient(billing_app)
    a_id, a_tok = _seed(repo)
    _b_id, b_tok = _seed(repo)
    # sin sesión → 401
    assert client.get(f"/v1/billing/meter/{a_id}").status_code == 401
    # sesión de OTRO → 403
    assert client.get(f"/v1/billing/meter/{a_id}",
                      headers={"Authorization": f"Bearer {b_tok}"}).status_code == 403
    # dueño → 200 con su meter
    r = client.get(f"/v1/billing/meter/{a_id}", headers={"Authorization": f"Bearer {a_tok}"})
    assert r.status_code == 200 and r.json()["user_id"] == a_id and r.json()["cap_usd"] == 1.0


def test_preflight_402_when_over_budget(billing_app):
    from app.phase1 import repo
    client = TestClient(billing_app)
    a_id, a_tok = _seed(repo)
    h = {"Authorization": f"Bearer {a_tok}"}
    # me corto solito a 0 → preflight 402
    assert client.post(f"/v1/billing/limit/{a_id}", json={"self_limit_usd": 0.0}, headers=h).status_code == 200
    r = client.get(f"/v1/billing/preflight/{a_id}", headers=h)
    assert r.status_code == 402 and r.json()["detail"]["error"] == "over_budget"


def test_run_path_blocked_when_over_budget(billing_app, valid_recipe):
    """EL DONE-BAR sobre el endpoint REAL: pasar el cap FRENA el run (402) ANTES de
    gastar cognición. Cero llamada al modelo: el corte ocurre en el preflight del path."""
    from app.phase1 import repo
    client = TestClient(billing_app)
    a_id, a_tok = _seed(repo)
    h = {"Authorization": f"Bearer {a_tok}"}
    # cortar el presupuesto a 0
    client.post(f"/v1/billing/limit/{a_id}", json={"self_limit_usd": 0.0}, headers=h)
    r = client.post("/v1/puppets/run",
                    json={"recipe": valid_recipe, "user_id": a_id, "prompt": "hola"},
                    headers=h)
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["error"] == "over_budget"


def test_run_path_allows_under_budget_reaches_executor(billing_app, valid_recipe):
    """Bajo el cap, el path NO corta: pasa el preflight y entra al executor. No exigimos
    que el run COMPLETE (depende de gateway/modelo UP); exigimos que NO sea el 402 de billing
    — el corte de presupuesto no se dispara para un usuario con saldo."""
    from app.phase1 import repo
    client = TestClient(billing_app)
    a_id, a_tok = _seed(repo)
    h = {"Authorization": f"Bearer {a_tok}"}
    r = client.post("/v1/puppets/run",
                    json={"recipe": valid_recipe, "user_id": a_id, "prompt": "hola",
                          "deadline_s": 8},
                    headers=h)
    assert r.status_code != 402, r.text  # billing no lo cortó (tiene saldo free)


def test_webhook_rejects_without_signature(billing_app):
    """Sin firma verificable → NO se acredita nada. Con la lib/secret ausentes en este
    entorno, el webhook responde 503 stripe_not_configured (honesto), nunca un crédito."""
    client = TestClient(billing_app)
    r = client.post("/v1/billing/webhook/stripe", content=b"{}")
    assert r.status_code in (400, 503)  # 400 firma inválida (configurado) | 503 no configurado


def test_stripe_status_endpoint(billing_app):
    client = TestClient(billing_app)
    r = client.get("/v1/billing/stripe-status")
    assert r.status_code == 200 and "configured" in r.json()
