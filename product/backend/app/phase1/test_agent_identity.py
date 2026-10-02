from app.phase1.agent_catalog import (
    FALLBACK_AGENT_NAME,
    clean_human_name,
    config_with_display_name,
    display_name,
)


_VALID_RECIPE = {
    "schema_version": "v1",
    "meta": {"name": "Luz de prueba", "nicho": "general"},
    "model": {"primary": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1",
              "temperature": 0, "max_tokens": 1024, "max_turns": 6},
    "belt": {"belt_refs": ["platform/assembler/fixtures/belt-calc.mcp.json"],
             "tool_filters": {"calc": ["add"]}},
    "framing": {"inline": "agente de prueba"},
    "rag": {"enabled": False},
    "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
}


def test_keeps_a_human_saved_name():
    assert display_name("Luz, analista de mercado", {"meta": {"name": "Otro"}}) == "Luz, analista de mercado"


def test_uses_legacy_recipe_name_before_a_technical_database_value():
    assert display_name("008-017", {"meta": {"name": "Analista de mercado"}}) == "Analista de mercado"


def test_never_exposes_uuid_or_export_path_as_name():
    uuid = "11111111-1111-4111-8111-111111111111"
    assert clean_human_name(uuid) is None
    assert clean_human_name("catalog/agents/agent-" + uuid + ".config.json") is None
    assert clean_human_name("12345") is None
    assert clean_human_name("agent-12345") is None
    assert clean_human_name("agt-11111111-1111-4111-8111-111111111111") is None
    assert clean_human_name("Aleph login-suave 0e2ceb") is None
    assert display_name(uuid, {"meta": {"name": "agent-" + uuid}}) == FALLBACK_AGENT_NAME


def test_backfill_shape_aligns_legacy_recipe_name_with_visible_name():
    cfg = config_with_display_name({"meta": {"name": "008-017"}, "belt": {}}, "008-017")
    assert cfg["meta"]["name"] == FALLBACK_AGENT_NAME
    assert cfg["belt"] == {}


def test_api_persists_new_name_and_migrates_historical_technical_names(tmp_path, monkeypatch):
    """The real create/list/update contract never returns an ID as an agent name."""
    from copy import deepcopy
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.phase1 import repo, router

    db_path = str(tmp_path / "agent-names.db")
    monkeypatch.setenv("ALEPH_ROLE", "client")
    monkeypatch.setenv("PUPPET_SQLITE_PATH", db_path)
    monkeypatch.setattr(router.agent_catalog, "export_agent", lambda _puppet, _root: None)
    repo._db = None
    try:
        sqlite = repo._dbmod()._sqlite()
        raw = sqlite.conectar(db_path)
        sqlite.crear_schema(raw)
        raw.commit()
        raw.close()

        app = FastAPI()
        app.include_router(router.build_phase1_router(get_conn=repo.get_conn,
                                                      events_dir=lambda: tmp_path))
        client = TestClient(app, raise_server_exceptions=False)
        conn = repo.get_conn()
        user = repo.register_user(conn, "names@test.local", "names-test-password")
        legacy = repo.create_puppet(
            conn, owner_id=str(user["id"]), name="008-017", nicho="general",
            config={"meta": {"name": "catalog/agents/agent-123e4567-e89b-12d3-a456-426614174000.config.json"},
                    "belt": {}},
        )
        conn.close()
        auth = {"Authorization": "Bearer " + repo.mint_session(str(user["id"]))}

        # Creation persists the user name in both compatibility locations.
        response = client.post("/v1/puppets", headers=auth, json={
            "owner_id": str(user["id"]), "name": "Luz de prueba", "nicho": "general",
            "config": deepcopy(_VALID_RECIPE),
        })
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["name"] == "Luz de prueba"
        assert created["config"]["meta"]["name"] == "Luz de prueba"

        # A stale technical meta.name cannot overwrite the saved visible identity.
        changed = deepcopy(created["config"])
        changed["meta"]["name"] = "008-017"
        response = client.put(f"/v1/puppets/{created['id']}/config", headers=auth,
                              json={"config": changed})
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Luz de prueba"
        assert response.json()["config"]["meta"]["name"] == "Luz de prueba"

        # Listing is the backward-compatible migration boundary and persists its fallback.
        listed = client.get(f"/v1/users/{user['id']}/puppets", headers=auth)
        assert listed.status_code == 200, listed.text
        by_id = {row["id"]: row for row in listed.json()["puppets"]}
        assert by_id[legacy["id"]]["name"] == FALLBACK_AGENT_NAME
        assert by_id[legacy["id"]]["config"]["meta"]["name"] == FALLBACK_AGENT_NAME
        conn = repo.get_conn()
        persisted = repo.get_puppet(conn, legacy["id"])
        conn.close()
        assert persisted["name"] == FALLBACK_AGENT_NAME

        # The API rejects a raw identifier before it can enter the database.
        rejected = client.post("/v1/puppets", headers=auth, json={
            "owner_id": str(user["id"]), "name": "123e4567-e89b-12d3-a456-426614174000",
            "nicho": "general", "config": deepcopy(_VALID_RECIPE),
        })
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["error"] == "agent_name_required"
    finally:
        repo._db = None
