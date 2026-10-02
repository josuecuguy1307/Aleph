"""test_payments_checkout.py — POST /v1/payments/checkout · Step 5 · Casa 1 · P4.

El foco NO es el camino feliz (que necesita red y se prueba en la llave viva). Es el
CANDADO: que la cuenta a la que se acredita el pago salga de la sesión y no haya forma
de que el cliente la elija. Si eso se rompe, todo el puente pago→tier no sirve: se paga
$15 y se asciende la cuenta que uno quiera.

El procesador se reemplaza por un doble que NO toca la red: acá se prueba el router,
no el SDK (el SDK ya está probado contra la API real en P0/P2/P3).
"""

from __future__ import annotations

# [Casa 2 · Fase 2 · 2.0] ESTE ARCHIVO PRUEBA EL PLANO DE CONTROL, y ahora lo declara.
# `platform/role.py` defaultea a `client` (fail-closed), y `main.py` monta los routers EN
# TIEMPO DE IMPORT — así que sin esto la app de test no tiene /v1/payments/checkout ni el
# webhook, y los 25 tests de pagos fallaban con 404. El rol se fija ANTES de que ninguna
# fixture importe app.main: después no sirve, el módulo ya quedó en sys.modules.
import os as _os
_os.environ.setdefault("ALEPH_ROLE", "control")


