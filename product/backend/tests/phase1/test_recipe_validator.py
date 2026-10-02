"""
test_recipe_validator.py — el Workshop valida la receta v1 anidada y RECHAZA lo que
rompe el contrato taller↔assembler (RECIPE-SCHEMA.md, A+A+C) + INVARIANTE §3.5.
"""

import json

import pytest

from app.phase1 import recipe_validator as rv
from app.phase1.recipe_validator import RecipeValidationError


def test_valid_recipe_passes(valid_recipe):
    # belt_ref '.md' no resuelve a .mcp.json → warning 'no-resoluble', NO error (portable).
    warnings = rv.validate_recipe(valid_recipe)
    assert isinstance(warnings, list)


def test_missing_schema_version_fails(valid_recipe):
    del valid_recipe["schema_version"]
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("schema_version" in e for e in ei.value.errors)


def test_wrong_schema_version_fails(valid_recipe):
    valid_recipe["schema_version"] = "v2"
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("schema_version" in e for e in ei.value.errors)


def test_missing_required_model_fields_fails(valid_recipe):
    del valid_recipe["model"]["base_url"]
    del valid_recipe["model"]["max_turns"]
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    errs = " ".join(ei.value.errors)
    assert "base_url" in errs and "max_turns" in errs


def test_temperature_out_of_range_fails(valid_recipe):
    valid_recipe["model"]["temperature"] = 3.5
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("temperature" in e for e in ei.value.errors)


def test_nicho_specific_top_key_rejected(valid_recipe):
    # §3.2: forma nicho-agnóstica — prohibido inventar una clave de nivel-tope.
    valid_recipe["finanzas_only_thing"] = {"x": 1}
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("no permitida" in e for e in ei.value.errors)


def test_model_use_reference_is_allowed_but_routing_fields_are_not(valid_recipe):
    valid_recipe["model_use"] = {
        "schema_version": "model-use/v1",
        "selection_ref": "codex_cli",
        "selection_scope": "agent",
    }
    rv.validate_recipe(valid_recipe)

    valid_recipe["model_use"]["base_url"] = "https://cliente.invalid/v1"
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("model_use contiene claves no permitidas" in e for e in ei.value.errors)


def test_belt_ref_absolute_path_rejected(valid_recipe):
    # decisión B: belt_ref es PORTABLE; un path absoluto del host lo rompe.
    valid_recipe["belt"]["belt_ref"] = "/Users/TEST_ONLY/host/belt.mcp.json"
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("absoluto" in e for e in ei.value.errors)


def test_empty_tool_filters_rejected(valid_recipe):
    valid_recipe["belt"]["tool_filters"] = {}
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("tool_filters" in e for e in ei.value.errors)


def test_plaintext_key_in_recipe_rejected(valid_recipe):
    # §3.4: PROHIBIDO una credencial en claro dentro de la receta.
    valid_recipe["keys"]["fred"] = {"byok_ref": "keys:fred", "value": "sk-supersecret"}
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("EN CLARO" in e for e in ei.value.errors)


def test_byok_ref_must_have_prefix(valid_recipe):
    valid_recipe["keys"]["fred"] = {"byok_ref": "fred"}  # falta 'keys:'
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(valid_recipe)
    assert any("keys:" in e for e in ei.value.errors)


# ── INVARIANTE §3.5 — la receta DECLARA, Security HACE CUMPLIR ──────────────────

def test_mandatory_gate_off_is_ignored_warns(valid_recipe):
    # la receta pone 'off' un mandatorio → válida PERO con warning; el motor lo fuerza.
    valid_recipe["gates"]["money_touch"] = "off"
    warnings = rv.validate_recipe(valid_recipe)
    assert any("money_touch" in w and "IGNORA" in w for w in warnings)


def test_effective_gates_forces_mandatory_when_off(valid_recipe):
    valid_recipe["gates"] = {"money_touch": "off", "send": "off"}
    eff = rv.effective_gates(valid_recipe)
    assert eff["money_touch"] == "needs_ok"
    assert eff["send"] == "needs_ok"


def test_effective_gates_forces_mandatory_when_omitted(valid_recipe):
    valid_recipe.pop("gates", None)
    eff = rv.effective_gates(valid_recipe)
    # la OMISIÓN no desactiva un mandatorio.
    assert eff["money_touch"] == "needs_ok"
    assert eff["send"] == "needs_ok"


