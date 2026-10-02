"""test_payments_webhook.py — las 4 reglas del §2 juntas en el endpoint.

Firma REAL (mismo algoritmo que verifica el SDK), DB real, TestClient real. Lo único
simulado es el pago; el resto del camino es el de producción.

Marcado `db`: toca el Postgres real (se salta si no está).
"""

from __future__ import annotations

# [Casa 2 · Fase 2 · 2.0] ESTE ARCHIVO PRUEBA EL PLANO DE CONTROL, y ahora lo declara.
# `platform/role.py` defaultea a `client` (fail-closed), y `main.py` monta los routers EN
# TIEMPO DE IMPORT — así que sin esto la app de test no tiene /v1/payments/checkout ni el
# webhook, y los 25 tests de pagos fallaban con 404. El rol se fija ANTES de que ninguna
# fixture importe app.main: después no sirve, el módulo ya quedó en sys.modules.
import os as _os
_os.environ.setdefault("ALEPH_ROLE", "control")


import base64
import datetime as _dt
import json
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
for p in (REPO_ROOT / "platform", REPO_ROOT / "product" / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SECRETO = base64.b64encode(b"step5-p3-webhook-secreto-de-prueba!!").decode()

pytestmark = pytest.mark.db


def _pg_disponible():
    try:
        from app.phase1 import repo
        c = repo.get_conn()
        c.close()
        return True
    except Exception:
        return False


if not _pg_disponible():
    pytest.skip("Postgres puppet_ai no disponible", allow_module_level=True)


@pytest.fixture()
def cliente(monkeypatch):
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", "noop-para-tests")
    monkeypatch.setenv("DODO_PAYMENTS_WEBHOOK_KEY", SECRETO)
    monkeypatch.setenv("DODO_PAYMENTS_ENVIRONMENT", "test_mode")
    from fastapi.testclient import TestClient
    from app.main import app
    # raise_server_exceptions=False: queremos ver el status real, no que el test
    # explote con la excepción del server.
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def cuenta():
    from app.phase1 import repo
    conn = repo.get_conn()
    u = repo.get_or_create_user(conn, f"p3-{uuid.uuid4().hex[:10]}@probe.local", "Sonda P3")
    yield conn, u["id"]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (u["id"],))
    conn.commit()
    conn.close()


def _firmar(cuerpo: bytes, wid: str, ts=None):
    from standardwebhooks.webhooks import Webhook
    ts = ts or int(time.time())
    firma = Webhook(SECRETO).sign(
        wid, _dt.datetime.fromtimestamp(ts, _dt.timezone.utc), cuerpo.decode())
    return {"webhook-id": wid, "webhook-timestamp": str(ts), "webhook-signature": firma}


def _cuerpo_alta(account_id, sub_id="sub_p3", fin="2099-01-01T00:00:00Z", tipo="subscription.active"):
    return json.dumps({
        "type": tipo,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": {
            "subscription_id": sub_id,
            "metadata": {"account_id": str(account_id)},
            "payment_frequency_interval": "Month",
            "next_billing_date": fin,
        },
    }).encode()


# ── Regla 1 · FIRMA PRIMERO ─────────────────────────────────────────────────────
def test_firma_invalida_da_401_y_no_persiste_nada(cliente, cuenta):
    conn, uid = cuenta
    cuerpo = _cuerpo_alta(uid)
    wid = f"msg_{uuid.uuid4().hex[:12]}"
    headers = _firmar(cuerpo, wid)
    headers["webhook-signature"] = "v1,firmafalsa="

    r = cliente.post("/v1/payments/webhook/dodo", content=cuerpo, headers=headers)
    assert r.status_code == 401, r.text

    # ni el evento se sembró, ni el tier se movió
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM payment_webhook_events WHERE webhook_id = %s", (wid,))
        assert cur.fetchone() is None, "una firma inválida sembró una fila de evento"
    from app.phase1 import repo
    assert repo.get_user(conn, uid)["tier"] == "free"


