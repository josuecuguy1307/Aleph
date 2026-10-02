#!/usr/bin/env python3
"""
verify_agent_refs_amendment.py — VERIFICACIÓN de la enmienda aditiva-v1 belt.agent_refs[]
(paso 1: esquema + validador + resolver; NADA de ejecución).

Headless, sin red, sin :8923. Corre:  python3 platform/assembler/verify_agent_refs_amendment.py
Exit 0 = todos los checks verde.

Cubre:
  • REGRESIÓN v1 (lo más importante): recetas v1 reales validan IGUAL que antes.
  • agent_refs[] → valida OK.
  • tool_filters {} + agent_refs → valida OK (padre que sólo delega).
  • tool_filters {} SIN agent_refs → sigue FALLANDO (regla v1 intacta).
  • resolver: agent_ref → ResolvedAgent type='agent'; tool ref → ResolvedBelt type='tool'.
  • CAMINO PROHIBIDO: objeto {ref,type} en belt_refs[] → sigue HARD-FALLANDO.
"""

import copy
import glob
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_REPO / "product" / "backend" / "app" / "phase1"))
sys.path.insert(0, str(_HERE))

from recipe_validator import validate_recipe, RecipeValidationError  # noqa: E402
import belt_resolver as R  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK ' if cond else 'XX '}] {name}" + (f"  — {detail}" if detail else ""))


def _valid_base():
    """Una receta v1 mínima válida (sin agent_refs) — punto de partida de los tweaks."""
    return {
        "schema_version": "v1",
        "meta": {"name": "Test", "nicho": "general"},
        "model": {"primary": "x", "base_url": "y", "temperature": 0,
                  "max_tokens": 256, "max_turns": 8},
        "belt": {"belt_ref": "calc", "tool_filters": {"calc": ["add"]}},
        "rag": {"enabled": False},
    }


def _validates(recipe):
    try:
        validate_recipe(recipe, repo_root=_REPO)
        return True, []
    except RecipeValidationError as e:
        return False, e.errors


print("═" * 78)
print("  VERIFICACIÓN — enmienda aditiva-v1  belt.agent_refs[]")
print("═" * 78)

# ── 1 · REGRESIÓN v1 — recetas reales validan IGUAL (con sus mismos warnings) ────
print("\n1 · REGRESIÓN v1 (recetas reales del repo — deben validar IGUAL):")
BASELINE_WARNINGS = {  # contados ANTES de tocar nada (baseline del paso 1)
    "recipe-cowork.v1.json": 2, "recipe-demo.v1.json": 2, "recipe-route-escalation.v1.json": 2,
    "cowork.config.json": 1, "educacion.config.json": 2, "finanzas.config.json": 0,
    "programacion.config.json": 1, "research.config.json": 2,
}
files = sorted(glob.glob(str(_REPO / "product/recipes/*.config.json"))
               + glob.glob(str(_REPO / "platform/assembler/recipes/*.json")))
reg_ok = True
for f in files:
    d = json.load(open(f))
    if d.get("schema_version") != "v1":
        continue
    name = Path(f).name
    try:
        w = validate_recipe(d, repo_root=_REPO)
        exp = BASELINE_WARNINGS.get(name)
        same = exp is None or len(w) == exp
        reg_ok = reg_ok and same
        print(f"     {name}: OK (warnings {len(w)}{'' if exp is None else f', baseline {exp}'}) {'✓' if same else '✗ CAMBIÓ'}")
    except RecipeValidationError as e:
        reg_ok = False
        print(f"     {name}: FALLA (antes validaba) -> {e.errors[:1]}")
check("regresión v1: recetas reales validan idéntico (warnings sin cambio)", reg_ok)

# ── 2 · agent_refs[] válido → OK ────────────────────────────────────────────────
print("\n2 · checks ADITIVOS:")
r = _valid_base()
r["belt"]["agent_refs"] = ["catalog/agents/research-sub"]
ok, errs = _validates(r)
check("receta con agent_refs[] (+ tools propias) valida OK", ok, str(errs[:1]) if errs else "")

