"""Unit tests for owner/process binding; real UI approval is certified separately."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workspaces import pack


@pytest.fixture
def owner(monkeypatch):
    rows = [{"entity_id": "pack:oficina", "user_id": "owner", "pids": [123]}]
    supervisor = SimpleNamespace(estado=lambda: {"vivas": rows})
    monkeypatch.setattr(pack, "_dueno", lambda: SimpleNamespace(actual=lambda: supervisor))
    monkeypatch.setattr(pack, "_TOKENS_STACK", {"owner::oficina": ((123,), {"host_token": "host-test"})})
    monkeypatch.setattr(pack, "_PUERTOS", {"owner::oficina": 43210})
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        if kwargs.get("metodo") == "POST": return 200, {"allowed": kwargs["cuerpo"]["reply"] == "allow"}
        return 200, {"items": [
            {"id": "file-1", "action": "workspace.file.write", "summary": "Write test.xlsx", "actor": {"tokenHash": "private"}},
            {"id": "admin-1", "action": "engine.reload", "summary": "Admin action"},
        ]}
    monkeypatch.setattr(pack, "_pedir_json", request)
    return rows, calls


def test_another_user_cannot_read_or_decide(owner):
    _, calls = owner
    with pytest.raises(pack.PackError): pack.aprobaciones_oficina({}, user_id="other")
    with pytest.raises(pack.PackError): pack.aprobaciones_oficina({}, user_id="other", solicitud="file-1", permitir=True)
    assert calls == []


def test_stale_process_credentials_are_rejected(owner):
    rows, calls = owner
    rows[0]["pids"] = [456]
    with pytest.raises(pack.PackError): pack.aprobaciones_oficina({}, user_id="owner")
    assert calls == []


def test_only_pending_file_writes_are_exposed_without_host_credentials(owner):
    result = pack.aprobaciones_oficina({}, user_id="owner")
    assert [item["id"] for item in result["items"]] == ["file-1"]
    assert "host-test" not in str(result) and "private" not in str(result)
    with pytest.raises(pack.PackError): pack.aprobaciones_oficina({}, user_id="owner", solicitud="admin-1", permitir=True)
    with pytest.raises(pack.PackError): pack.aprobaciones_oficina({}, user_id="owner", solicitud="expired", permitir=True)
    assert all(args.get("metodo") != "POST" for _, args in owner[1])


@pytest.mark.parametrize("allowed", [True, False])
def test_owner_can_explicitly_accept_or_reject_the_exact_pending_write(owner, allowed):
    result = pack.aprobaciones_oficina({}, user_id="owner", solicitud="file-1", permitir=allowed)
    assert result == {"ok": True, "allowed": allowed}
    url, args = owner[1][-1]
    assert url == "http://127.0.0.1:43210/approvals/file-1"
    assert args["cuerpo"] == {"reply": "allow" if allowed else "deny"}