import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
for p in (REPO_ROOT / "platform", REPO_ROOT / "product" / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytestmark = pytest.mark.db


def _pg():
    try:
        from app.phase1 import repo
        c = repo.get_conn()
        c.close()
        return True
    except Exception:
        return False


if not _pg():
    pytest.skip("Postgres puppet_ai no disponible", allow_module_level=True)


class _ProcesadorDoble:
    """Doble del procesador: registra con qué lo llamaron, sin salir a la red."""

    nombre = "dodo"
    ultima_llamada: dict = {}

    def crear_checkout(self, *, plan, account_id, return_url):
        _ProcesadorDoble.ultima_llamada = {
            "plan": plan, "account_id": account_id, "return_url": return_url}
        return {"checkout_url": f"https://test.checkout.example/{plan}",
                "session_id": "cks_doble"}


@pytest.fixture()
def cliente(monkeypatch):
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", "noop")
    monkeypatch.setenv("DODO_PAYMENTS_WEBHOOK_KEY", "noop")
    monkeypatch.setenv("DODO_PAYMENTS_ENVIRONMENT", "test_mode")
    _ProcesadorDoble.ultima_llamada = {}

    import payments.base as base
    monkeypatch.setattr(base, "get_procesador", lambda *a, **k: _ProcesadorDoble())

    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def dos_cuentas():
    from app.phase1 import repo
    conn = repo.get_conn()
    a = repo.get_or_create_user(conn, f"p4a-{uuid.uuid4().hex[:8]}@probe.local", "A")
    b = repo.get_or_create_user(conn, f"p4b-{uuid.uuid4().hex[:8]}@probe.local", "B")
    yield conn, a["id"], b["id"]
    with conn.cursor() as cur:
        # cast explícito: los ids vienen como texto y la columna es UUID
        cur.execute("DELETE FROM users WHERE id = ANY(%s::uuid[])",
                    ([a["id"], b["id"]],))
    conn.commit()
    conn.close()


# ── EL CANDADO ──────────────────────────────────────────────────────────────────
def test_sin_sesion_no_hay_checkout(cliente):
    r = cliente.post("/v1/payments/checkout", json={"plan": "lifetime"})
    assert r.status_code == 401


def test_la_cuenta_sale_de_la_SESION(cliente, dos_cuentas):
    from app.phase1 import repo
    _, a, _b = dos_cuentas
    r = cliente.post("/v1/payments/checkout", json={"plan": "lifetime"},
                     headers={"Authorization": f"Bearer {repo.mint_session(a)}"})
    assert r.status_code == 200, r.text
    assert _ProcesadorDoble.ultima_llamada["account_id"] == a


def test_no_se_puede_acreditar_el_pago_a_OTRA_cuenta(cliente, dos_cuentas):
    """El ataque que este endpoint tiene que hacer imposible: A paga y acredita a B.

    Se prueban las variantes con las que alguien intentaría colarlo. Ninguna puede
    cambiar la cuenta: el modelo no tiene ese campo, así que pydantic los descarta y
    el router sólo mira la sesión.
    """
    from app.phase1 import repo
    _, a, b = dos_cuentas
    tok_a = repo.mint_session(a)

    for intento in ({"plan": "lifetime", "account_id": b},
                    {"plan": "lifetime", "user_id": b},
                    {"plan": "lifetime", "metadata": {"account_id": b}},
                    {"plan": "lifetime", "owner": b}):
        r = cliente.post("/v1/payments/checkout", json=intento,
                         headers={"Authorization": f"Bearer {tok_a}"})
        assert r.status_code == 200, r.text
        assert _ProcesadorDoble.ultima_llamada["account_id"] == a, (
            f"se acreditó a otra cuenta con {intento!r}")


def test_token_basura_no_pasa(cliente):
    r = cliente.post("/v1/payments/checkout", json={"plan": "lifetime"},
                     headers={"Authorization": "Bearer no-soy-una-sesion"})
    assert r.status_code == 401


# ── Validación de plan ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("plan", ["gratis", "", "PREMIUM", "basico", "free", "x"])
def test_plan_invalido_da_400(cliente, dos_cuentas, plan):
    from app.phase1 import repo
    _, a, _b = dos_cuentas
    r = cliente.post("/v1/payments/checkout", json={"plan": plan},
                     headers={"Authorization": f"Bearer {repo.mint_session(a)}"})
    assert r.status_code == 400


@pytest.mark.parametrize("plan", ["lifetime", "monthly", "LIFETIME", " lifetime "])
def test_planes_validos_pasan_normalizados(cliente, dos_cuentas, plan):
    from app.phase1 import repo
    _, a, _b = dos_cuentas
    r = cliente.post("/v1/payments/checkout", json={"plan": plan},
                     headers={"Authorization": f"Bearer {repo.mint_session(a)}"})
    assert r.status_code == 200, r.text
    assert _ProcesadorDoble.ultima_llamada["plan"] == plan.strip().lower()


def test_plan_sin_product_id_da_501_honesto(cliente, dos_cuentas, monkeypatch):
    """El anual todavía no existe en el dashboard. Debe decirlo, no dar un 500 mudo."""
    from app.phase1 import repo
    import payments.base as base

    class _SinAnual(_ProcesadorDoble):
        def crear_checkout(self, *, plan, account_id, return_url):
            raise ValueError("plan sin product_id configurado: 'annual'")

    monkeypatch.setattr(base, "get_procesador", lambda *a, **k: _SinAnual())
    _, a, _b = dos_cuentas
    r = cliente.post("/v1/payments/checkout", json={"plan": "annual"},
                     headers={"Authorization": f"Bearer {repo.mint_session(a)}"})
    assert r.status_code == 501
    assert r.json()["detail"]["error"] == "plan_no_disponible"


def test_procesador_caido_da_502_sin_filtrar_la_excepcion(cliente, dos_cuentas, monkeypatch):
    from app.phase1 import repo
    import payments.base as base

    class _Caido(_ProcesadorDoble):
        def crear_checkout(self, **kw):
            raise RuntimeError("connection refused a api.interna.secreta:5432")

    monkeypatch.setattr(base, "get_procesador", lambda *a, **k: _Caido())
    _, a, _b = dos_cuentas
    r = cliente.post("/v1/payments/checkout", json={"plan": "lifetime"},
                     headers={"Authorization": f"Bearer {repo.mint_session(a)}"})
    assert r.status_code == 502
    # el detalle interno no se filtra al cliente
    assert "secreta" not in r.text and "connection refused" not in r.text


# ── P5 · reconciliación de la propia cuenta ────────────────────────────────────
def test_reconcile_requiere_sesion(cliente):
    r = cliente.post("/v1/payments/reconcile")
    assert r.status_code == 401


def test_reconcile_no_filtra_ids_del_procesador(cliente, dos_cuentas, monkeypatch):
    """La respuesta le dice al usuario en qué quedó su tier, no la tripa del
    procesador (external_ids, estados internos)."""
    from app.phase1 import repo
    import payments.reconcile as rec

    _, a, _b = dos_cuentas
    monkeypatch.setattr(rec, "reconciliar", lambda *a_, **k: {
        "revisadas": 1, "corregidas": 1, "tiers_cambiados": 1, "errores": 0,
        "detalle": [{"external_id": "sub_SECRETO_del_procesador"}]})

    r = cliente.post("/v1/payments/reconcile",
                     headers={"Authorization": f"Bearer {repo.mint_session(a)}"})
    assert r.status_code == 200, r.text
    assert "sub_SECRETO_del_procesador" not in r.text
    assert set(r.json()) == {"revisadas", "corregidas", "tier"}