# ── 3 · tool_filters {} + agent_refs → OK (padre que SÓLO delega) ───────────────
r = _valid_base()
r["belt"]["tool_filters"] = {}
r["belt"]["agent_refs"] = ["catalog/agents/research-sub"]
ok, errs = _validates(r)
check("tool_filters {} VACÍO pero con agent_refs → valida OK (sólo delega)", ok, str(errs[:1]) if errs else "")

# ── 4 · tool_filters {} SIN agent_refs → sigue FALLANDO (regla v1 intacta) ──────
r = _valid_base()
r["belt"]["tool_filters"] = {}
ok, errs = _validates(r)
check("tool_filters {} VACÍO y SIN agent_refs → sigue FALLANDO (regla v1 intacta)",
      (not ok) and any("tool_filters" in e for e in errs), str(errs[:1]))

# ── 5 · agent_refs con elemento no-string → FALLA ───────────────────────────────
r = _valid_base()
r["belt"]["agent_refs"] = [{"ref": "x", "type": "agent"}]  # objeto, no string
ok, errs = _validates(r)
check("agent_refs con OBJETO (no string) → FALLA (mismo tipo string que belt_refs)",
      (not ok) and any("agent_refs" in e for e in errs), str(errs[:1]))

# ── 6 · CAMINO PROHIBIDO: objeto {ref,type} en belt_refs[] sigue HARD-FALLANDO ──
print("\n3 · CAMINO PROHIBIDO (debe seguir bloqueado):")
r = _valid_base()
r["belt"].pop("belt_ref", None)
r["belt"]["belt_refs"] = [{"ref": "catalog/belts/x", "type": "agent"}]  # tipar belt_refs[i] = PROHIBIDO
ok, errs = _validates(r)
check("objeto {ref,type} en belt_refs[] → HARD-FALLA (camino prohibido cerrado)",
      (not ok) and any("belt_refs" in e for e in errs), str(errs[:1]))

# ── 7 · RESOLVER: tool ref → type='tool'; agent ref → type='agent' ──────────────
print("\n4 · RESOLVER (distingue tool vs agente, NO ejecuta):")
rb = R.resolve_belt_ref("platform/assembler/fixtures/belt-calc.mcp.json", _REPO)
check("belt_ref → ResolvedBelt type='tool' con mcpServers", rb.type == "tool" and bool(rb.servers),
      f"type={rb.type} servers={rb.servers}")

ra = R.resolve_agent_ref("catalog/agents/research-sub", _REPO)
child_ok = (ra.type == "agent" and isinstance(ra.recipe, dict)
            and ra.recipe.get("schema_version") == "v1"
            and ra.recipe.get("meta", {}).get("name") == "Sub-agente Research")
check("agent_ref → ResolvedAgent type='agent' con la receta hija cargada", child_ok,
      f"type={ra.type} hijo={ra.recipe.get('meta',{}).get('name')!r}")

# resolver: agent_ref que apunta a un .mcp.json (NO una receta) → AgentResolutionError
try:
    R.resolve_agent_ref("platform/assembler/fixtures/belt-calc.mcp.json", _REPO)
    check("agent_ref que apunta a un belt (no receta) → rechaza", False, "no lanzó")
except R.AgentResolutionError:
    check("agent_ref que apunta a un belt (no receta) → AgentResolutionError (check estructural)", True)

# resolve_agent_refs lista vacía → [] (opcional, no error)
check("resolve_agent_refs([]) → [] (agent_refs es opcional)", R.resolve_agent_refs([], _REPO) == [])

# ── resumen ─────────────────────────────────────────────────────────────────────
# [H3] La barra decorativa va ARRIBA: la ÚLTIMA línea de una vara es su veredicto. Ésta
# se le escapó al primer censo porque el detector reconocía `print("═══")` pero no
# `print("═" * 78)` — el regex se arregló y la encontró.
print("\n" + "═" * 78)
if FAIL:
    print("  FALLARON: " + ", ".join(FAIL))
print(f"  RESULTADO: {len(PASS)} OK · {len(FAIL)} FAIL")
sys.exit(0 if not FAIL else 1)
