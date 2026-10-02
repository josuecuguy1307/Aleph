#!/usr/bin/env python3
"""
Tests de la INVARIANTE §3.5 (orden del founder 2026-06-15): la receta DECLARA
gates, pero SECURITY los HACE CUMPLIR. El motor FUERZA money_touch/send aunque la
receta los omita o los ponga "off"; la receta puede AGREGAR, nunca QUITAR; default
FAIL-CLOSED para tools desconocidas que escriben/mandan.

Cada test trae su PAR M002 (rechazo + control positivo): no es gate-all/block-all —
lo legítimo y la lectura obvia SIGUEN pasando.

Corré:  python3 platform/gates/tests_recipe_enforcer.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_GATES = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _GATES / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


approval_gate = _load("approval_gate")
enforcer = _load("recipe_enforcer")

ApprovalGate = approval_gate.ApprovalGate
GateDecision = approval_gate.GateDecision
recipe_to_matrix = enforcer.recipe_to_matrix
assert_invariant = enforcer.assert_invariant

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    tag = PASS if cond else FAIL
    results.append((tag, name, detail))
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))
    return cond


# Receta v1 anidada (forma del RECIPE-SCHEMA) que INTENTA APAGAR ambos gates.
RECIPE_GATES_OFF = {
    "schema_version": "v1",
    "meta": {"name": "Agente Finanzas (gates apagados a propósito)", "nicho": "finanzas"},
    "model": {"primary": "gpt-oss-120b", "base_url": "http://127.0.0.1:4000/v1",
              "temperature": 0, "max_tokens": 2048, "max_turns": 8},
    "belt": {
        "belt_ref": "catalog/belts/finanzas.md",
        "tool_filters": {
            "sheets": ["get_sheet_data", "batch_update_cells"],   # lectura + money-touch
            "gmail":  ["search_messages", "send_message"],         # lectura + send
            "secedgar": ["get_financials"],                        # lectura pura
        },
    },
    "gates": {"money_touch": "off", "send": "off"},   # ← LA RECETA LOS APAGA
}

# Receta que OMITE por completo la sección gates (la omisión NO desactiva nada).
RECIPE_GATES_OMITTED = {
    "schema_version": "v1",
    "meta": {"name": "Agente Cowork (sin sección gates)", "nicho": "cowork"},
    "model": {"primary": "gpt-oss-120b", "base_url": "http://127.0.0.1:4000/v1",
              "temperature": 0, "max_tokens": 2048, "max_turns": 8},
    "belt": {"belt_ref": "catalog/belts/cowork.md",
             "tool_filters": {"gmail": ["send_message", "search_messages"]}},
    # sin clave "gates"
}


def test_money_touch_off_still_gates():
    print("\n=== INVARIANTE (1a) — money_touch:'off' en la receta IGUAL gatea [par M002] ===")
    matrix = recipe_to_matrix(RECIPE_GATES_OFF)
    gate = ApprovalGate(matrix)

    # RECHAZO: una tool money-touch (escribir hoja financiera viva) -> NEEDS_OK
    d = gate.evaluate("sheets", "batch_update_cells",
                      {"spreadsheet_id": "S1", "data": [["x", "y"]]})
    check("(1a) batch_update_cells con gate en 'off' => NEEDS_OK (gatea igual)",
          d.action == GateDecision.NEEDS_OK and d.level == "confirma-siempre",
          f"action={d.action} level={d.level}")
    check("(1a) el payload trae el contrato de UX (qué/dónde/preview/ok)",
          d.action == GateDecision.NEEDS_OK
          and all(k in d.payload for k in ("que_va_a_hacer", "donde_afecta", "vista_previa", "requiere_ok")),
          str(list(d.payload.keys()))[:90])

    # RECHAZO: una orden de pago (otra money-touch por clasificación) -> NEEDS_OK
    d2 = gate.evaluate("broker", "place_order", {"ticker": "AAPL", "qty": 10})
    check("(1a) place_order (money-touch por clasificación) => NEEDS_OK",
          d2.action == GateDecision.NEEDS_OK and d2.level == "confirma-siempre",
          f"action={d2.action} level={d2.level}")

    # CONTROL POSITIVO M002: una LECTURA pura del mismo belt -> EXECUTE (no es gate-all)
    d3 = gate.evaluate("secedgar", "get_financials", {"cik": "320193"})
    check("(1a-control+) get_financials (lectura) => EXECUTE (no es gate-all)",
          d3.action == GateDecision.EXECUTE, f"action={d3.action}")
    d4 = gate.evaluate("sheets", "get_sheet_data", {"spreadsheet_id": "S1"})
    check("(1a-control+) get_sheet_data (lectura) => EXECUTE",
          d4.action == GateDecision.EXECUTE, f"action={d4.action}")


def test_send_off_still_gates():
    print("\n=== INVARIANTE (1b) — send:'off' en la receta IGUAL gatea [par M002] ===")
    matrix = recipe_to_matrix(RECIPE_GATES_OFF)
    gate = ApprovalGate(matrix)

    # RECHAZO: send_message con send apagado en la receta -> NEEDS_OK
    d = gate.evaluate("gmail", "send_message",
                      {"to": "cfo@empresa.com", "body": "Te paso el cierre."})
    check("(1b) gmail.send_message con gate en 'off' => NEEDS_OK (gatea igual)",
          d.action == GateDecision.NEEDS_OK and d.level == "confirma-siempre",
          f"action={d.action} level={d.level}")
    check("(1b) preview de mensaje muestra destinatario+cuerpo (lenguaje plano)",
          "cfo@empresa.com" in d.payload.get("vista_previa", ""),
          d.payload.get("vista_previa", "")[:80])

    # CONTROL POSITIVO M002: leer correos NO gatea
    d2 = gate.evaluate("gmail", "search_messages", {"q": "cierre Q2"})
    check("(1b-control+) gmail.search_messages (lectura) => EXECUTE (no es gate-all)",
          d2.action == GateDecision.EXECUTE, f"action={d2.action}")


def test_gates_omitted_still_gates():
    print("\n=== INVARIANTE (1c) — receta SIN sección gates: la omisión NO desactiva ===")
    matrix = recipe_to_matrix(RECIPE_GATES_OMITTED)
    gate = ApprovalGate(matrix)
    d = gate.evaluate("gmail", "send_message", {"to": "x@y.com", "body": "hola"})
    check("(1c) send_message con receta sin 'gates' => NEEDS_OK",
          d.action == GateDecision.NEEDS_OK and d.level == "confirma-siempre",
          f"action={d.action} level={d.level}")


def test_unknown_writer_fails_closed():
    print("\n=== INVARIANTE (2) — tool DESCONOCIDA-que-escribe gatea por default [par M002] ===")
    # receta finanzas con su belt; la tool que probamos NO está en ninguna regla
    matrix = recipe_to_matrix(RECIPE_GATES_OFF)
    gate = ApprovalGate(matrix)

    # RECHAZO: desconocidas con forma de escritura/envío/exfil -> NEEDS_OK (fail-closed)
    for srv, tool in [("x", "wipe_database"), ("y", "exfiltrate_to"),
                      ("z", "frobnicate_and_upload"), ("w", "mark_done")]:
        d = gate.evaluate(srv, tool, {"foo": "bar"})
        check(f"(2) desconocida-que-escribe '{tool}' => NEEDS_OK (fail-closed)",
              d.action == GateDecision.NEEDS_OK, f"action={d.action} level={d.level}")

    # RECHAZO: una desconocida AMBIGUA (no es lectura obvia) también cae fail-closed
    d_amb = gate.evaluate("q", "frobnicate", {"foo": "bar"})
    check("(2) desconocida AMBIGUA 'frobnicate' (ni lectura obvia ni regla) => NEEDS_OK",
          d_amb.action == GateDecision.NEEDS_OK, f"action={d_amb.action}")

    # CONTROL POSITIVO M002: desconocida de LECTURA OBVIA -> EXECUTE (no es block-all)
    for srv, tool in [("x", "get_quote"), ("y", "list_files"), ("z", "search_news")]:
        d = gate.evaluate(srv, tool, {})
        check(f"(2-control+) desconocida-lectura '{tool}' => EXECUTE (no es block-all)",
              d.action == GateDecision.EXECUTE, f"action={d.action}")


def test_recipe_can_add_never_remove():
    print("\n=== INVARIANTE (3) — la receta puede AGREGAR gates, nunca QUITAR ===")
    # receta que intenta colar una regla EXTRA laxa sobre una tool que manda
    recipe = dict(RECIPE_GATES_OFF)
    recipe["gates"] = {
        "money_touch": "off",
        "send": "off",
        "extra_rules": [
            # intento malicioso: declarar send_message como auto-ejecuta
            {"id": "evil-bypass",
             "match": {"server": "gmail", "tool_name_contains": ["send_message"]},
             "level": "auto-ejecuta"},
            # adición legítima: gatear una tool propia de exportación
            {"id": "extra-export",
             "match": {"server": "reporting", "tool_name_contains": ["export_pdf"]},
             "level": "confirma-una-vez"},
        ],
    }
    matrix = recipe_to_matrix(recipe)
    gate = ApprovalGate(matrix)

    # el intento de bajar send_message a auto-ejecuta NO prospera: la MANDATORY-send
    # va primero y gana el match -> sigue siendo confirma-siempre.
    d = gate.evaluate("gmail", "send_message", {"to": "a@b.com", "body": "x"})
    check("(3) extra-rule que intenta auto-ejecutar un send => sigue NEEDS_OK (no se puede quitar)",
          d.action == GateDecision.NEEDS_OK and d.level == "confirma-siempre",
          f"action={d.action} level={d.level}")

    # la adición legítima (más estricta) SÍ aplica
    d2 = gate.evaluate("reporting", "export_pdf", {"path": "/tmp/r.pdf"})
    check("(3-control+) extra-rule legítima (export_pdf) SÍ se agrega => NEEDS_OK",
          d2.action == GateDecision.NEEDS_OK, f"action={d2.action} level={d2.level}")


def test_assert_invariant_guard():
    print("\n=== INVARIANTE (4) — assert_invariant: guard de arranque fail-closed ===")
    ok_matrix = recipe_to_matrix(RECIPE_GATES_OFF)
    try:
        assert_invariant(ok_matrix)
        check("(4) matriz derivada PASA el guard de invariante", True)
    except AssertionError as e:
        check("(4) matriz derivada PASA el guard de invariante", False, str(e))

    # matriz MANIPULADA: le quitamos las reglas mandatorias -> el guard DEBE fallar
    tampered = recipe_to_matrix(RECIPE_GATES_OFF)
    tampered["rules"] = [r for r in tampered["rules"] if not r.get("mandatory")]
    try:
        assert_invariant(tampered)
        check("(4) matriz SIN mandatorias => el guard la RECHAZA", False, "no lanzó AssertionError")
    except AssertionError:
        check("(4) matriz SIN mandatorias => el guard la RECHAZA (fail-closed)", True)


def main():
    test_money_touch_off_still_gates()
    test_send_off_still_gates()
    test_gates_omitted_still_gates()
    test_unknown_writer_fails_closed()
    test_recipe_can_add_never_remove()
    test_assert_invariant_guard()

    n_fail = sum(1 for t, _, _ in results if t == FAIL)
    n_pass = sum(1 for t, _, _ in results if t == PASS)
    print("\n" + "=" * 70)
    print(f"RESULTADO: {n_pass} PASS · {n_fail} FAIL  (total {len(results)})")
    print("=" * 70)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
