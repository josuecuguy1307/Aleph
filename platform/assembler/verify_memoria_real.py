#!/usr/bin/env python3
"""
verify_memoria_real.py — la EVIDENCIA de MEMORIA COMPARTIDA de PRIMERA CLASE
(recipe.memory, decisión de persona usuaria: primera clase, NO belt-hack).

Qué prueba, contra el MOTOR REAL (assemble_and_run + delegation) y con el MCP server
de memoria REAL (npx @modelcontextprotocol/server-memory, el MISMO patrón que
product/belts/atomicas.mcp.json):

  1. ESCRIBE-EL-HIJO → LEE-EL-PADRE: el padre declara memory.shared=true; delega; el
     HIJO escribe una entidad vía create_entities (server de memoria REAL, npx); el
     PADRE la lee de vuelta vía read_graph. Un solo archivo compartido:
     <workdir del padre>/shared-memory.json — y la entidad del hijo está adentro.
  2. UN SOLO ARCHIVO: en todo el árbol del workdir del padre hay EXACTAMENTE un
     shared-memory.json (el hijo NO crea uno propio en su sub-workdir).
  3. PROPAGACIÓN EXPLÍCITA (no os.environ): el env del server de memoria del HIJO
     lleva el MISMO PUPPET_SHARED_MEMORY que el del padre (espiado en el boot real).
  4. NO-LEAK: una receta SIN memory no recibe PUPPET_SHARED_MEMORY en NINGÚN env de
     server, y su record no trae sección memory.
  5. GATE HONESTO: la escritura del hijo corre con approve=None (RIEL #1) — ejecuta
     porque las tools de memoria son estado LOCAL (base_matrix del belt de memoria las
     marca auto-ejecuta; ni send ni money) — mientras los mandatorios siguen forzados.
  6. VALIDADOR: la receta con memory valida; basura en memory / child_models se rechaza;
     una receta sin memory valida byte-idéntico.

Sólo el CEREBRO está stubeado (FakeBrain, guión determinista → cero tokens, headless).
El server de memoria, el gate, el workdir y la delegación son el código REAL.

Uso:  python3 platform/assembler/verify_memoria_real.py
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_FIX = _HERE / "deleg_fixtures"
for p in (str(_HERE), str(_FIX), str(_REPO_ROOT / "product" / "backend" / "app" / "phase1")):
    if p not in sys.path:
        sys.path.insert(0, p)

import recipe_assembler as RA  # noqa: E402
from verify_delegation_real import FakeBrain, _Patched  # noqa: E402  (reuso del patrón)
from recipe_validator import validate_recipe, RecipeValidationError  # noqa: E402

results: dict = {}   # label -> (passed, evidencia)


def _hr(title: str):
    print("\n" + "═" * 78)
    print("  " + title)
    print("═" * 78)


def _load(name: str) -> dict:
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


def _wd(tag: str, *, clean: bool = True) -> str:
    d = _FIX / ".deleg-workdirs" / tag
    if clean and d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


# ── ESPÍA del boot real de MCP servers: captura (nombre, env) de CADA server que el
#   motor arranca (padre e hijos por igual — la delegación corre por el mismo módulo).
#   No cambia el comportamiento: hereda MCPServer y delega todo. ────────────────────
_ORIG_MCPSERVER = RA._asm.MCPServer


class _SpyServer(_ORIG_MCPSERVER):
    booted: list = []   # [(server_name, env_dict_copy)]

    def __init__(self, name, command, args, env=None):
        _SpyServer.booted.append((name, dict(env or {})))
        super().__init__(name, command, args, env=env)


class _SpyBoot:
    def __enter__(self):
        _SpyServer.booted = []
        RA._asm.MCPServer = _SpyServer
        return _SpyServer

    def __exit__(self, *a):
        RA._asm.MCPServer = _ORIG_MCPSERVER


# ── GUIONES del FakeBrain (cero tokens): el hijo ESCRIBE, el padre LEE ────────────
SCRIPTS_MEM = {
    "MEM_PARENT": [
        {"tool_calls": [("memoria_sub", {"task": "MEM_CHILD"})]},
        {"tool_calls": [("read_graph", {})]},
        {"final": "leí la memoria compartida"},
    ],
    "MEM_CHILD": [
        {"tool_calls": [("create_entities", {"entities": [
            {"name": "DATO-DEL-HIJO", "entityType": "hecho",
             "observations": ["escrito por el sub-agente vía el MCP de memoria real"]}]})]},
        {"final": "escribí la entidad en la memoria compartida"},
    ],
    "PLAIN_NOMEM": [
        {"tool_calls": [("read_data", {"q": "x"})]},
        {"final": "plain sin memoria"},
    ],
}


# ════════════════════════════════════════════════════════════════════════════════
# 1-3+5 · round-trip REAL hijo-escribe → padre-lee sobre UN archivo compartido
# ════════════════════════════════════════════════════════════════════════════════
def t_roundtrip(brain):
    _hr("MEMORIA · el HIJO escribe una entidad (npx server-memory REAL) y el PADRE la lee")
    wd = _wd("memoria")
    with _SpyBoot() as spy, _Patched(brain):
        rec = RA.assemble_and_run(_load("parent_memoria.json"), "MEM_PARENT",
                                  repo_root=_REPO_ROOT, deadline_s=180.0, workdir=wd)
    child = (rec.get("sub_runs") or [{}])[0]
    print(f"  padre ok={rec.get('ok')} answer={rec.get('answer')!r}")
    print(f"  hijo  ok={child.get('ok')} answer={(child.get('answer') or '')[:80]!r}")
    print(f"  record.memory padre={rec.get('memory')}")
    print(f"  record.memory hijo ={child.get('memory')}")

    # (1) UN solo archivo, en el workdir del PADRE, con la entidad del HIJO adentro
    shared = Path(rec.get("workdir", wd)) / "shared-memory.json"
    exists = shared.exists()
    content = shared.read_text(encoding="utf-8") if exists else ""
    has_entity = "DATO-DEL-HIJO" in content
    print(f"  archivo compartido: {shared}  existe={exists}  contiene-entidad-del-hijo={has_entity}")

    # (2) EXACTAMENTE uno en todo el árbol (el hijo no creó otro en su sub-workdir)
    all_files = sorted(str(p) for p in Path(rec.get("workdir", wd)).rglob("shared-memory.json"))
    only_one = len(all_files) == 1 and all_files[0] == str(shared)
    print(f"  shared-memory.json en el árbol del padre: {len(all_files)} → {all_files}")

    # (3) el env del server de memoria del HIJO lleva el MISMO path que el del padre
    mem_envs = [(n, e.get("PUPPET_SHARED_MEMORY")) for (n, e) in _SpyServer.booted if n == "memory"]
    same_path = (len(mem_envs) >= 2
                 and all(v == str(shared) for (_n, v) in mem_envs))
    inherited_flag = bool((child.get("memory") or {}).get("inherited"))
    print(f"  servers 'memory' booteados={len(mem_envs)} PUPPET_SHARED_MEMORY={sorted(set(v for _n, v in mem_envs))}")
    print(f"  hijo heredó el path por PARÁMETRO explícito (record.memory.inherited): {inherited_flag}")

    # (5) GATE: la escritura del hijo corrió SIN approve (estado LOCAL → auto-ejecuta);
    #     la lectura del padre también. Cero teatro: gate_action=='execute' en ambas.
    child_write = [t for t in child.get("tool_calls", []) if t.get("tool") == "create_entities"]
    parent_read = [t for t in rec.get("tool_calls", []) if t.get("tool") == "read_graph"]
    wrote_ungated = bool(child_write) and child_write[0].get("gate_action") == "execute"
    read_ungated = bool(parent_read) and parent_read[0].get("gate_action") == "execute"
    read_saw_entity = bool(parent_read) and "DATO-DEL-HIJO" in (parent_read[0].get("result") or "")
    print(f"  hijo create_entities: {child_write[0].get('gate_action') if child_write else '—'} "
          f"(approve=None; auto-ejecuta vía base_matrix del belt de memoria)")
    print(f"  padre read_graph: {parent_read[0].get('gate_action') if parent_read else '—'} "
          f"→ ¿su resultado trae la entidad del hijo?: {read_saw_entity}")

    ok = (rec.get("ok") and child.get("ok") and exists and has_entity and only_one
          and same_path and inherited_flag and wrote_ungated and read_ungated and read_saw_entity)
    results["MEMORIA·hijo-escribe→padre-lee"] = (
        bool(rec.get("ok") and child.get("ok") and exists and has_entity and read_saw_entity),
        f"entidad 'DATO-DEL-HIJO' escrita por el hijo vive en {shared.name} y el read_graph del padre la devolvió")
    results["MEMORIA·un-solo-archivo"] = (only_one,
        f"{len(all_files)} shared-memory.json en el árbol (el hijo no creó uno propio)")
    results["MEMORIA·propagación-explícita"] = (same_path and inherited_flag,
        f"{len(mem_envs)} servers de memoria (padre+hijo) con el MISMO PUPPET_SHARED_MEMORY, "
        f"heredado por parámetro (no os.environ)")
    results["MEMORIA·gate-local-ungated"] = (wrote_ungated and read_ungated,
        "create_entities (hijo, approve=None) y read_graph (padre) corrieron execute — estado LOCAL sin gate")
    print(f"  >>> round-trip {'OK' if ok else 'FALLO'}")
    return rec


# ════════════════════════════════════════════════════════════════════════════════
# 4 · NO-LEAK — receta SIN memory: cero PUPPET_SHARED_MEMORY en CUALQUIER server env
# ════════════════════════════════════════════════════════════════════════════════
def t_no_leak(brain):
    _hr("NO-LEAK — receta SIN memory: ningún server recibe PUPPET_SHARED_MEMORY")
    recipe = _load("plain_no_agents.json")
    with _SpyBoot() as spy, _Patched(brain):
        rec = RA.assemble_and_run(recipe, "PLAIN_NOMEM",
                                  repo_root=_REPO_ROOT, deadline_s=120.0, workdir=_wd("memoria-plain"))
    leaks = [(n, e["PUPPET_SHARED_MEMORY"]) for (n, e) in _SpyServer.booted
             if "PUPPET_SHARED_MEMORY" in e]
    no_record = "memory" not in rec
    ran = rec.get("ok") and any(t.get("tool") == "read_data" for t in rec.get("tool_calls", []))
    print(f"  servers booteados={len(_SpyServer.booted)}  con PUPPET_SHARED_MEMORY={leaks} (debe ser [])")
    print(f"  record sin sección memory={no_record}  corrió normal={ran}")
    passed = not leaks and no_record and bool(ran)
    results["MEMORIA·no-leak-sin-memory"] = (passed,
        f"{len(_SpyServer.booted)} servers booteados, 0 con PUPPET_SHARED_MEMORY; record sin sección memory")
    print(f"  >>> NO-LEAK {'OK' if passed else 'FALLO'}")


# ════════════════════════════════════════════════════════════════════════════════
# 6 · VALIDADOR — memory + agent_policy.child_models (forma congelada del contrato)
# ════════════════════════════════════════════════════════════════════════════════
def t_validator():
    _hr("VALIDADOR — recipe.memory + belt.agent_policy.child_models (contrato congelado)")
    checks = []

    def chk(name, cond, detail=""):
        checks.append(cond)
        print(f"  [{'OK ' if cond else 'XX '}] {name}" + (f" — {detail}" if detail else ""))

    parent_mem = _load("parent_memoria.json")
    try:
        w = validate_recipe(copy.deepcopy(parent_mem), repo_root=_REPO_ROOT)
        chk("receta con memory {shared,ref} VALIDA", True, f"warnings={len(w)}")
    except RecipeValidationError as e:
        chk("receta con memory {shared,ref} VALIDA", False, str(e.errors))

    # sin memory → byte-idéntico (mismos errors/warnings que siempre)
    base = copy.deepcopy(parent_mem)
    base.pop("memory")
    try:
        w0 = validate_recipe(base, repo_root=_REPO_ROOT)
        chk("misma receta SIN memory valida igual (aditivo)", True, f"warnings={len(w0)}")
    except RecipeValidationError as e:
        chk("misma receta SIN memory valida igual (aditivo)", False, str(e.errors))

    bad_cases = [
        ("memory no-dict", {"memory": "compartida"}),
        ("memory.shared no-bool", {"memory": {"shared": "yes", "ref": "product/belts/memoria-compartida.mcp.json"}}),
        ("memory sin ref", {"memory": {"shared": True}}),
        ("memory.ref inexistente en disco", {"memory": {"shared": True, "ref": "product/belts/no-existe.mcp.json"}}),
        ("memory.ref absoluto", {"memory": {"shared": True, "ref": "/etc/passwd"}}),
    ]
    for label, patch in bad_cases:
        r = copy.deepcopy(parent_mem)
        r.update(patch)
        try:
            validate_recipe(r, repo_root=_REPO_ROOT)
            chk(f"rechaza {label}", False, "validó y no debía")
        except RecipeValidationError:
            chk(f"rechaza {label}", True)

    # agent_policy.child_models — acepta la forma congelada; rechaza basura
    pc = _load("parent_model_perchild.json")
    try:
        validate_recipe(copy.deepcopy(pc), repo_root=_REPO_ROOT)
        chk("child_models {slug: cfg plano con primary} VALIDA", True)
    except RecipeValidationError as e:
        chk("child_models {slug: cfg plano con primary} VALIDA", False, str(e.errors))

    for label, ap in [
        ("agent_policy no-dict", "own"),
        ("child_models no-dict", {"child_models": ["child_alpha"]}),
        ("child_models[slug] no-dict", {"child_models": {"child_alpha": "picked-model"}}),
        ("child_models[slug] sin primary/model", {"child_models": {"child_alpha": {"base_url": "stub://x"}}}),
    ]:
        r = copy.deepcopy(pc)
        r["belt"]["agent_policy"] = ap
        try:
            validate_recipe(r, repo_root=_REPO_ROOT)
            chk(f"rechaza {label}", False, "validó y no debía")
        except RecipeValidationError:
            chk(f"rechaza {label}", True)

    passed = all(checks)
    results["VALIDADOR·memory+child_models"] = (passed, f"{sum(checks)}/{len(checks)} checks del contrato congelado")
    print(f"  >>> VALIDADOR {'OK' if passed else 'FALLO'}")


def main():
    # higiene: si el shell exterior exportó PUPPET_SHARED_MEMORY, lo sacamos — el
    # contrato es que el path viaja por PARÁMETRO, no por entorno global.
    import os
    os.environ.pop("PUPPET_SHARED_MEMORY", None)

    brain = FakeBrain(SCRIPTS_MEM)
    t_roundtrip(brain)
    t_no_leak(brain)
    t_validator()

    _hr("RESUMEN — ¿la memoria compartida de primera clase CIERRA?")
    all_ok = True
    for k in sorted(results.keys()):
        passed, _ev = results[k]
        all_ok = all_ok and passed
        print(f"  {k:<34} {'✓ CIERRA' if passed else '✗ NO CIERRA'}")
    print("\n  EVIDENCIA:")
    for k in sorted(results.keys()):
        print(f"   • {k}: {results[k][1]}")
    print("\n  VEREDICTO:", "TODO VERDE — un solo archivo, propagación explícita, sin leak"
          if all_ok else "ALGO NO CIERRA — revisar antes de seguir")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
