"""
test_router_bridge_pending.py — FIX F (§9·F) · el export del puente D3 es best-effort, pero en un
deploy read-only (FS de solo-lectura, topología mainstream de containers) el export FALLA en silencio
y el puppet igual devuelve 201 → el agente colocado queda PERMANENTEMENTE no-delegable sin que nadie
lo sepa (delegation omite el agent_ref que no resuelve, sin ruido). El fix: cuando el export lanza,
la respuesta create/update lleva `bridge_pending: true` (no-fatal, sigue 201) para que la UI sepa.

Sin DB: montamos el router con get_conn STUB y monkeypatcheamos repo.session_owner / repo.create_puppet
/ repo.update_config + agent_catalog.export_agent (que RAISE para simular el FS read-only). Verifica el
contrato HTTP real (el flag aparece cuando falla, ausente cuando el export sale bien).
"""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.phase1 import repo, agent_catalog
from app.phase1.router import build_phase1_router

_OWNER = "44444444-4444-4444-8444-444444444444"
_PUPPET_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def client(tmp_path):
    events_root = tmp_path / "spaces"
    events_root.mkdir()

    class _DummyConn:
        raw = None

        def __init__(self):
            self.raw = self

        def execute(self, *_args, **_kwargs):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    app = FastAPI()
    app.include_router(build_phase1_router(get_conn=lambda: _DummyConn(),
                                           events_dir=lambda: events_root))
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_repo(monkeypatch):
    # AUTHZ: la sesión es dueña de lo que reclama (owner == token owner)
    monkeypatch.setattr(repo, "session_owner", lambda token: _OWNER)
    monkeypatch.setattr(repo, "puppet_owner", lambda conn, pid: _OWNER)

    def _create(conn, *, owner_id, name, nicho, config, **kw):
        return {"id": _PUPPET_ID, "owner_id": owner_id, "name": name,
                "nicho": nicho, "config": config, "version": 1, "status": "draft"}

    def _update(conn, pid, config):
        return {"id": pid, "owner_id": _OWNER, "config": config, "version": 2, "status": "draft"}

    monkeypatch.setattr(repo, "create_puppet", _create)
    monkeypatch.setattr(repo, "update_config", _update)


def _body(valid_recipe):
    return {"owner_id": _OWNER, "name": "Sub agente", "nicho": "finanzas", "config": valid_recipe}


_HDRS = {"Authorization": "Bearer tok"}


def test_create_flags_bridge_pending_when_export_raises(client, monkeypatch, valid_recipe):
    # simula el FS read-only: el exporter lanza (OSError EROFS es lo que da un deploy read-only)
    def _boom(row, repo_root):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(agent_catalog, "export_agent", _boom)
    r = client.post("/v1/puppets", json=_body(valid_recipe), headers=_HDRS)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == _PUPPET_ID
    assert body.get("bridge_pending") is True, \
        "export falló pero la respuesta NO señaló bridge_pending (asesino silencioso · §9·F)"


def test_create_no_flag_when_export_succeeds(client, monkeypatch, valid_recipe):
    monkeypatch.setattr(agent_catalog, "export_agent", lambda row, repo_root: None)
    r = client.post("/v1/puppets", json=_body(valid_recipe), headers=_HDRS)
    assert r.status_code == 201
    body = r.json()
    # el export salió bien → NO se agrega ruido a la respuesta
    assert "bridge_pending" not in body


def test_update_flags_bridge_pending_when_export_raises(client, monkeypatch, valid_recipe):
    def _boom(row, repo_root):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(agent_catalog, "export_agent", _boom)
    r = client.put(f"/v1/puppets/{_PUPPET_ID}/config", json={"config": valid_recipe}, headers=_HDRS)
    assert r.status_code == 200
    assert r.json().get("bridge_pending") is True


def test_create_model_use_ref_materializes_route_server_side(
    client, monkeypatch, valid_recipe
):
    """Cuarto persiste un id; el cliente no decide URL/proveedor ejecutables."""
    from app.phase1 import centro_modelos

    monkeypatch.setattr(agent_catalog, "export_agent", lambda row, repo_root: None)
    monkeypatch.setattr(
        centro_modelos,
        "selector_modelos",
        lambda **_kwargs: {
            "default_id": "codex_cli",
            "modelos": [{
                "picker_id": "codex_cli",
                "label": "Codex",
                "model": "codex-cli-canonical",
                "base_url": "http://canonical.invalid/v1",
                "brain_provider": "codex_cli",
                "conectado": True,
                "model_use_capabilities": ["text", "streaming", "tool_calling"],
            }],
        },
    )

    recipe = deepcopy(valid_recipe)
    recipe["model"] = {
        "primary": "modelo-controlado-por-cliente",
        "base_url": "https://cliente.invalid/v1",
        "temperature": 0.17,
        "max_tokens": 2048,
        "max_turns": 8,
        "workers": {"primary": "worker-especial", "max_tokens": 99},
    }
    payload = _body(recipe)
    payload["model_selection_ref"] = "codex_cli"

    response = client.post("/v1/puppets", json=payload, headers=_HDRS)

    assert response.status_code == 201, response.text
    stored = response.json()["config"]
    assert stored["model"]["primary"] == "codex-cli-canonical"
    assert stored["model"]["base_url"] == "http://canonical.invalid/v1"
    assert stored["model"]["temperature"] == 0.17
    assert stored["model"]["workers"] == recipe["model"]["workers"]
    assert stored["model_use"]["selection_ref"] == "codex_cli"


def test_create_model_use_ref_fails_strong_when_selection_does_not_exist(
    client, monkeypatch, valid_recipe
):
    from app.phase1 import centro_modelos

    monkeypatch.setattr(centro_modelos, "selector_modelos", lambda **_kwargs: {
        "default_id": None, "modelos": [],
    })
    payload = _body(valid_recipe)
    payload["model_selection_ref"] = "fantasma"

    response = client.post("/v1/puppets", json=payload, headers=_HDRS)

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "selection_not_found"
