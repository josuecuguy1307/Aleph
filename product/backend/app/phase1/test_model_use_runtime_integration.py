from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.phase1.router import build_phase1_router


class _Conn:
    def close(self):
        pass


def _catalog(*_args, **_kwargs):
    return {
        "default_id": "codex_cli",
        "modelos": [{
            "picker_id": "codex_cli",
            "label": "Codex",
            "model": "codex-cli-canonical",
            "base_url": "http://canonical.invalid/v1",
            "alias": "codex_cli",
            "brain_provider": "codex_cli",
            "conectado": True,
            "model_use_capabilities": ["text", "streaming", "tool_calling", "vision"],
        }],
    }


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(build_phase1_router(
        get_conn=lambda: _Conn(), events_dir=lambda: tmp_path,
    ))
    return TestClient(app)


def _common(monkeypatch):
    from app.phase1 import billing, centro_modelos, repo

    monkeypatch.setattr(repo, "session_owner", lambda _token: "owner")
    monkeypatch.setattr(centro_modelos, "selector_modelos", _catalog)
    monkeypatch.setattr(billing, "preflight", lambda *_a, **_k: {"allowed": True})
    monkeypatch.setattr(
        billing, "record_run_cost", lambda *_a, **_k: {"ingested": 0}
    )


def test_raw_aleph_v2_materializa_en_servidor(monkeypatch, tmp_path):
    from app.phase1 import stream_chat

    _common(monkeypatch)
    monkeypatch.setenv("ALEPH_MODEL_ROUTE_SALA_CHAT_RAW", "aleph_v2")
    seen = {}

    def fake_stream(recipe, *_args, **_kwargs):
        seen["model"] = dict(recipe["model"])
        yield "model_final", "codex-cli-canonical"
        yield "token", "hola"

    monkeypatch.setattr(stream_chat, "stream_answer", fake_stream)
    response = _client(tmp_path).post(
        "/v1/puppets/run/stream",
        headers={"Authorization": "Bearer session"},
        json={"prompt": "hola", "model": "codex_cli", "agent": None},
    )

    assert response.status_code == 200
    assert '"answer": "hola"' in response.text
    assert seen["model"]["primary"] == "codex-cli-canonical"
    assert seen["model"]["base_url"] == "http://canonical.invalid/v1"


def test_agente_aleph_v2_no_ejecuta_routing_del_cliente(monkeypatch, tmp_path):
    from app.phase1 import billing, executor, recipe_validator

    _common(monkeypatch)
    monkeypatch.setenv("ALEPH_MODEL_ROUTE_SALA_AGENT_RUN", "aleph_v2")
    monkeypatch.setattr(recipe_validator, "validate_recipe", lambda *_a, **_k: None)
    seen = {}

    def fake_run(recipe, *_args, **_kwargs):
        seen["recipe"] = recipe
        return {"run_id": "r", "answer": "ok", "cost_events": []}

    monkeypatch.setattr(executor, "run_puppet_e2e", fake_run)
    monkeypatch.setattr(billing, "record_run_cost", lambda *_a, **_k: {"ingested": 0})
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "Agente", "nicho": "general"},
        "model": {
            "primary": "modelo-del-cliente",
            "base_url": "https://cliente.invalid/v1",
            "brain_provider": "codex_cli",
            "temperature": 0.1,
            "max_tokens": 700,
            "max_turns": 8,
            "workers": {"primary": "worker", "base_url": "http://worker/v1"},
        },
        "belt": {"belt_ref": "x", "tool_filters": {"calc": ["add"]}},
        "framing": {"inline": ""},
        "rag": {"enabled": False},
        "keys": {},
        "gates": {},
    }
    response = _client(tmp_path).post(
        "/v1/puppets/run",
        headers={"Authorization": "Bearer session"},
        json={"prompt": "hazlo", "recipe": recipe},
    )

    assert response.status_code == 201, response.text
    routed = seen["recipe"]
    assert routed["model"]["primary"] == "codex-cli-canonical"
    assert routed["model"]["base_url"] == "http://canonical.invalid/v1"
    assert routed["model"]["temperature"] == 0.1
    assert routed["model"]["workers"] == recipe["model"]["workers"]
    assert routed["model_use"]["selection_ref"] == "codex_cli"


@pytest.mark.parametrize(
    "workspace", ["legal", "educacion", "ciencia", "diseno", "finanzas", "oficina"]
)
def test_workspace_aleph_v2_conserva_harness_y_tools(
    monkeypatch, tmp_path, workspace
):
    from app.phase1 import workspace_brain

    _common(monkeypatch)
    monkeypatch.setenv(
        f"ALEPH_MODEL_ROUTE_{workspace.upper()}_WORKSPACE_STEP", "aleph_v2"
    )
    seen = {}

    def fake_complete(recipe, messages, tools, **kwargs):
        seen.update(recipe=recipe, messages=messages, tools=tools, kwargs=kwargs)
        return {
            "content": None,
            "tool_calls": [{"id": "c", "name": "science_search", "arguments": "{}"}],
            "model": "codex-cli-canonical",
            "finish_reason": "tool_calls",
            "cost_events": [],
        }

    monkeypatch.setattr(workspace_brain, "complete", fake_complete)
    response = _client(tmp_path).post(
        "/v1/workspaces/brain/complete",
        headers={"Authorization": "Bearer session"},
        json={
            "workspace": workspace,
            "model": "codex_cli",
            "messages": [{"role": "user", "content": "busca"}],
            "tools": [{"type": "function", "function": {
                "name": "science_search", "parameters": {"type": "object"},
            }}],
        },
    )

    assert response.status_code == 200, response.text
    assert seen["recipe"]["model"]["primary"] == "codex-cli-canonical"
    assert seen["tools"][0]["function"]["name"] == "science_search"
    assert response.json()["tool_calls"][0]["name"] == "science_search"