def test_sin_headers_de_firma_da_401(cliente, cuenta):
    _, uid = cuenta
    r = cliente.post("/v1/payments/webhook/dodo", content=_cuerpo_alta(uid))
    assert r.status_code == 401


def test_procesador_desconocido_da_404(cliente, cuenta):
    _, uid = cuenta
    cuerpo = _cuerpo_alta(uid)
    r = cliente.post("/v1/payments/webhook/paddle", content=cuerpo,
                     headers=_firmar(cuerpo, f"msg_{uuid.uuid4().hex[:8]}"))
    assert r.status_code == 404


# ── Regla 2+4 · ACK RÁPIDO y el efecto aplicado ────────────────────────────────
def test_webhook_valido_ackea_y_asciende_el_tier(cliente, cuenta):
    conn, uid = cuenta
    from app.phase1 import repo
    assert repo.get_user(conn, uid)["tier"] == "free"

    cuerpo = _cuerpo_alta(uid)
    wid = f"msg_{uuid.uuid4().hex[:12]}"

    t0 = time.monotonic()
    r = cliente.post("/v1/payments/webhook/dodo", content=cuerpo, headers=_firmar(cuerpo, wid))
    elapsed = time.monotonic() - t0

    assert r.status_code == 200, r.text
    assert r.json().get("received") is True
    # Dodo corta a los 15 s. Con margen amplio: si esto se acerca, el trabajo pesado
    # se filtró al handler.
    assert elapsed < 5, f"el ACK tardó {elapsed:.2f}s — algo pesado quedó en el handler"

    # TestClient corre los BackgroundTasks al cerrar la respuesta.
    assert repo.get_user(conn, uid)["tier"] == "basico"

    with conn.cursor() as cur:
        cur.execute("SELECT outcome, processed_at FROM payment_webhook_events "
                    "WHERE webhook_id = %s", (wid,))
        outcome, processed_at = cur.fetchone()
    assert outcome == "applied"
    assert processed_at is not None


# ── Regla 3 · IDEMPOTENCIA ──────────────────────────────────────────────────────
def test_mismo_webhook_id_dos_veces_procesa_una(cliente, cuenta):
    conn, uid = cuenta
    cuerpo = _cuerpo_alta(uid)
    wid = f"msg_{uuid.uuid4().hex[:12]}"
    headers = _firmar(cuerpo, wid)

    r1 = cliente.post("/v1/payments/webhook/dodo", content=cuerpo, headers=headers)
    r2 = cliente.post("/v1/payments/webhook/dodo", content=cuerpo, headers=headers)

    assert r1.status_code == 200 and r1.json().get("queued") is True
    # El duplicado se ACKea igual: sin 2xx, el procesador reintenta 8 veces más.
    assert r2.status_code == 200, "un duplicado sin 2xx dispara 8 reintentos"
    assert r2.json().get("duplicate") is True

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM payment_webhook_events WHERE webhook_id = %s", (wid,))
        assert cur.fetchone()[0] == 1

    # y una sola fila de auditoría: no se ascendió dos veces
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM tier_audit WHERE account_id = %s", (uid,))
        assert cur.fetchone()[0] == 1


