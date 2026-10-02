"""test_cruces_rol.py — los 3 cruces cliente↔control, resueltos por d1. [Casa 2 · 2.2b, parte d]

El recon encontró que el corte del 2.0 (que sacó `billing_router` del cliente) dejó tres
lugares donde código de CLIENTE alcanza tablas de CONTROL:

  1. `router.py:1622,1664,1929` llaman `billing.preflight/record_run_cost` en el camino
     caliente de cada run, y `router.py` se monta SIEMPRE (main.py:508).
  2. `payments_router.py` `GET /me/tier` lee `subscriptions` y NO está bajo `solo_control`
     (correctamente: D1 dice que el cliente pregunta su plan sin llamar a casa).
  3. `repo.py` toca `subscriptions`/`payment_webhook_events`/`tier_audit` y lo importa todo.

Resueltos por **d1: gatear por rol**, que es aplicar D1 —el muro real es server-side— y no
por d2 (mover billing_*/subscriptions al cliente), que pondría la autoridad de plata en un
archivo que el usuario puede editar.

Verde = el cliente hace el trabajo SIN pedir tablas de control, y el control sigue midiendo
y cobrando igual que antes.

Correr:  pytest platform/db/test_cruces_rol.py -v
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys

import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_PLATFORM = os.path.dirname(_AQUI)
_REPO = os.path.dirname(_PLATFORM)
for _p in (_AQUI, _PLATFORM, os.path.join(_REPO, "product", "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _recargar(rol: str):
    os.environ["ALEPH_ROLE"] = rol
    import role
    importlib.reload(role)
    import db
    importlib.reload(db)
    from app.phase1 import billing, repo
    importlib.reload(repo)
    importlib.reload(billing)
    return billing, repo


@pytest.fixture(autouse=True)
def _limpiar():
    previo = os.environ.get("ALEPH_ROLE"), os.environ.get("PUPPET_SQLITE_PATH")
    yield
    for k, v in zip(("ALEPH_ROLE", "PUPPET_SQLITE_PATH"), previo):
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _hay_postgres() -> bool:
    try:
        return subprocess.run(["pg_isready", "-h", "127.0.0.1", "-p", "5432"],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def _espia(fabrica, registro: list):
    """Una fábrica de conexiones que anota cada SQL ejecutado.

    Envuelve con clases en vez de asignar atributos: `psycopg2.connection.cursor` es
    read-only, así que monkeypatchear la instancia no funciona en el camino de control.
    """
    class _Cur:
        def __init__(self, cur):
            self._c = cur

        def execute(self, sql, params=None):
            registro.append(sql)
            return self._c.execute(sql, params)

        def __enter__(self):
            self._c.__enter__() if hasattr(self._c, "__enter__") else None
            return self

        def __exit__(self, *e):
            return self._c.__exit__(*e) if hasattr(self._c, "__exit__") else False

        def __getattr__(self, n):
            return getattr(self._c, n)

    class _Conn:
        def __init__(self, conn):
            self._c = conn

        def cursor(self, *a, **kw):
            return _Cur(self._c.cursor(*a, **kw))

        def __getattr__(self, n):
            return getattr(self._c, n)

    return lambda: _Conn(fabrica())


def _cliente(tmp_path, nombre="cruces.db"):
    billing, repo = _recargar("client")
    os.environ["PUPPET_SQLITE_PATH"] = str(tmp_path / nombre)
    import sqlite_db
    conn = repo.get_conn()
    sqlite_db.crear_schema(conn)
    conn.commit()
    return billing, repo, conn


# ── CRUCE 1: billing en el camino caliente del cliente ───────────────────────────

def test_preflight_en_cliente_no_toca_tablas_de_control(tmp_path):
    """EL TEST QUE IMPORTA: sin la guarda, esto muere con "no such table: billing_quota"."""
    billing, repo, conn = _cliente(tmp_path)
    try:
        u = repo.get_or_create_user(conn, email="run@aleph.app")
        pf = billing.preflight(conn, u["id"])
        assert pf["allowed"] is True
        assert pf["reason"] == "client_local"
    finally:
        conn.close()


def test_record_run_cost_en_cliente_no_ingesta_ni_falla(tmp_path):
    billing, repo, conn = _cliente(tmp_path)
    try:
        u = repo.get_or_create_user(conn, email="costo@aleph.app")
        out = billing.record_run_cost(
            conn, run_id="11111111-1111-4111-8111-111111111111", user_id=u["id"],
            cost_events=[{"type": "cost", "kind": "model", "usd": 0.01,
                          "tokens": {"prompt": 10, "completion": 5, "total": 15}}])
        assert out["ingested"] == 0
        assert out["reason"] == "client_local"
    finally:
        conn.close()


def test_un_run_medido_no_se_cae_en_cliente(tmp_path):
    """La secuencia REAL de router.py:1622→1664 sobre un run: preflight, correr, cobrar."""
    billing, repo, conn = _cliente(tmp_path)
    try:
        u = repo.get_or_create_user(conn, email="e2e@aleph.app")
        assert billing.preflight(conn, u["id"])["allowed"]           # :1622
        p = repo.create_puppet(conn, owner_id=u["id"], name="p", nicho="quant", config={})
        r = repo.create_run(conn, puppet_id=p["id"], user_id=u["id"], intent="probar")
        out = billing.record_run_cost(conn, run_id=r["id"], user_id=u["id"],
                                      cost_events=[])                # :1664
        assert out["ingested"] == 0
        assert repo.get_run(conn, r["id"])["id"] == r["id"], "el run no se persistió"
    finally:
        conn.close()


def test_lo_que_no_tiene_equivalente_local_se_dice(tmp_path):
    """`set_self_limit`/`add_credit` no tienen sentido local: avisan en vez de escribir
    en una tabla que no existe (o peor, devolver un número inventado)."""
    billing, repo, conn = _cliente(tmp_path)
    try:
        u = repo.get_or_create_user(conn, email="lim@aleph.app")
        for fn, args in ((billing.set_self_limit, (conn, u["id"], 5.0)),
                         (billing.add_credit, (conn, u["id"], 10.0))):
            with pytest.raises(RuntimeError) as e:
                fn(*args)
            assert "plano de control" in str(e.value)
    finally:
        conn.close()


# ── CRUCE 2: /me/tier ────────────────────────────────────────────────────────────

def test_me_tier_en_cliente_responde_desde_users_tier(tmp_path):
    """Sin el corte, `repo.list_subscriptions` mata el endpoint con "no such table"."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    billing, repo, conn = _cliente(tmp_path, "tier.db")
    try:
        u = repo.get_or_create_user(conn, email="tier@aleph.app")
        # El tier se escribe con un UPDATE plano, NO con `repo.set_tier()`: esa función
        # audita en `tier_audit`, que es tabla de control. Y no es un cruce — `set_tier`
        # sólo se alcanza vía `resync_account_tier`, y sus dos llamadores (el webhook por
        # `_aplicar` en :211, y `/reconcile`) están los dos bajo `solo_control`. Ver
        # `test_set_tier_es_control_only`.
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET tier = %s WHERE id = %s", ("tecnico", u["id"]))
        conn.commit()
        token = repo.mint_session(u["id"])
    finally:
        conn.close()

    from app.phase1.payments_router import build_payments_router
    app = FastAPI()
    app.include_router(build_payments_router(get_conn=repo.get_conn, rol="client"))
    r = TestClient(app).get("/v1/payments/me/tier",
                            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["tier"] == "tecnico"
    assert cuerpo["es_premium"] is True
    assert cuerpo["plan"] is None, "el cliente no tiene detalle de plan (no lee subscriptions)"


def test_me_tier_en_cliente_no_consulta_subscriptions(tmp_path):
    """Prueba directa de que la tabla de control NO se toca: si se tocara, el espía la ve."""
    billing, repo, conn = _cliente(tmp_path, "espia.db")
    try:
        u = repo.get_or_create_user(conn, email="espia@aleph.app")
        token = repo.mint_session(u["id"])
    finally:
        conn.close()

    vistos: list[str] = []
    espiado = _espia(repo.get_conn, vistos)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.phase1.payments_router import build_payments_router
    app = FastAPI()
    app.include_router(build_payments_router(get_conn=espiado, rol="client"))
    r = TestClient(app).get("/v1/payments/me/tier",
                            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    import role
    for sql in vistos:
        for t in role.TABLAS_CONTROL:
            assert t not in sql.lower(), f"tocó la tabla de control {t}: {sql[:80]}"


# ── el camino CONTROL no cambia ──────────────────────────────────────────────────

@pytest.mark.skipif(not _hay_postgres(), reason="sin Postgres local")
def test_en_control_billing_sigue_midiendo_de_verdad():
    """LO QUE NO PUEDE CAER. En control, preflight consulta el ledger real y devuelve el
    metering, exactamente como antes de 2.2b."""
    billing, repo = _recargar("control")
    conn = repo.get_conn()
    try:
        email = "control-billing-2.2b@aleph.test"
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        u = repo.get_or_create_user(conn, email=email)
        pf = billing.preflight(conn, u["id"])
        assert pf["reason"] != "client_local", "en control NO debe cortocircuitar"
        assert pf["allowed"] is True                       # free con cap > 0
        for clave in ("tier", "spent_usd", "cap_usd", "remaining_usd"):
            assert clave in pf, f"falta {clave}: el contrato de control cambió"
        assert pf["cap_usd"] > 0
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.skipif(not _hay_postgres(), reason="sin Postgres local")
def test_en_control_me_tier_sigue_leyendo_subscriptions():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    billing, repo = _recargar("control")
    conn = repo.get_conn()
    try:
        email = "control-tier-2.2b@aleph.test"
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        u = repo.get_or_create_user(conn, email=email)
        token = repo.mint_session(u["id"])
    finally:
        conn.close()

    vistos: list[str] = []
    espiado = _espia(repo.get_conn, vistos)

    from app.phase1.payments_router import build_payments_router
    app = FastAPI()
    app.include_router(build_payments_router(get_conn=espiado, rol="control"))
    r = TestClient(app).get("/v1/payments/me/tier",
                            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert any("subscriptions" in s.lower() for s in vistos), (
        "en control SÍ debe leer subscriptions — si no, se rompió el detalle del plan")

    conn = repo.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = %s", ("control-tier-2.2b@aleph.test",))
        conn.commit()
    finally:
        conn.close()


# ── EN ROJO ──────────────────────────────────────────────────────────────────────

def test_rojo_sin_la_guarda_el_cliente_muere_con_no_such_table(tmp_path):
    """El daño exacto que d1 evita: la consulta que `preflight` haría sin la guarda."""
    billing, repo, conn = _cliente(tmp_path, "rojo.db")
    try:
        u = repo.get_or_create_user(conn, email="rojo@aleph.app")
        with pytest.raises(Exception) as e:
            billing.get_meter(conn, u["id"])        # lo que preflight llamaría sin guarda
        assert "no such table" in str(e.value).lower(), (
            f"debería fallar por la tabla ausente; falló con: {e.value}")
    finally:
        conn.close()


def test_set_tier_es_control_only_por_construccion():
    """UN CUARTO CRUCE QUE NO LO ERA — y por qué. `repo.set_tier()` escribe `tier_audit`
    (tabla de control) en la misma transacción que `users.tier`. Parecía un cruce, pero
    sólo se alcanza vía `resync_account_tier`, y sus dos llamadores están los dos bajo
    `solo_control`: el webhook (por `_aplicar`, agendado en payments_router:211, dentro
    del endpoint decorado en :167) y `/reconcile` (:312). En el cliente no corre ninguno.

    Este test lo FIJA: si alguien cablea `set_tier`/`resync_account_tier` a un camino
    compartido, deja de ser cierto y hay que volver a decidir (probablemente separando la
    escritura del tier de su auditoría).
    """
    import re
    fuente = open(os.path.join(_REPO, "product", "backend", "app", "phase1",
                               "payments_router.py"), encoding="utf-8").read()
    # el decorador que gobierna cada llamada a resync_account_tier
    for m in re.finditer(r"resync_account_tier", fuente):
        antes = fuente[:m.start()]
        deco = None
        for d in re.finditer(r"@(solo_control\(router\.\w+|router\.\w+)", antes):
            deco = d.group(1)
        assert deco is None or deco.startswith("solo_control"), (
            f"resync_account_tier quedó bajo un endpoint sin solo_control: {deco}")

    otros = subprocess.run(
        ["grep", "-rn", "set_tier(\\|resync_account_tier(", "--include=*.py",
         os.path.join(_REPO, "product", "backend", "app"),
         os.path.join(_REPO, "platform")],
        capture_output=True, text=True).stdout.splitlines()
    vivos = [l for l in otros
             if "test_" not in l and "/.venv/" not in l and "def set_tier" not in l
             and "def resync_account_tier" not in l]
    permitidos = ("payments_router.py", "payments/reconcile.py", "phase1/repo.py")
    for l in vivos:
        assert any(p in l for p in permitidos), f"llamador nuevo de set_tier: {l}"


def test_rojo_ninguna_tabla_de_control_existe_en_el_cliente(tmp_path):
    """La frontera de 2.0, observable en la base del cliente después de todo el cableado."""
    import role
    billing, repo, conn = _cliente(tmp_path, "frontera.db")
    try:
        presentes = {r[0] for r in conn.raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert not (presentes & set(role.TABLAS_CONTROL))
        assert presentes >= {"users", "puppets", "runs"}, "faltan tablas de cliente"
    finally:
        conn.close()
