"""
test_router.py — los endpoints HTTP de Fase 1 vía TestClient (sin bindear puerto).

Cubre lo que NO necesita DB: validación de receta (b), el 422 al guardar una receta
inválida, el stream SSE (c) con replay, y el handler de BYOKFailure → 424 tipado (e).
Los endpoints que tocan DB se prueban en test_db_integration.py (capa repo) — acá
montamos un get_conn STUB para no depender de Postgres en el test de routing puro.
"""

import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.phase1.router import build_phase1_router, install_byok_handler
from app.phase1.byok import BYOKFailure, BYOKReason

REPO_ROOT = Path(__file__).resolve().parents[4]
ER_PY = REPO_ROOT / "platform" / "flywheel" / "events_replay.py"


@pytest.fixture
def app_and_dir(tmp_path, monkeypatch):
    events_root = tmp_path / "spaces"
    events_root.mkdir()

    # La autorización Fernet ya no es stateless: usa una DB separada para probar el
    # borde real, mientras el get_conn inyectado al router sigue fallando a propósito.
    import sqlite_db
    from app.phase1 import repo
    auth_path = tmp_path / "auth.sqlite"
    auth_conn = sqlite_db.conectar(str(auth_path))
    sqlite_db.crear_schema(auth_conn)
    with auth_conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email) VALUES (%s, %s)", ("x", "x@test.invalid"))
    auth_conn.commit()
    auth_conn.close()
    monkeypatch.setattr(repo, "get_conn", lambda dbname=None: sqlite_db.conectar(str(auth_path)))

    def _get_conn():
        raise RuntimeError("DB stubbed-off en test de routing")  # fuerza 503 tipado

    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=_get_conn, events_dir=lambda: events_root))
    install_byok_handler(app)

    # endpoint de prueba que LANZA una BYOKFailure a media tarea (simula el loop).
    @app.get("/_test/byok_fail")
    def _byok_fail():
        raise BYOKFailure(provider="fred", reason=BYOKReason.INVALID,
                          run_id="r-123", tool="get_financials")

    return app, events_root


@pytest.fixture
def app_stream_anon(tmp_path):
    """App para los tests del stream: desde T6 (ba4cb6f3, §4.5) el stream resuelve el
    DUEÑO del space en DB ANTES de abrir (space con dueño ⇒ solo el dueño; space
    anónimo ⇒ lectura abierta). Acá la DB fake responde "sin filas" (space anónimo)
    para poder probar la mecánica SSE (replay/404) — con el get_conn que LANZA, el
    lookup del dueño daría 503 antes de llegar al stream."""
    events_root = tmp_path / "spaces"
    events_root.mkdir()

    class _CurSinFilas:
        def execute(self, *a, **k): pass
        def fetchone(self): return None
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    class _ConnAnon:
        def cursor(self): return _CurSinFilas()
        def close(self): pass

    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=_ConnAnon, events_dir=lambda: events_root))
    return app, events_root


def _sesion(uid: str) -> dict:
    # sesión REAL acuñada con la misma lib y generación en DB — §4.5:
    # los endpoints con identidad exigen owner == sesión ANTES de validar.
    from app.phase1 import repo
    return {"Authorization": "Bearer " + repo.mint_session(uid)}


def test_validate_recipe_endpoint_ok(app_and_dir, valid_recipe):
    app, _ = app_and_dir
    client = TestClient(app)
    r = client.post("/v1/recipes/validate", json={"recipe": valid_recipe})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    # §3.5: effective_gates muestra los mandatorios.
    assert body["effective_gates"]["money_touch"] == "needs_ok"
    assert body["effective_gates"]["send"] == "needs_ok"


def test_validate_recipe_endpoint_rejects_invalid(app_and_dir, valid_recipe):
    app, _ = app_and_dir
    client = TestClient(app)
    del valid_recipe["model"]["base_url"]
    r = client.post("/v1/recipes/validate", json={"recipe": valid_recipe})
    assert r.status_code == 200  # validate no es error HTTP; reporta valid:false
    body = r.json()
    assert body["valid"] is False
    assert any("base_url" in e for e in body["errors"])


def test_validate_shows_forced_gate_even_when_recipe_says_off(app_and_dir, valid_recipe):
    app, _ = app_and_dir
    client = TestClient(app)
    valid_recipe["gates"]["money_touch"] = "off"
    r = client.post("/v1/recipes/validate", json={"recipe": valid_recipe})
    body = r.json()
    # válida con warning, y effective_gates igual lo muestra forzado.
    assert body["valid"] is True
    assert body["effective_gates"]["money_touch"] == "needs_ok"
    assert any("money_touch" in w for w in body["warnings"])


def test_create_puppet_rejects_invalid_before_db(app_and_dir, valid_recipe):
    # con sesión del owner (§4.5: la auth va PRIMERO — anónimo daría 401 acá),
    # receta inválida ⇒ 422 ANTES de tocar la DB (el get_conn stub ni se llama).
    app, _ = app_and_dir
    client = TestClient(app)
    del valid_recipe["belt"]["belt_ref"]
    r = client.post("/v1/puppets", json={
        "owner_id": "x", "name": "n", "nicho": "finanzas", "config": valid_recipe,
    }, headers=_sesion("x"))
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "recipe_invalid"


def test_create_puppet_valid_recipe_hits_db_stub_503(app_and_dir, valid_recipe):
    # con sesión del owner: receta VÁLIDA ⇒ pasa auth (sin DB: Fernet stateless) y
    # validación, y llega al get_conn (stub) ⇒ 503 tipado, no crash.
    app, _ = app_and_dir
    client = TestClient(app)
    r = client.post("/v1/puppets", json={
        "owner_id": "x", "name": "n", "nicho": "finanzas", "config": valid_recipe,
    }, headers=_sesion("x"))
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "db_unavailable"


def test_byok_failure_returns_424_typed_signal(app_and_dir):
    # (e): la excepción de dominio se mapea a 424 + señal tipada → screen 11. NO 500.
    app, _ = app_and_dir
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/_test/byok_fail")
    assert r.status_code == 424
    sig = r.json()
    assert sig["error"] == "byok_failure"
    assert sig["screen"] == "screen_11"
    assert sig["provider"] == "fred"
    assert sig["reason"] == "invalid"
    assert sig["recoverable"] is True
    assert sig["run_id"] == "r-123"
    assert sig["tool"] == "get_financials"
    assert isinstance(sig["user_message"], str) and sig["user_message"]


def test_sse_stream_replays_events(app_stream_anon):
    app, events_root = app_stream_anon
    # escribe un events.jsonl con la lib REAL del loop.
    spec = importlib.util.spec_from_file_location("er_router", ER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sp_dir = events_root / "sp_http"
    sp_dir.mkdir()
    log = mod.EventLog(sp_dir / "events.jsonl")
    log.append({"type": "belt_ready", "space_id": "sp_http", "payload": {"tools": ["echo"]}})
    log.append({"type": "final", "space_id": "sp_http", "payload": {"answer": "ok"}})
    log.append({"type": "closed", "space_id": "sp_http", "payload": {}})

    client = TestClient(app)
    with client.stream("GET", "/v1/spaces/sp_http/stream?last_event_id=0") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = "".join(chunk for chunk in resp.iter_text())
    assert "event: belt_ready" in text
    assert "event: final" in text
    assert "event: closed" in text
    assert "id: 1" in text


def test_sse_stream_404_unknown_space(app_stream_anon):
    app, _ = app_stream_anon
    client = TestClient(app)
    r = client.get("/v1/spaces/nope/stream")
    assert r.status_code == 404
