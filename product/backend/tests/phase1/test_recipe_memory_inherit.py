"""ORDEN 6 · el validador acepta memory.inherit (el productor vivo del selector de herencia).

El executor YA leía recipe.memory.inherit en el A3-read (orden 4), pero el validador exigía
shared+ref si la sección memory estaba presente → ninguna receta VÁLIDA podía llevar la política
(el cabo LOW). Order 6 abre los DOS sub-bloques (bus compartido · herencia) como independientes y
opcionales, sin romper el bus clásico ni las recetas sin sección memory (byte-idénticas).
"""
import pytest

from app.phase1 import recipe_validator as rv


def _base(**extra):
    r = {
        "schema_version": "v1", "meta": {"name": "A", "nicho": "general"},
        "model": {"primary": "opus", "base_url": "https://gw.local",
                  "temperature": 0, "max_tokens": 256, "max_turns": 3},
        "framing": {"inline": ""}, "rag": {"enabled": False},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-calc.mcp.json",
                 "tool_filters": {"calc": ["add"]}},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }
    r.update(extra)
    return r


def _valid(recipe) -> bool:
    try:
        rv.validate_recipe(recipe, repo_root=None)
        return True
    except rv.RecipeValidationError:
        return False


@pytest.mark.parametrize("memory,should_pass", [
    (None, True),                                              # sin sección → byte-idéntico
    ({"inherit": "skill_only"}, True),                         # el productor del selector (orden 6)
    ({"inherit": None}, True),                                 # continuación explícita
    ({"inherit": {"projects": ["run-1"]}}, True),              # herencia por proyecto
    ({"inherit": {"entries": ["m-1", "m-2"]}}, True),          # herencia por entrada
    ({"inherit": {"projects": "x"}}, False),                   # projects no-lista → error de contrato
    ({"inherit": 5}, False),                                   # forma ajena → error
    ({"shared": True, "ref": "product/belts/x.mcp.json"}, True),   # bus clásico intacto
    ({"shared": True}, False),                                 # bus incompleto (falta ref)
    ({"shared": True, "ref": "product/belts/x.mcp.json",
      "inherit": "skill_only"}, True),                         # bus + herencia coexisten
    ({}, False),                                               # ni bus ni inherit → vacío inválido
    ({"shared": True, "ref": "/etc/passwd"}, False),           # ref absoluto → portabilidad rota
])
def test_memory_block_variants(memory, should_pass):
    recipe = _base() if memory is None else _base(memory=memory)
    assert _valid(recipe) is should_pass


def test_inherit_does_not_require_shared_bus():
    """El corazón del cabo LOW: una receta con SÓLO herencia (sin bus) valida."""
    assert _valid(_base(memory={"inherit": "skill_only"}))


def test_empty_memory_section_is_rejected():
    """Una sección memory vacía es señal de error de forma, no un no-op silencioso."""
    assert not _valid(_base(memory={}))