# ── Regla 4 · SIN ORDEN GARANTIZADO ────────────────────────────────────────────
def test_evento_viejo_no_degrada_a_quien_acaba_de_renovar(cliente, cuenta):
    """El caso que rompe un diseño ingenuo: un `cancelled` demorado que llega DESPUÉS
    de un `renewed`. Sin defensa, le corta el servicio a un cliente que pagó."""
    conn, uid = cuenta
    from app.phase1 import repo

    ahora = _dt.datetime.now(_dt.timezone.utc)

    def cuerpo_con(tipo, ts, fin="2099-01-01T00:00:00Z"):
        return json.dumps({
            "type": tipo,
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "data": {"subscription_id": "sub_orden",
                     "metadata": {"account_id": str(uid)},
                     "payment_frequency_interval": "Month",
                     "next_billing_date": fin},
        }).encode()

    # 1) renovación de AHORA
    c1 = cuerpo_con("subscription.renewed", ahora)
    cliente.post("/v1/payments/webhook/dodo", content=c1,
                 headers=_firmar(c1, f"msg_{uuid.uuid4().hex[:12]}"))
    assert repo.get_user(conn, uid)["tier"] == "basico"

    # 2) cancelación VIEJA (de hace una hora) que llega tarde, con período ya vencido
    c2 = cuerpo_con("subscription.cancelled", ahora - _dt.timedelta(hours=1),
                    fin="2000-01-01T00:00:00Z")
    r = cliente.post("/v1/payments/webhook/dodo", content=c2,
                     headers=_firmar(c2, f"msg_{uuid.uuid4().hex[:12]}"))
    assert r.status_code == 200

    assert repo.get_user(conn, uid)["tier"] == "basico", \
        "un evento VIEJO degradó a un cliente que acababa de renovar"


# ── FAIL-CLOSED · lo que no se puede atribuir no toca ningún tier ──────────────
def test_sin_account_id_no_toca_ningun_tier(cliente, cuenta):
    conn, uid = cuenta
    from app.phase1 import repo

    cuerpo = json.dumps({
        "type": "subscription.active",
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": {"subscription_id": "sub_huerfano", "metadata": {},
                 "payment_frequency_interval": "Month",
                 "next_billing_date": "2099-01-01T00:00:00Z"},
    }).encode()
    wid = f"msg_{uuid.uuid4().hex[:12]}"
    r = cliente.post("/v1/payments/webhook/dodo", content=cuerpo, headers=_firmar(cuerpo, wid))

    assert r.status_code == 200      # se ACKea (no queremos 8 reintentos de algo irreparable)
    assert repo.get_user(conn, uid)["tier"] == "free"
    with conn.cursor() as cur:
        cur.execute("SELECT outcome FROM payment_webhook_events WHERE webhook_id = %s", (wid,))
        assert cur.fetchone()[0] == "error:sin_account_id"


def test_evento_irrelevante_se_ackea_sin_ascender(cliente, cuenta):
    conn, uid = cuenta
    from app.phase1 import repo

    cuerpo = json.dumps({
        "type": "invoice.created",
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": {"metadata": {"account_id": str(uid)}},
    }).encode()
    wid = f"msg_{uuid.uuid4().hex[:12]}"
    r = cliente.post("/v1/payments/webhook/dodo", content=cuerpo, headers=_firmar(cuerpo, wid))

    assert r.status_code == 200
    assert repo.get_user(conn, uid)["tier"] == "free"
    with conn.cursor() as cur:
        cur.execute("SELECT outcome FROM payment_webhook_events WHERE webhook_id = %s", (wid,))
        assert cur.fetchone()[0] == "ignored_unknown"


# ── Diagnóstico sin secretos ───────────────────────────────────────────────────
def test_status_no_filtra_secretos(cliente, monkeypatch):
    # [audit superficie · H7] Sin PUPPET_DIAG (el caso de producción), /status ya no
    # regala procesador/modo/config: sólo confirma vivo. Con el flag, el detalle —
    # pero nunca los secretos.
    monkeypatch.delenv("PUPPET_DIAG", raising=False)
    r = cliente.get("/v1/payments/status")
    assert r.status_code == 200
    assert r.json() == {"ok": True}, "en prod /status no debe exponer config"

    monkeypatch.setenv("PUPPET_DIAG", "1")
    r = cliente.get("/v1/payments/status")
    assert r.status_code == 200
    cuerpo = r.text
    assert SECRETO not in cuerpo and "noop-para-tests" not in cuerpo, \
        "ni con el flag de diagnóstico se filtran las claves"
    assert r.json()["webhook_key_configurada"] is True