def test_recipe_can_add_stricter_gate(valid_recipe):
    valid_recipe["gates"]["delete_data"] = "needs_ok"  # gate EXTRA (la receta puede agregar)
    eff = rv.effective_gates(valid_recipe)
    assert eff["delete_data"] == "needs_ok"
    assert eff["money_touch"] == "needs_ok"


def test_belt_ref_resolves_and_validates_phantom_server(tmp_path):
    # Belt resoluble: un server fantasma en tool_filters DEBE fallar (§3.3).
    belt = tmp_path / "catalog" / "belts" / "mini.mcp.json"
    belt.parent.mkdir(parents=True, exist_ok=True)
    belt.write_text('{"mcpServers": {"echo": {"command": "x"}}}', encoding="utf-8")
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "T", "nicho": "test"},
        "model": {"primary": "m", "base_url": "u", "temperature": 0,
                  "max_tokens": 10, "max_turns": 2},
        "belt": {"belt_ref": "mini", "tool_filters": {"ghost": ["foo"]}},
        "rag": {"enabled": False},
    }
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(recipe, repo_root=tmp_path)
    assert any("fantasma" in e for e in ei.value.errors)


# ── §3.3 · LA UNIÓN DE BELTS (regresión de la integración tanda-P) ─────────────
# `ensure_kit` (FIX-P4) PRESERVA el `belt_ref` singular y además siembra `belt_refs[]`
# con el kit. §3.3 medía sólo el singular, así que todo server que viniera del segundo
# belt salía «fantasma» y `POST /v1/puppets` devolvía 422 para CUALQUIER receta con
# belt_ref singular. Estos tres tests son el contrato que faltaba.

def _belt(tmp_path, slug, servers):
    p = tmp_path / "catalog" / "belts" / f"{slug}.mcp.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mcpServers": {s: {"command": "x"} for s in servers}}), encoding="utf-8")
    return p


def _receta(belt):
    return {
        "schema_version": "v1",
        "meta": {"name": "T", "nicho": "test"},
        "model": {"primary": "m", "base_url": "u", "temperature": 0,
                  "max_tokens": 10, "max_turns": 2},
        "belt": belt, "rag": {"enabled": False},
    }


def test_belt_refs_union_acepta_servers_del_segundo_belt(tmp_path):
    """EL CASO QUE ROMPÍA: singular + belt_refs[] — los servers del kit son legítimos."""
    _belt(tmp_path, "research", ["arxiv"])
    _belt(tmp_path, "kit", ["sqlite", "duckduckgo"])
    receta = _receta({
        "belt_ref": "research",
        "belt_refs": ["research", "kit"],
        "tool_filters": {"arxiv": ["search_papers"], "sqlite": ["read_query"]},
    })
    rv.validate_recipe(receta, repo_root=tmp_path)   # no levanta: la unión los tiene


def test_belt_refs_union_sigue_cazando_al_fantasma_de_verdad(tmp_path):
    """CONTRA-PRUEBA: la regla no se aflojó — un server que no está en NINGUNO cae."""
    _belt(tmp_path, "research", ["arxiv"])
    _belt(tmp_path, "kit", ["sqlite"])
    receta = _receta({
        "belt_ref": "research",
        "belt_refs": ["research", "kit"],
        "tool_filters": {"ghost": ["foo"]},
    })
    with pytest.raises(RecipeValidationError) as ei:
        rv.validate_recipe(receta, repo_root=tmp_path)
    assert any("fantasma" in e and "ghost" in e for e in ei.value.errors)


def test_belt_no_resoluble_no_acusa_fantasma(tmp_path):
    """Si UN belt no resuelve, el server podría vivir ahí: warning, jamás error."""
    _belt(tmp_path, "research", ["arxiv"])
    receta = _receta({
        "belt_ref": "research",
        "belt_refs": ["research", "no-existe-en-disco"],
        "tool_filters": {"sqlite": ["read_query"]},
    })
    warnings = rv.validate_recipe(receta, repo_root=tmp_path)
    assert any("no se pudo resolver" in w for w in warnings)
