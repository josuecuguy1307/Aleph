"""Regresión de seguridad: una receta no puede auto-ejecutar código de host."""

from recipe_enforcer import build_enforced_gate, recipe_to_matrix


def _recipe(declared="read", autonomy="balanceado"):
    return {
        "schema_version": "v1",
        "meta": {"name": "code-exec-floor"},
        "autonomy": autonomy,
        "belt": {"action_classes": {"pysandbox": {"run_python": declared}}},
    }


def test_code_exec_floor_beats_recipe_and_autonomy():
    for autonomy in ("manual", "balanceado", "autonomo"):
        for declared in ("read", "write-local", "write-world"):
            decision = build_enforced_gate(_recipe(declared, autonomy)).evaluate(
                "pysandbox", "run_python", {"code": "print(6 * 7)"}
            )
            assert decision.action == "needs_ok"
            assert decision.action_class == "code_exec"
            assert "print(6 * 7)" in decision.payload["vista_previa"]


def test_mandatory_code_exec_rule_precedes_recipe_rules():
    matrix = recipe_to_matrix(_recipe())
    ids = [rule.get("id") for rule in matrix["rules"]]
    assert ids[0] == "MANDATORY-code-exec"
    assert "declared-pysandbox-run_python" not in ids


def test_known_exec_aliases_share_the_floor():
    gate = build_enforced_gate(_recipe())
    for tool in ("run_shell", "execute_code", "aleph_run_code", "shell_exec",
                 "execute_cell", "stata_run"):
        assert gate.classify_action("any", tool, {}, "read") == "code_exec"
        assert gate.evaluate("any", tool, {"code": "pass"}).action == "needs_ok"


def test_code_exec_preview_is_honest_about_missing_os_jail():
    decision = build_enforced_gate(_recipe()).evaluate(
        "pysandbox", "run_python", {"code": "print(1)"})
    preview = decision.payload["vista_previa"]
    assert "no hay aislamiento de sistema operativo" in preview
    assert "cuaderno aislado" not in preview
