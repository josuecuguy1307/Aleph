"""Agent delete API: canonical DB deletion for both device-local and synced accounts."""
from __future__ import annotations

import os


_RECIPE = {
    "schema_version": "v1",
    "meta": {"name": "agent-to-delete", "nicho": "general"},
    "model": {"primary": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1",
              "temperature": 0, "max_tokens": 1024, "max_turns": 6},
    "belt": {"belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"],
             "tool_filters": {"calc": ["add"]}},
    "framing": {"inline": "test"},
    "rag": {"enabled": False},
    "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
}


def test_delete_agent_persists_for_local_and_synced_users(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1 import repo, router

    old = {key: os.environ.get(key) for key in ("ALEPH_ROLE", "PUPPET_SQLITE_PATH")}
    db_path = str(tmp_path / "agent-delete.db")
    monkeypatch.setenv("ALEPH_ROLE", "client")
    monkeypatch.setenv("PUPPET_SQLITE_PATH", db_path)
    repo._db = None
    try:
        raw = repo._dbmod()._sqlite().conectar(db_path)
        repo._dbmod()._sqlite().crear_schema(raw)
        raw.commit()
        raw.close()
        removed_exports = []
        export_root = tmp_path / "exports"
        export_dir = export_root / "catalog" / "agents"
        export_dir.mkdir(parents=True)
        monkeypatch.setattr(router.agent_catalog, "export_agent", lambda *_args: None)
        real_remove_export = router.agent_catalog.delete_agent_export
        def remove_export(puppet_id, _root):
            removed_exports.append(puppet_id)
            return real_remove_export(puppet_id, export_root)
        monkeypatch.setattr(router.agent_catalog, "delete_agent_export", remove_export)

        app = FastAPI()
        app.include_router(router.build_phase1_router(get_conn=repo.get_conn,
                                                      events_dir=lambda: tmp_path))
        client = TestClient(app, raise_server_exceptions=False)

        conn = repo.get_conn()
        device = repo.get_or_create_device_user(conn)
        synced = repo.register_user(conn, "synced-delete@test.local", "delete-test-password")
        local_agent = repo.create_puppet(conn, owner_id=str(device["id"]),
            name="Local agent", nicho="general", config=_RECIPE)
        synced_agent = repo.create_puppet(conn, owner_id=str(synced["id"]),
            name="Synced agent", nicho="general", config=_RECIPE)
        conn.close()
        local_auth = {"Authorization": "Bearer " + repo.mint_session(str(device["id"]))}
        synced_auth = {"Authorization": "Bearer " + repo.mint_session(str(synced["id"]))}

        for agent in (local_agent, synced_agent):
            (export_dir / f"agent-{agent['id']}.config.json").write_text("{}", encoding="utf-8")

        # Both identities hit the same persisted catalog contract; no localStorage-only path.
        for owner, agent, auth in ((device, local_agent, local_auth),
                                   (synced, synced_agent, synced_auth)):
            deleted = client.delete(f"/v1/puppets/{agent['id']}", headers=auth)
            assert deleted.status_code == 200, deleted.text
            assert deleted.json() == {"deleted": True, "id": agent["id"]}
            listed = client.get(f"/v1/users/{owner['id']}/puppets", headers=auth)
            assert listed.status_code == 200, listed.text
            assert all(row["id"] != agent["id"] for row in listed.json()["puppets"])
            check_conn = repo.get_conn()
            assert repo.get_puppet(check_conn, agent["id"]) is None
            check_conn.close()

        assert removed_exports == [local_agent["id"], synced_agent["id"]]
        assert not list(export_dir.glob("agent-*.config.json"))

        # Ownership remains enforced; a different account cannot delete or hide the row.
        conn = repo.get_conn()
        protected = repo.create_puppet(conn, owner_id=str(device["id"]),
            name="Protected local agent", nicho="general", config=_RECIPE)
        conn.close()
        denied = client.delete(f"/v1/puppets/{protected['id']}", headers=synced_auth)
        # Match the existing _authorize contract: a valid session belonging to
        # another account is 403 (an absent agent is 404).
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"]["error"] == "forbidden"
        assert removed_exports == [local_agent["id"], synced_agent["id"]]
        check_conn = repo.get_conn()
        assert repo.get_puppet(check_conn, protected["id"]) is not None
        check_conn.close()

        # If the derived export cannot be removed, keep the source row and report failure.
        def fail_remove(*_args):
            raise PermissionError("fixture")
        monkeypatch.setattr(router.agent_catalog, "delete_agent_export", fail_remove)
        failed = client.delete(f"/v1/puppets/{protected['id']}", headers=local_auth)
        assert failed.status_code == 503
        assert failed.json()["detail"]["error"] == "agent_delete_failed"
        check_conn = repo.get_conn()
        assert repo.get_puppet(check_conn, protected["id"]) is not None
        check_conn.close()
    finally:
        repo._db = None
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
