"""test_presupuesto_por_sesion.py — T-S5-02 · Step 5 · Casa 1 · P12.

EL BYPASS: el corte por presupuesto se decidía con `if body.user_id:` — un campo que
manda el CLIENTE. Un usuario logueado y por encima de su cap sólo tenía que OMITIR su
propio `user_id`: la sesión seguía siendo válida, el run arrancaba igual, y no había a
quién medir. Gasto de cognición sin techo, que es la línea roja #1 del negocio
(`aleph-estrategia-defensa.md` §8.4).

Es el mismo patrón que T-S5-01 y T-S5-03 — identidad declarada por el cliente — pero
al revés: allá el cliente ponía un id AJENO para ver de más; acá NO pone NINGUNO para
que no lo midan.

El cierre: a quién se mide sale de la sesión. Omitir el campo ya no cambia nada.

Marcado `db`: necesita cuenta y cap reales.
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
def cliente(tmp_path):
    """App armada como en test_billing.py: router phase1 (el run path) + billing, con
    get_conn REAL y un events_dir temporal. Usar `app.main:app` entero da 500 porque
    ese path espera más infra montada."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1 import billing, repo
    from app.phase1.router import build_phase1_router
    from app.phase1.billing_router import build_billing_router

    events_root = tmp_path / "spaces"
    events_root.mkdir()
    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=repo.get_conn,
                                           events_dir=lambda: events_root))
    app.include_router(build_billing_router(get_conn=repo.get_conn))
    conn = repo.get_conn()
    billing.apply_billing_schema(conn)
    conn.close()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def cuenta_sin_presupuesto():
    """Cuenta REAL cuyo tope autoimpuesto es 0 → está por encima del cap."""
    from app.phase1 import billing, repo
    conn = repo.get_conn()
    u = repo.get_or_create_user(conn, f"p12-{uuid.uuid4().hex[:8]}@probe.local", "Sonda P12")
    billing.set_self_limit(conn, u["id"], 0)      # se pone tope 0: no puede gastar nada
    tok = repo.mint_session(u["id"])
    yield conn, u["id"], tok
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s::uuid", (u["id"],))
    conn.commit()
    conn.close()


def _correr(cliente, tok, cuerpo):
    return cliente.post("/v1/puppets/run", json=cuerpo,
                        headers={"Authorization": f"Bearer {tok}"})


def test_declarando_el_user_id_lo_corta(cliente, cuenta_sin_presupuesto, valid_recipe):
    """Línea base: el corte funciona cuando el cliente declara quién es."""
    _conn, uid, tok = cuenta_sin_presupuesto
    r = _correr(cliente, tok, {"recipe": valid_recipe, "user_id": uid, "prompt": "hola"})
    assert r.status_code == 402, f"el cap no cortó (dio {r.status_code})"
    assert r.json()["detail"]["error"] == "over_budget"


def test_OMITIR_el_user_id_YA_NO_esquiva_el_cap(cliente, cuenta_sin_presupuesto, valid_recipe):
    """EL BYPASS. Misma sesión, mismo usuario sin presupuesto — pero sin declarar id.

    Antes del fix esto pasaba el preflight y arrancaba el run. Ahora la sesión decide.
    """
    _conn, _uid, tok = cuenta_sin_presupuesto
    r = _correr(cliente, tok, {"recipe": valid_recipe, "prompt": "hola"})
    assert r.status_code == 402, (
        f"BYPASS VIVO: omitiendo user_id el run esquivó el cap (dio {r.status_code}). "
        "Gasto de cognición sin techo.")
    assert r.json()["detail"]["error"] == "over_budget"


def test_el_bypass_tampoco_funciona_por_el_stream(cliente, cuenta_sin_presupuesto, valid_recipe):
    """/puppets/run/stream tenía SU PROPIO preflight con el mismo defecto. Arreglar
    sólo uno de los dos habría dejado el agujero abierto por el otro camino."""
    _conn, _uid, tok = cuenta_sin_presupuesto
    r = cliente.post("/v1/puppets/run/stream",
                     json={"recipe": valid_recipe, "prompt": "hola"},
                     headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 402, (
        f"BYPASS VIVO por el stream (dio {r.status_code})")


def test_el_run_ANONIMO_de_verdad_sigue_pasando(cliente, valid_recipe):
    """Sin sesión no hay cuenta que medir ni cap que aplicar. Ese camino lo usan los
    tests y el e2e; su techo es el rate-limit del borde, no esta capa. Lo que NO puede
    pasar es que devuelva 402 (sería cortar por un presupuesto que no existe)."""
    r = cliente.post("/v1/puppets/run",
                     json={"recipe": valid_recipe, "prompt": "hola"})
    assert r.status_code != 402, "cortó por presupuesto a un anónimo, que no tiene cap"
