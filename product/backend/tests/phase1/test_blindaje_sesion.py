"""test_blindaje_sesion.py — el middleware que MATA LA CLASE. Hallazgo #1.

El patrón "identidad del cliente" apareció 13+ veces porque el sistema nació
mono-usuario: endpoints que confiaban en `body.user_id` de forma condicional, de modo
que OMITIR el campo salteaba el control.

El fondo: un middleware que exige SESIÓN para toda mutación /v1 por DEFAULT, salvo una
allowlist pública explícita. Este test corre con el opt-out APAGADO (= comportamiento de
producción) y confirma que CADA endpoint sensible rechaza el ataque anónimo — y que un
endpoint HIPOTÉTICO nuevo también quedaría cerrado sin hacer nada.

`monkeypatch.delenv(PUPPET_ALLOW_ANON_V1)` = simula producción (la suite normalmente lo
tiene en 1 para que los harnesses corran; acá lo apagamos a propósito).
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


@pytest.fixture()
def prod(monkeypatch):
    """El cliente TAL CUAL corre en producción: sin el opt-out de anon."""
    monkeypatch.delenv("PUPPET_ALLOW_ANON_V1", raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


# ── EL BLINDAJE · toda mutación /v1 sensible rechaza al anónimo ────────────────
# Cada tupla es un exploit real: método, path, body. Sin sesión, todos → 401.
_MUTACIONES_SENSIBLES = [
    ("POST", "/v1/cuarto/guide", {"messages": [{"role": "user", "content": "x"}]}),
    ("POST", "/v1/forge", {"intent": "algo"}),
    ("POST", "/v1/transcribe", {"audio_b64": "x"}),
    ("POST", "/v1/classify-turn", {"prompt": "x"}),
    ("POST", "/v1/obra-caption", {"prompt": "x"}),
    ("POST", "/v1/artifacts/classify-action", {"action": "x"}),
    ("POST", "/v1/puppets/run", {"recipe": {"model": "x"}, "prompt": "x"}),
    ("POST", "/v1/puppets/run/stream", {"recipe": {"model": "x"}, "prompt": "x"}),
    ("POST", "/v1/runs/enqueue", {"recipe": {"model": "x"}, "prompt": "x"}),
    ("POST", "/v1/runs", {}),
    ("POST", "/v1/inspect", {"url": "https://example.com"}),
    ("POST", "/v1/inspect/dispatch", {"service": "x", "url": "https://example.com"}),
    ("POST", "/v1/inspect/session/browser", {"url": "https://example.com"}),
    ("POST", "/v1/construcciones", {"intent": "x"}),
    ("POST", "/v1/keys", {"provider": "x", "secret": "y"}),
    ("POST", "/v1/puppets", {"name": "x", "nicho": "y", "config": {}}),
]


@pytest.mark.parametrize("method,path,body", _MUTACIONES_SENSIBLES,
                         ids=[f"{m}:{p}" for m, p, _ in _MUTACIONES_SENSIBLES])
def test_mutacion_sin_sesion_es_401(prod, method, path, body):
    """EL EXPLOIT: la mutación anónima que gastaba recursos / creaba filas. → 401."""
    r = prod.request(method, path, json=body)
    assert r.status_code == 401, (
        f"BLINDAJE ROTO: {method} {path} corrió (o validó) SIN sesión (dio {r.status_code}). "
        "Un anónimo puede gastar cognición / crear datos.")
    assert r.json().get("detail", {}).get("error") == "no_session"


def test_un_endpoint_HIPOTETICO_nuevo_tambien_queda_cerrado(prod):
    """La prueba de que el blindaje es POR DEFAULT: una ruta /v1 que no existe (y que
    tampoco está en la allowlist) recibe el 401 del middleware ANTES del 404 del router —
    o sea que un endpoint nuevo que alguien agregue queda cerrado sin hacer nada."""
    r = prod.request("POST", "/v1/endpoint-que-nadie-escribio-todavia", json={})
    # el middleware corta con 401 antes de que el router resuelva la ruta
    assert r.status_code == 401, (
        f"un POST /v1 nuevo NO quedó cerrado por default (dio {r.status_code}) — el "
        "blindaje no es por-default y la clase puede volver")


# ── Lo público SIGUE público (no rompimos la puerta ni los webhooks) ──────────
def test_login_sigue_publico(prod):
    r = prod.post("/v1/auth/login", json={"email": "x@y.com"})
    # 401/404/400 del handler, NO el 401 no_session del middleware (llega al handler)
    assert not (r.status_code == 401 and
                r.json().get("detail", {}).get("error") == "no_session"), \
        "el middleware bloqueó el login — la puerta quedó tapiada"


def test_webhook_sigue_publico(prod):
    r = prod.post("/v1/payments/webhook/dodo", json={})
    # el webhook se autentica por firma → el middleware NO debe cortarlo con no_session
    assert not (r.status_code == 401 and
                r.json().get("detail", {}).get("error") == "no_session"), \
        "el middleware bloqueó el webhook — los pagos no activarían premium"


def test_catalogo_GET_sigue_navegable_sin_sesion(prod):
    r = prod.get("/v1/catalog/search?q=github")
    assert r.status_code != 401 or \
        r.json().get("detail", {}).get("error") != "no_session", \
        "el catálogo dejó de ser navegable sin sesión (rompe onboarding)"


# ── Con el opt-out (dev), la mutación anónima vuelve a pasar (los harnesses) ───
@pytest.mark.db
def test_con_opt_out_el_anonimo_pasa(monkeypatch):
    monkeypatch.setenv("PUPPET_ALLOW_ANON_V1", "1")
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/v1/puppets/run",
               json={"recipe": {"model": "stub", "belt": {}, "framing": "x",
                                "tool_filters": {}, "max_turns": 1}, "prompt": "x"})
    # con el opt-out el middleware no corta → llega al handler (no es el 401 no_session)
    assert not (r.status_code == 401 and
                r.json().get("detail", {}).get("error") == "no_session"), \
        "el opt-out de dev no relajó el middleware — los harnesses no correrían"
