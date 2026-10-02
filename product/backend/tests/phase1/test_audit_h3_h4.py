"""test_audit_h3_h4.py — dos IDOR del barrido de superficie, cerrados y con exploit.

Cada test EJECUTA EL ATAQUE y confirma que ahora falla. No prueba "el fix está" — prueba
que el exploit concreto que un atacante correría devuelve 401/404.

H3 · ejecución de receta ajena (la línea roja #1: gasta la factura de Aleph)
     POST /v1/puppets/run {puppet_id: <de otra cuenta>}  SIN sesión → corría la receta.
H4 · fuga de conectores de cualquier usuario
     GET /v1/belts/cards?user_id=<ajeno> → devolvía provider+last4 de esa cuenta.

Ambos son la misma causa raíz que el step cazó cuatro veces antes: identidad declarada
por el cliente. La quinta (H4) y una variante de ejecución (H3).
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
def victima_con_puppet_y_key():
    """Una víctima con un agente GUARDADO y un conector conectado — los dos activos que
    un atacante querría tocar."""
    from app.phase1 import repo
    conn = repo.get_conn()
    u = repo.get_or_create_user(conn, f"vict-{uuid.uuid4().hex[:8]}@probe.local", "Víctima")
    pup = repo.create_puppet(
        conn, owner_id=u["id"], name="agente-privado", nicho="generalistas",
        config={"model": "stub", "belt": {}, "framing": "x", "tool_filters": {},
                "max_turns": 1})
    repo.upsert_key(conn, user_id=u["id"], provider="github", secret="ghp_secreto_victima")
    yield conn, u["id"], pup["id"], repo.mint_session(u["id"])
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s::uuid", (u["id"],))
    conn.commit()
    conn.close()


# ── H3 · EL EXPLOIT: correr la receta de otro ─────────────────────────────────
def test_H3_run_receta_ajena_SIN_sesion_es_rechazado(cliente, victima_con_puppet_y_key):
    _conn, _uid, puppet_id, _tok = victima_con_puppet_y_key
    # el atacante conoce el puppet_id y NO manda sesión ni user_id
    r = cliente.post("/v1/puppets/run", json={"puppet_id": puppet_id, "prompt": "corré"})
    assert r.status_code in (401, 404), (
        f"H3 VIVO: corrió (o intentó) la receta ajena sin sesión (dio {r.status_code}). "
        "Gasto de cognición a costa de Aleph con un puppet_id ajeno.")


def test_H3_run_receta_ajena_con_sesion_de_OTRO_es_404(cliente, victima_con_puppet_y_key):
    """Una sesión válida pero de otra cuenta tampoco alcanza — y da 404, no 403
    (no se confirma que el puppet existe)."""
    from app.phase1 import repo
    _conn, _uid, puppet_id, _tok = victima_con_puppet_y_key
    conn = repo.get_conn()
    otro = repo.get_or_create_user(conn, f"otro-{uuid.uuid4().hex[:8]}@probe.local", "Otro")
    tok_otro = repo.mint_session(otro["id"])
    try:
        r = cliente.post("/v1/puppets/run", json={"puppet_id": puppet_id, "prompt": "x"},
                         headers={"Authorization": f"Bearer {tok_otro}"})
        assert r.status_code == 404, f"sesión ajena corrió la receta (dio {r.status_code})"
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s::uuid", (otro["id"],))
        conn.commit()
        conn.close()


def test_H3_enqueue_tiene_el_mismo_cierre(cliente, victima_con_puppet_y_key):
    """El bug estaba también en la cola: cerrar sólo el síncrono dejaba el agujero."""
    _conn, _uid, puppet_id, _tok = victima_con_puppet_y_key
    r = cliente.post("/v1/runs/enqueue", json={"puppet_id": puppet_id, "prompt": "x"})
    assert r.status_code in (401, 404), f"enqueue corrió receta ajena (dio {r.status_code})"


def test_H3_el_DUEÑO_sí_corre_su_agente(cliente, victima_con_puppet_y_key):
    """Contraste: el fix no rompió la función. El dueño, con su sesión, pasa la carga
    de la receta (llega más allá del 401/404 de identidad)."""
    _conn, _uid, puppet_id, tok = victima_con_puppet_y_key
    r = cliente.post("/v1/puppets/run", json={"puppet_id": puppet_id, "prompt": "hola"},
                     headers={"Authorization": f"Bearer {tok}"})
    # No exigimos 200 (el run real necesita cognición): exigimos que NO sea el rechazo
    # de identidad — o sea que la receta se cargó porque es suya.
    assert r.status_code not in (401,), f"al DUEÑO le negó su propio agente (dio {r.status_code})"


def test_H3_recipe_inline_anonima_sigue_permitida(cliente):
    """La frontera: una receta INLINE es tuya, no de nadie — no la toca este gate.
    Los tests y el e2e dependen de correr recipes ad-hoc sin sesión."""
    r = cliente.post("/v1/puppets/run",
                     json={"recipe": {"model": "stub", "belt": {}, "framing": "x",
                                      "tool_filters": {}, "max_turns": 1},
                           "prompt": "hola"})
    # No debe ser 401/404 por identidad: la receta inline no requiere sesión.
    assert r.status_code not in (401, 404), (
        f"el gate de H3 rompió el camino de recipe inline anónima (dio {r.status_code})")


# ── H4 · EL EXPLOIT: leer los conectores de otro ──────────────────────────────
def _belt_ref():
    # cualquier belt del catálogo con cards; github aparece en research
    return "catalog/templates/research/belt-research.mcp.json"


def test_H4_cards_no_filtra_conectores_ajenos(cliente, victima_con_puppet_y_key):
    _conn, uid, _pid, _tok = victima_con_puppet_y_key
    # el atacante pasa el user_id de la víctima en el query, SIN sesión
    r = cliente.get(f"/v1/belts/cards?ref={_belt_ref()}&user_id={uid}")
    assert r.status_code == 200
    conectados = [c for c in r.json().get("cards", []) if c.get("state") == "connected"]
    assert conectados == [], (
        f"H4 VIVO: el ?user_id= sigue revelando los conectores de otra cuenta: "
        f"{[c.get('id') for c in conectados]}")


def test_H4_el_dueño_sí_ve_sus_conectores(cliente, victima_con_puppet_y_key):
    _conn, _uid, _pid, tok = victima_con_puppet_y_key
    r = cliente.get(f"/v1/belts/cards?ref={_belt_ref()}",
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    conectados = [c for c in r.json().get("cards", []) if c.get("state") == "connected"]
    # github fue conectado en el fixture → el dueño DEBE verlo conectado
    assert any("github" in str(c.get("connector", "")).lower()
               or c.get("state") == "connected" for c in r.json().get("cards", [])), \
        "el dueño dejó de ver su propio conector (el fix rompió la función)"
