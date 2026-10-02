"""test_auth_password_cerrado.py — la superficie de registro, cerrada. CONTRACT-AUTH-v2.

EL HALLAZGO: `POST /v1/auth/register` respondía **201 en el servidor de producción**.
Cualquiera en internet podía crear una cuenta con un email que nadie verifica — que es
exactamente el vector de pre-hijacking (el atacante pre-registra la dirección de la
víctima; cuando ella entra por Google, su identidad se liga a esa cuenta).

Se había quitado el método de la pantalla de login. **Eso fue cosmético**: la API seguía
aceptando registros. Una superficie no se cierra en la UI, se cierra en el servidor.

Y `/auth/login` era peor: su modo legacy sin contraseña hace get-or-create por email, o
sea que TAMBIÉN crea cuentas — con sólo mandar una dirección.

EL CIERRE: ambos exigen `PUPPET_ALLOW_PASSWORD_AUTH=1`. Default cerrado, misma doctrina
que P7 — un default de seguridad que depende de que alguien recuerde una variable no es
un default de seguridad. Sigue vivo para dev/CI y el CLI local.

Devuelve **404, no 403**: para quien sondea desde afuera el endpoint no existe. No se le
confirma que hay una puerta cerrada.
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

ENV = "PUPPET_ALLOW_PASSWORD_AUTH"


@pytest.fixture()
def cliente():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _email():
    return f"cerrado-{uuid.uuid4().hex[:10]}@probe.local"


# ── EL DEFAULT: cerrado ────────────────────────────────────────────────────────
def test_sin_env_el_registro_NO_EXISTE(cliente, monkeypatch):
    """El caso de producción: nadie configuró nada."""
    monkeypatch.delenv(ENV, raising=False)
    r = cliente.post("/v1/auth/register",
                     json={"email": _email(), "password": "una-clave-larga-123"})
    assert r.status_code == 404, (
        f"SIN la env, el registro por contraseña sigue ABIERTO (dio {r.status_code}). "
        "Cualquiera en internet puede crear cuentas con emails que nadie verifica.")


def test_sin_env_el_login_tampoco(cliente, monkeypatch):
    """/auth/login también crea cuentas (get-or-create sin contraseña): misma puerta."""
    monkeypatch.delenv(ENV, raising=False)
    r = cliente.post("/v1/auth/login", json={"email": _email()})
    assert r.status_code == 404, f"dio {r.status_code}"


def test_responde_404_y_no_403(cliente, monkeypatch):
    """404 y no 403: a quien sondea no se le confirma que hay una puerta cerrada."""
    monkeypatch.delenv(ENV, raising=False)
    r = cliente.post("/v1/auth/register",
                     json={"email": _email(), "password": "una-clave-larga-123"})
    assert r.status_code == 404
    assert "403" not in r.text and "forbidden" not in r.text.lower()


@pytest.mark.parametrize("valor", ["", " ", "0", "false", "no", "off", "quizás",
                                   "sí", "enabled", "None", "2"])
def test_solo_un_encendido_EXPLICITO_lo_abre(cliente, monkeypatch, valor):
    """Fail-closed ante ambigüedad: sólo 1/true/yes/on abren. Un typo en la config
    deja el endpoint CERRADO — molesto en dev, nunca abierto en producción."""
    monkeypatch.setenv(ENV, valor)
    r = cliente.post("/v1/auth/register",
                     json={"email": _email(), "password": "una-clave-larga-123"})
    esperado_abre = valor.strip().lower() in ("1", "true", "yes", "on")
    if esperado_abre:
        assert r.status_code != 404
    else:
        assert r.status_code == 404, f"el valor {valor!r} abrió el endpoint"


# ── Y encendido, dev sigue funcionando ─────────────────────────────────────────
@pytest.mark.db
def test_con_la_env_dev_puede_registrar(cliente, monkeypatch):
    """El opt-out existe y funciona: los harnesses y el CLI local no se rompen."""
    monkeypatch.setenv(ENV, "1")
    email = _email()
    r = cliente.post("/v1/auth/register",
                     json={"email": email, "password": "una-clave-larga-123"})
    if r.status_code == 503:
        pytest.skip("Postgres no disponible")
    assert r.status_code == 201, f"dio {r.status_code}: {r.text[:200]}"

    from app.phase1 import repo
    conn = repo.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
    finally:
        conn.close()
