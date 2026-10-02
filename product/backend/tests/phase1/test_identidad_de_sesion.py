"""test_identidad_de_sesion.py — regresión de T-S5-01 y T-S5-03 · Step 5 · P8.

UNA SOLA CAUSA RAÍZ, tres endpoints: la identidad venía en la QUERY STRING.
Cualquiera podía pasar el `user_id` de otro y obtener su vista privada.

  · T-S5-01 (medium) — GET /catalog/{nicho}?user_id=<uuid-premium> devolvía el
    listado de templates premium a cualquiera. (Regresión en tests/test_catalog.py.)
  · T-S5-03 (medium) — GET /v1/atoms/catalog?user_id=<uuid-ajeno> y
    /v1/catalog/search?user_id=… revelaban QUÉ CONECTORES tiene conectados esa
    cuenta, SIN ninguna sesión. Verificado en vivo antes del fix: 'GitHub' aparecía
    como `connected`. No filtraba secretos (el contrato BYOK garantiza que list_keys
    sólo devuelve provider/last4) pero sí el inventario privado de integraciones.

El cierre es el mismo que exige la muralla: la identidad sale de la SESIÓN y el
parámetro deja de existir. Estos tests impiden que vuelva.
"""
from __future__ import annotations

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


@pytest.fixture()
def cliente():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def victima_con_conector():
    """Una cuenta con un conector conectado — el dato privado que no debe filtrarse."""
    from app.phase1 import repo
    conn = repo.get_conn()
    u = repo.get_or_create_user(conn, f"vict-{uuid.uuid4().hex[:8]}@probe.local", "Víctima")
    repo.upsert_key(conn, user_id=u["id"], provider="github", secret="ghp_secreto_de_la_victima")
    token = repo.mint_session(u["id"])
    yield conn, u["id"], token
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s::uuid", (u["id"],))
    conn.commit()
    conn.close()


def _conectados(resp) -> list:
    return [a["label"] for a in resp.json().get("atoms", []) if a.get("state") == "connected"]


# ── T-S5-03 · /v1/atoms/catalog ────────────────────────────────────────────────
def test_atoms_no_filtra_los_conectores_de_otra_cuenta(cliente, victima_con_conector):
    _conn, uid, _tok = victima_con_conector

    # el atacante conoce el uuid y NO tiene sesión
    r = cliente.get(f"/v1/atoms/catalog?user_id={uid}")
    assert r.status_code == 200
    assert _conectados(r) == [], (
        "el ?user_id= sigue revelando los conectores de otra cuenta (T-S5-03)")


def test_atoms_le_muestra_lo_suyo_al_DUEÑO(cliente, victima_con_conector):
    """Contraste: el fix no rompió la función — con la sesión propia sí se ve."""
    _conn, _uid, tok = victima_con_conector
    r = cliente.get("/v1/atoms/catalog", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert "GitHub" in _conectados(r), "el dueño dejó de ver sus propios conectores"


def test_atoms_con_token_de_OTRO_no_ve_lo_ajeno(cliente, victima_con_conector):
    """Una sesión válida pero de otra cuenta tampoco alcanza."""
    from app.phase1 import repo
    _conn, uid, _tok = victima_con_conector

    conn = repo.get_conn()
    otro = repo.get_or_create_user(conn, f"otro-{uuid.uuid4().hex[:8]}@probe.local", "Otro")
    tok_otro = repo.mint_session(otro["id"])
    try:
        r = cliente.get(f"/v1/atoms/catalog?user_id={uid}",
                        headers={"Authorization": f"Bearer {tok_otro}"})
        assert r.status_code == 200
        assert _conectados(r) == [], "una sesión ajena + ?user_id= vio lo de la víctima"
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s::uuid", (otro["id"],))
        conn.commit()
        conn.close()


def test_atoms_token_basura_no_ve_nada(cliente, victima_con_conector):
    _conn, uid, _tok = victima_con_conector
    r = cliente.get(f"/v1/atoms/catalog?user_id={uid}",
                    headers={"Authorization": "Bearer no-soy-una-sesion"})
    assert r.status_code == 200
    assert _conectados(r) == []


# ── T-S5-03 · /v1/catalog/search ───────────────────────────────────────────────
def test_search_no_filtra_estado_conectado_de_otra_cuenta(cliente, victima_con_conector):
    _conn, uid, tok = victima_con_conector

    ajeno = cliente.get(f"/v1/catalog/search?q=github&source=internal&user_id={uid}")
    assert ajeno.status_code == 200
    conectados_ajeno = [i for i in ajeno.json().get("items", [])
                        if i.get("state") == "connected"]
    assert conectados_ajeno == [], (
        "el search sigue revelando qué tiene conectado otra cuenta (T-S5-03)")

    # y con la sesión propia la función sigue viva
    propio = cliente.get("/v1/catalog/search?q=github&source=internal",
                         headers={"Authorization": f"Bearer {tok}"})
    assert propio.status_code == 200
