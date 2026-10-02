#!/usr/bin/env python3
"""
STEP 4 · S16 — el belt curado declara `action_class` para sus tools de cómputo/lectura
(committable verify, sin backend, sin modelo).

QUÉ CIERRA (S16, ground truth §10/§14): el belt keyless/inline NO declaraba action_classes →
el gate A2 fail-cerraba cada tool de cómputo sin verbo-externo (calc.mul, run_python) a
write-world `confirma-siempre` → el gate RETENÍA aritmética ("¿OK, hago la multiplicación?").

LA SOLUCIÓN (cero cambio de gate): el belt declara `_meta.action_classes {server:{tool:read|
write-local}}`; `_merge_belt_cfgs` la une por-belt (compuesto); `assemble_and_run` la PLIEGA a
`recipe.belt.action_classes` antes de `build_enforced_gate`. El enforcer YA emite una regla
auto-ejecuta por tool declarada read/write-local, y los PISOS money/send/mutación-externa del
gate ganan a `declared` SIEMPRE → declarar NUNCA afloja una tool que toca el mundo.

Este harness prueba, contra el enforcer + gate REALES:
  1. `belt-inline-rich.mcp.json` declara `_meta.action_classes` con la forma esperada.
  2. `_merge_belt_cfgs` (assembler real) UNE `action_classes` de varios belts al `_meta` compuesto.
  3. Con la declaración plegada a `recipe.belt.action_classes`, el gate:
     · calc.mul (declarado read)          → EXECUTE (auto)   — aritmética NO gatea (headline S16)
     · pysandbox.run_python (code_exec floor) → HOLD bajo toda autonomía
     · datatools.write_xlsx (write-local)  → NEEDS_OK (el substring 'write' dispara el piso
       mutación-externa ANTES de `declared`: el trade-off aceptado, no debilitamos ese piso)
     · gmail.send_email declarado 'read'   → NEEDS_OK (piso send gana a la declaración)
     · broker.place_order declarado 'read' → NEEDS_OK (piso money gana; auto NUNCA)
  4. `assert_invariant` pasa (las mandatorias money/send siguen plantadas).

Uso:  python3 platform/assembler/verify_s16_action_class.py     (exit 0 = verde)
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]  # platform/assembler/<file> -> repo root
GATES = REPO / "platform" / "gates"
BELT = HERE.parent / "fixtures" / "belt-inline-rich.mcp.json"

RESET, GREEN, RED, DIM, BOLD = "\033[0m", "\033[32m", "\033[31m", "\033[2m", "\033[1m"
_fails = []


def check(name, ok, detail=""):
    if not ok:
        _fails.append(name)
    print(f"  {GREEN+'PASS'+RESET if ok else RED+'FAIL'+RESET}  {name}"
          + (("" if ok or not detail else f"  {DIM}→ {detail}{RESET}")))


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _fold_belt_ac_into_recipe(recipe, belt_meta_ac):
    """Réplica EXACTA del fold de assemble_and_run (recipe gana por-tool; belt llena huecos)."""
    r = copy.deepcopy(recipe)
    folded = {}
    for srv, tmap in (belt_meta_ac or {}).items():
        if isinstance(tmap, dict):
            folded[srv] = dict(tmap)
    for srv, tmap in ((r.get("belt") or {}).get("action_classes") or {}).items():
        if isinstance(tmap, dict):
            folded.setdefault(srv, {}).update(tmap)
    r.setdefault("belt", {})["action_classes"] = folded
    return r


def main():
    print(f"{DIM}S16 verify · belt={BELT.name} · enforcer+gate REALES{RESET}")

    # ── 1) el belt declara _meta.action_classes ────────────────────────────────
    print(f"\n{DIM}── 1 · el belt declara action_classes ──{RESET}")
    belt = json.loads(BELT.read_text(encoding="utf-8"))
    ac = (belt.get("_meta") or {}).get("action_classes") or {}
    check("calc.* declarado read", all(ac.get("calc", {}).get(t) == "read"
          for t in ("add", "sub", "mul", "div", "pow", "mod")), json.dumps(ac.get("calc")))
    check("pysandbox.run_python declarado write-local",
          ac.get("pysandbox", {}).get("run_python") == "write-local")
    check("datatools.write_xlsx declarado write-local",
          ac.get("datatools", {}).get("write_xlsx") == "write-local")

    # ── 2) _merge_belt_cfgs REAL une action_classes por belt ───────────────────
    print(f"\n{DIM}── 2 · _merge_belt_cfgs une action_classes (compuesto) ──{RESET}")
    sys.path.insert(0, str(HERE.parent))
    sys.path.insert(0, str(GATES))
    merged_ok = None
    try:
        asm = _load("puppet_recipe_assembler_s16", HERE.parent / "recipe_assembler.py")

        class _R:  # stub de belt resuelto (sólo necesita .mcp_json_path)
            def __init__(self, p):
                self.mcp_json_path = p
        # segundo belt sintético con OTRO server declarado, para probar la unión
        tmp = HERE.parent / "fixtures" / "_s16_tmp_belt.json"
        tmp.write_text(json.dumps({"mcpServers": {"exa": {"command": "x"}},
                                   "_meta": {"action_classes": {"exa": {"search": "read"}}}}),
                       encoding="utf-8")
        try:
            merged_cfg, _bm = asm._merge_belt_cfgs([_R(BELT), _R(tmp)], REPO)
            m_ac = (merged_cfg.get("_meta") or {}).get("action_classes") or {}
            merged_ok = (m_ac.get("calc", {}).get("mul") == "read"
                         and m_ac.get("exa", {}).get("search") == "read")
        finally:
            tmp.unlink(missing_ok=True)
        check("compuesto conserva action_classes de AMBOS belts (calc + exa)", bool(merged_ok),
              json.dumps(m_ac))
    except Exception as e:  # noqa: BLE001
        check("_merge_belt_cfgs importable/ejecutable", False, f"{type(e).__name__}: {e}")

    # ── 3) gate REAL con la declaración plegada ────────────────────────────────
    print(f"\n{DIM}── 3 · el gate honra read/write-local y los PISOS ganan a declared ──{RESET}")
    enforcer = _load("puppet_recipe_enforcer_s16", GATES / "recipe_enforcer.py")

    base_recipe = {
        "schema_version": "v1",
        "meta": {"name": "s16", "nicho": "general"},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
                 # el usuario intenta declarar read a un send y a un money → los pisos deben ganar
                 "action_classes": {"gmail": {"send_email": "read"},
                                    "broker": {"place_order": "read"}}},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }
    folded = _fold_belt_ac_into_recipe(base_recipe, ac)

    def gate_for(autonomy):
        return enforcer.build_enforced_gate(folded, autonomy=autonomy)

    g_bal = gate_for("balanceado")
    g_man = gate_for("manual")

    def act(gate, server, tool, args=None):
        return gate.evaluate(server, tool, args or {}).action

    EXEC, NEED = "execute", "needs_ok"
    check("calc.mul → EXECUTE bajo balanceado (aritmética NO gatea · headline S16)",
          act(g_bal, "calc", "mul", {"a": 2, "b": 3}) == EXEC, act(g_bal, "calc", "mul"))
    check("calc.mul → EXECUTE bajo manual (read auto bajo TODA perilla)",
          act(g_man, "calc", "mul") == EXEC, act(g_man, "calc", "mul"))
    check("pysandbox.run_python → NEEDS_OK bajo balanceado (piso code_exec)",
          act(g_bal, "pysandbox", "run_python", {"code": "print(1)"}) == NEED)
    check("pysandbox.run_python → NEEDS_OK bajo manual (piso code_exec)",
          act(g_man, "pysandbox", "run_python", {"code": "print(1)"}) == NEED)
    check("pysandbox.run_python declarado read NO degrada el piso code_exec",
          g_bal.classify_action("pysandbox", "run_python", {}, "read") == "code_exec")
    check("datatools.write_xlsx → NEEDS_OK (piso 'write' gana a write-local · trade-off aceptado)",
          act(g_bal, "datatools", "write_xlsx", {"rows": []}) == NEED,
          act(g_bal, "datatools", "write_xlsx"))
    check("gmail.send_email declarado read → NEEDS_OK (piso SEND gana a declared)",
          act(g_bal, "gmail", "send_email", {"to": "x"}) == NEED,
          act(g_bal, "gmail", "send_email"))
    check("broker.place_order declarado read → NEEDS_OK (piso MONEY gana; auto NUNCA)",
          act(g_bal, "broker", "place_order", {"qty": 1}) == NEED,
          act(g_bal, "broker", "place_order"))

    # ── 4) invariante intacta ──────────────────────────────────────────────────
    print(f"\n{DIM}── 4 · la invariante §3.5 sigue plantada ──{RESET}")
    matrix = enforcer.recipe_to_matrix(folded)
    inv_ok = True
    try:
        enforcer.assert_invariant(matrix, autonomy="balanceado")
    except AssertionError as e:
        inv_ok = False
        _inv_detail = str(e)
    check("assert_invariant pasa (money/send mandatorias presentes)", inv_ok,
          "" if inv_ok else _inv_detail)
    # y una regla declarada-calc-mul quedó en la matriz (canal declarativo activo)
    has_calc_rule = any(r.get("id") == "declared-calc-mul" for r in matrix.get("rules", []))
    check("la matriz contiene la regla declared-calc-mul (canal declarativo activo)", has_calc_rule)

    ok = not _fails
    print(f"\n{(GREEN+BOLD+'ALL GREEN ✓' if ok else RED+BOLD+'RED ✗  '+', '.join(_fails))}{RESET}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
