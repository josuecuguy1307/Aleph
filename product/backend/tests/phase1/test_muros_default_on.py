"""test_muros_default_on.py — EL DEFAULT ES EL SEGURO. Step 5 · Casa 1 · P7.

CONTRACT-PIN. Este archivo existe para que el flip de P7 no se revierta por accidente.

Cómo llegamos acá: los dos muros premium nacieron "staged" — el default en código era
APAGADO y sólo los prendía `start_caso3_stack.sh`. Funcionaba en el stack del examen y
por eso nadie lo notó, pero significaba que **un build público donde nadie exportara la
env corría SIN MURO**. El propio script lo documentaba como riesgo. Lo destapó el audit
§0 del Step 5.

Un default de seguridad que depende de que alguien se acuerde de una variable no es un
default de seguridad. Si mañana alguien "limpia" el `"1"` de `os.environ.get(..., "1")`
creyendo que es ruido, ESTOS tests se ponen rojos y le explican por qué está mal —
en vez de que el moat quede abierto en silencio hasta que alguien lo note.

`monkeypatch.delenv` simula el caso real: producción sin ninguna env configurada.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
for p in (REPO_ROOT / "platform", REPO_ROOT / "product" / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

ENV_CONSTRUCCION = "PUPPET_ENFORCE_MCP_CONSTRUCTION"
ENV_EXPORT = "PUPPET_ENFORCE_METHOD_EXPORT"


# ── EL MURO DE CONSTRUCCIÓN (el MOAT) ──────────────────────────────────────────
def test_sin_ninguna_env_el_muro_de_construccion_NIEGA(monkeypatch):
    """El caso de producción: nadie configuró nada. El muro tiene que estar puesto."""
    monkeypatch.delenv(ENV_CONSTRUCCION, raising=False)
    from app.phase1.forge_router import enforce_construction_premium

    rechazo = enforce_construction_premium(None)   # anónimo, sin sesión
    assert rechazo is not None, (
        "SIN la env, el muro de construcción dejó pasar a un anónimo. El default volvió "
        "a ser fail-OPEN: un build público sin configurar regala el MOAT.")
    assert rechazo.get("tier_gated") is True
    assert rechazo.get("min_tier") == "basico"


@pytest.mark.parametrize("valor", ["0", "false", "FALSE", "no", "off", "Off"])
def test_solo_un_apagado_EXPLICITO_lo_desactiva(monkeypatch, valor):
    """El opt-out de dev/CI existe y funciona — pero hay que pedirlo."""
    monkeypatch.setenv(ENV_CONSTRUCCION, valor)
    from app.phase1.forge_router import enforce_construction_premium
    assert enforce_construction_premium(None) is None, f"{valor!r} no apagó el muro"


@pytest.mark.parametrize("valor", ["", " ", "1", "true", "on", "yes", "sí", "quizás",
                                   "disabled", "OFF ", "cero", "null", "None"])
def test_ningun_otro_valor_lo_apaga(monkeypatch, valor):
    """Fail-closed ante ambigüedad, igual que el resto de la muralla: sólo el conjunto
    exacto de apagado desactiva. Un valor raro (typo, config mal escrita) deja el muro
    PUESTO — molesto, nunca abierto.

    Ojo `"OFF "` con espacio: el lector hace strip, así que SÍ apaga. Se documenta acá
    para que sea decisión y no accidente."""
    monkeypatch.setenv(ENV_CONSTRUCCION, valor)
    from app.phase1.forge_router import enforce_construction_premium
    esperado_apaga = valor.strip().lower() in ("0", "false", "no", "off")
    resultado = enforce_construction_premium(None)
    if esperado_apaga:
        assert resultado is None
    else:
        assert resultado is not None, (
            f"el valor {valor!r} apagó el muro sin ser un apagado explícito")


# ── EL MURO DE EXPORT TOTAL ────────────────────────────────────────────────────
def _cuenta_free():
    """Cuenta free REAL en Postgres + su sesión. El muro de export es owner-gated:
    sin sesión devuelve 401 ANTES de mirar el tier, así que para ver morder al muro
    hace falta una sesión legítima de alguien que no pagó."""
    import uuid
    from app.phase1 import repo
    conn = repo.get_conn()
    u = repo.get_or_create_user(conn, f"p7-{uuid.uuid4().hex[:8]}@probe.local", "Sonda P7")
    tok = repo.mint_session(u["id"])
    return conn, u["id"], tok


def _borrar(conn, uid):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s::uuid", (uid,))
    conn.commit()
    conn.close()


@pytest.mark.db
def test_sin_ninguna_env_el_muro_de_export_NIEGA(monkeypatch):
    """Una cuenta FREE con sesión válida pide un formato premium, sin ninguna env
    configurada: tiene que recibir 402."""
    monkeypatch.delenv(ENV_EXPORT, raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    try:
        conn, uid, tok = _cuenta_free()
    except Exception:
        pytest.skip("Postgres puppet_ai no disponible")
    try:
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/v1/methods/00000000-0000-0000-0000-000000000000/export?format=docx",
                  headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 402, (
            f"SIN la env, el export total no mordió (dio {r.status_code}): un build sin "
            "configurar exporta todo gratis")
    finally:
        _borrar(conn, uid)


@pytest.mark.db
def test_el_export_aleph_sigue_siendo_FREE_con_el_muro_puesto(monkeypatch):
    """El muro no puede tragarse lo que es gratis por diseño: el .aleph vivo y el PDF
    simple viajan SIEMPRE (§7). Si esto se rompe, le cortamos a free algo prometido —
    que es el otro modo de fallar, y también cuenta."""
    monkeypatch.delenv(ENV_EXPORT, raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    try:
        conn, uid, tok = _cuenta_free()
    except Exception:
        pytest.skip("Postgres puppet_ai no disponible")
    try:
        c = TestClient(app, raise_server_exceptions=False)
        for fmt in ("aleph", "pdf"):
            r = c.get(f"/v1/methods/00000000-0000-0000-0000-000000000000/export?format={fmt}",
                      headers={"Authorization": f"Bearer {tok}"})
            # 404 = el método no existe (esperado); lo que NO puede pasar es 402.
            assert r.status_code != 402, (
                f"el muro mordió el formato FREE {fmt!r}: free perdió algo que le prometimos")
    finally:
        _borrar(conn, uid)
