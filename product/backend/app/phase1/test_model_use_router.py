from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.phase1 import centro_modelos, repo
from app.phase1.model_use_router import build_model_use_router


def _catalog(*_args, **_kwargs):
    return {
        "default_id": "codex_cli",
        "modelos": [{
            "picker_id": "codex_cli",
            "slug": "cli.codex_cli",
            "label": "Codex",
            "marca": "OpenAI",
            "familia": "cli",
            "model": "codex-cli",
            "base_url": "http://127.0.0.1:8926/v1",
            "brain_provider": "codex_cli",
            "conectado": True,
            "model_use_capabilities": ["streaming", "tool_calling"],
            "default": True,
        }],
    }


def _client(monkeypatch):
    monkeypatch.setattr(repo, "session_owner", lambda token: "owner-1" if token == "ok" else None)
    monkeypatch.setattr(centro_modelos, "selector_modelos", _catalog)
    app = FastAPI()
    app.include_router(build_model_use_router())
    return TestClient(app)


def test_choices_exige_owner_y_no_expone_infraestructura(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/v1/model-use/choices").status_code == 401

    response = client.get("/v1/model-use/choices", headers={"Authorization": "Bearer ok"})
    assert response.status_code == 200
    body = response.json()
    assert body["search_threshold"] == 12
    assert body["choices"][0]["selection_ref"] == "codex_cli"
    rendered = repr(body)
    assert "base_url" not in rendered
    assert "8926" not in rendered
    assert "brain_provider" not in rendered


def test_resolve_hace_preflight_sin_ejecutar(monkeypatch):
    client = _client(monkeypatch)
    response = client.post("/v1/model-use/resolve", headers={"Authorization": "Bearer ok"}, json={
        "schema_version": "model-use/v1",
        "call_id": "call-1",
        "idempotency_key": "idem-1",
        "workspace_id": "ciencia",
        "call_class": "science.main",
        "context": {"session_id": "session-1", "agent_id": None},
        "selection_ref": "codex_cli",
        "selection_scope": "session",
        "capabilities": {"required": ["streaming", "tool_calling"]},
        "input": {"messages": []},
        "tools": {"definitions": [{"type": "function"}], "required": True},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["admitted"] is True
    assert body["selection_ref"] == "codex_cli"
    rendered = repr(body)
    assert "owner-1" not in rendered
    assert "connection_ref" not in rendered
    assert "codex-cli" not in rendered


def test_resolve_rechaza_owner_en_body(monkeypatch):
    client = _client(monkeypatch)
    response = client.post("/v1/model-use/resolve", headers={"Authorization": "Bearer ok"}, json={
        "schema_version": "model-use/v1",
        "call_id": "call-1",
        "idempotency_key": "idem-1",
        "workspace_id": "ciencia",
        "call_class": "science.main",
        "context": {},
        "selection_ref": "codex_cli",
        "selection_scope": "default",
        "owner_id": "attacker",
    })
    assert response.status_code == 422
