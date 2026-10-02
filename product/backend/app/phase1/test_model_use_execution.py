from app.phase1.model_use_contract import RouteSnapshot
from app.phase1.model_use_execution import (
    canonicalize_recipe_selection,
    materialize_model_config,
    materialize_recipe,
    selection_ref_for_recipe,
)


def _catalog():
    return {"modelos": [
        {
            "picker_id": "codex_cli", "model": "codex-cli", "base_url": "http://brain/v1",
            "brain_provider": "codex_cli", "alias": "codex_cli", "conectado": True,
            "model_use_capabilities": ["text", "streaming", "tool_calling"],
        },
        {
            "picker_id": "api:openai", "model": "gpt-5", "base_url": "https://api/v1",
            "byok_ref": "keys:openai", "conectado": True,
            "model_use_capabilities": ["text", "streaming", "tool_calling"],
        },
    ]}


def _snapshot(ref="codex_cli", model="codex-cli"):
    return RouteSnapshot(
        owner_id="u", workspace_id="sala", call_id="c", selection_ref=ref,
        selection_scope="agent", policy_ref="recipe:v1:a", requirements_hash="sha256:x",
        resolved_model=model, connection_ref="cli:codex_cli", admitted_at=1,
    )


def test_reverse_map_prefiere_identidades_estables():
    assert selection_ref_for_recipe(
        {"model": {"brain_provider": "codex_cli", "primary": "otro"}}, _catalog()
    ) == "codex_cli"
    assert selection_ref_for_recipe(
        {"model": {"byok_ref": "keys:openai", "primary": "gpt-5"}}, _catalog()
    ) == "api:openai"


def test_reverse_map_no_adivina_modelo_ambiguo():
    catalog = _catalog()
    catalog["modelos"].append({
        "picker_id": "api:other", "model": "gpt-5", "base_url": "https://other/v1",
    })
    assert selection_ref_for_recipe({"model": {"primary": "gpt-5"}}, catalog) is None


def test_materializacion_descarta_routing_cliente_y_preserva_controles():
    current = {
        "primary": "cliente", "base_url": "https://evil.invalid", "api_key": "secret",
        "temperature": 0.2, "max_tokens": 900, "max_turns": 12,
        "workers": {"primary": "worker", "base_url": "http://worker/v1"},
    }
    cfg = materialize_model_config(_snapshot(), _catalog(), current=current)
    assert cfg["primary"] == "codex-cli"
    assert cfg["base_url"] == "http://brain/v1"
    assert cfg["brain_provider"] == "codex_cli"
    assert "api_key" not in cfg
    assert cfg["temperature"] == 0.2 and cfg["max_turns"] == 12
    assert cfg["workers"] == current["workers"]


def test_receta_guarda_referencia_canónica_sin_tocar_oficio():
    recipe = {
        "schema_version": "v1", "meta": {"name": "A"},
        "model": {"primary": "viejo", "base_url": "x", "temperature": 0},
        "belt": {"agent_refs": ["hijo"]},
    }
    out = materialize_recipe(recipe, _snapshot(), _catalog())
    assert out["model_use"]["selection_ref"] == "codex_cli"
    assert out["belt"] == recipe["belt"]
    assert recipe["model"]["primary"] == "viejo"


def test_guardado_secretless_materializa_recipe_legacy_para_rollback():
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "A", "nicho": "general"},
        # El navegador manda perillas, no infraestructura.
        "model": {"temperature": 0.4, "max_tokens": 800, "max_turns": 9},
        "belt": {"belt_ref": "x", "tool_filters": {"calc": ["add"]}},
    }
    out = canonicalize_recipe_selection(
        recipe,
        selection_ref="codex_cli",
        owner_id="u",
        agent_id="draft",
        read_catalog=lambda _owner: _catalog(),
    )
    assert out["model"]["primary"] == "codex-cli"
    assert out["model"]["base_url"] == "http://brain/v1"
    assert out["model"]["temperature"] == 0.4
    assert out["model_use"]["selection_ref"] == "codex_cli"
