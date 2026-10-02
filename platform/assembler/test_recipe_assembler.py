#!/usr/bin/env python3
"""
test_recipe_assembler.py — Real (no-mock) unit checks for the pieces of the
nested-v1 assembler that don't need a live model:

  (a) curated subset: a recipe asking for a phantom tool cables only the real
      ones and REPORTS the dropped tool (evidence, microtask g).
  (e) lazy schema loading: reveal_next() exposes schemas in batches; a big belt
      never dumps every schema into the first prompt.
  (f) context management: _bound_tool_result caps a giant result; _prune_history
      stubs old tool results past the window.
  (c) belt_resolver: direct path + dir-scan + clean failure.

These boot the REAL calc MCP server over stdio (credential-free) — nothing is
mocked. Run: python test_recipe_assembler.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import recipe_assembler as ra  # noqa: E402
from belt_resolver import resolve_belt_ref, BeltResolutionError  # noqa: E402

REPO_ROOT = _THIS.parents[1]
CALC_BELT = _THIS / "fixtures" / "belt-calc.mcp.json"

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _boot_calc():
    import json
    mcp = json.loads(CALC_BELT.read_text())
    scfg = mcp["mcpServers"]["calc"]
    # Los args se EXPANDEN igual que en el runtime (${PUPPET_BELTS}/${PUPPET_WORKDIR}).
    # Antes se pasaban crudos y funcionaba de casualidad: el belt traía la ruta absoluta
    # de la laptop de quien escribió el test, así que no había nada que expandir. O sea el
    # test verde dependía justamente del bug de portabilidad que ese belt tenía — en
    # cualquier otra máquina, y en el contenedor, este boot nunca hubiera arrancado.
    env = ra._puppet_run_env(REPO_ROOT, dict(os.environ))
    args = [ra._expand_str(a, env) for a in scfg.get("args", [])]
    srv = ra._asm.MCPServer("calc", ra._expand_str(scfg["command"], env), args)
    assert srv.start(), "calc MCP server failed to start"
    return srv


# ── (a) curated subset + drop-on-phantom (microtask a + g) ──────────────────────
def test_curated_subset_and_drop():
    srv = _boot_calc()
    try:
        # recipe asks for add, mul (real) + nope (phantom)
        reg = ra.LazyToolRegistry([srv], {"calc": ["add", "mul", "nope"]})
        check("a.1 cables only requested real tools",
              sorted(reg.cabled) == ["add", "mul"], f"cabled={reg.cabled}")
        check("a.2 the 6-tool surface was probed",
              len(reg.server_surfaces.get("calc", [])) == 6,
              f"surface={reg.server_surfaces.get('calc')}")
        check("a.3 phantom tool reported in dropped (not silent)",
              any(d["tool"] == "nope" for d in reg.dropped), f"dropped={reg.dropped}")
        # the four uncabled real tools are simply not exposed
        names = set(reg.tool_names())
        check("a.4 uncabled tools absent from schema",
              {"sub", "div", "pow", "mod"}.isdisjoint(names), f"names={names}")
    finally:
        srv.stop()


# ── (e) lazy schema loading in batches (microtask e) ────────────────────────────
def test_lazy_loading():
    srv = _boot_calc()
    try:
        # cable all 6, batch_size 2 -> reveal in 3 batches
        reg = ra.LazyToolRegistry([srv], {"calc": None}, batch_size=2)
        check("e.1 all 6 cabled when filter is None (allow-all)",
              len(reg.cabled) == 6, f"cabled={len(reg.cabled)}")
        check("e.2 nothing revealed before first reveal_next",
              len(reg.revealed_schema()) == 0)
        reg.reveal_next()
        check("e.3 first batch exposes 2 schemas",
              len(reg.revealed_schema()) == 2, f"revealed={len(reg.revealed_schema())}")
        reg.reveal_next(); reg.reveal_next()
        check("e.4 after 3 batches all 6 exposed",
              len(reg.revealed_schema()) == 6, f"revealed={len(reg.revealed_schema())}")
        check("e.5 reveal_next returns False when exhausted",
              reg.reveal_next() is False)
    finally:
        srv.stop()


# ── (f) context management (microtask f) ────────────────────────────────────────
def test_context_management():
    big = "x" * 10000
    bounded = ra._bound_tool_result(big, limit=4000)
    check("f.1 giant tool result is capped", len(bounded) < 4300 and "truncado" in bounded,
          f"len={len(bounded)}")

    # 12 tool results, keep 8 -> oldest 4 get stubbed
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    for i in range(12):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "tool", "tool_call_id": f"t{i}", "content": f"FULL-RESULT-{i}"})
    pruned = ra._prune_history(msgs, keep_tool_results=8)
    tool_msgs = [m for m in pruned if m.get("role") == "tool"]
    stubbed = [m for m in tool_msgs if "podado" in m["content"]]
    intact = [m for m in tool_msgs if m["content"].startswith("FULL-RESULT-")]
    check("f.2 oldest tool results stubbed past window",
          len(stubbed) == 4, f"stubbed={len(stubbed)}")
    check("f.3 most recent 8 tool results kept intact",
          len(intact) == 8, f"intact={len(intact)}")
    check("f.4 system + user turns untouched",
          pruned[0]["content"] == "s" and pruned[1]["content"] == "u")


# ── (c) belt_resolver branches (microtask c) ────────────────────────────────────
def test_resolver():
    r1 = resolve_belt_ref("platform/assembler/fixtures/belt-calc.mcp.json", REPO_ROOT)
    check("c.1 direct .mcp.json resolves", r1.servers == ["calc"], f"servers={r1.servers}")

    r2 = resolve_belt_ref("demo-test", REPO_ROOT)
    check("c.2 slug -> dir-scan resolves (demo-test)", r2.servers == ["echo"],
          f"-> {r2.mcp_json_path.name}")

    r3 = resolve_belt_ref("catalog/belts/finanzas.md", REPO_ROOT)
    check("c.3 spec-md -> template resolves (finanzas)", "excel" in r3.servers,
          f"servers={r3.servers}")

    try:
        resolve_belt_ref("nicho-inexistente", REPO_ROOT)
        check("c.4 unresolvable raises clearly", False)
    except BeltResolutionError as exc:
        check("c.4 unresolvable raises clearly", len(exc.tried) >= 2,
              f"tried={len(exc.tried)} candidates")


# ── FRAMING composition (bloque C: Capa C universal + domain por-nicho) ─────────
# Determinístico (sin modelo): valida la COMPOSICIÓN, no la conducta del LLM (eso se
# prueba en runs reales). Lo que asegura: Capa C SIEMPRE; domain SOLO si el nicho lo
# tiene; inline del autor se appendea al final; el orden es Capa C → domain → inline.
def test_framing_composition():
    _CAPA_MARK = "Escucha el pedido LITERAL primero"          # firma de Capa C
    _RESEARCH_MARK = "rigor de investigador"                  # firma del domain research

    # general → SOLO Capa C (sin domain, sin inline)
    f_gen = ra._build_framing({"meta": {"nicho": "general"}}, REPO_ROOT)
    check("fr.1 Capa C presente en nicho general", _CAPA_MARK in f_gen, f_gen[:60])
    check("fr.2 domain research AUSENTE en general", _RESEARCH_MARK not in f_gen)

    # research → Capa C + domain research, en ese orden
    f_res = ra._build_framing({"meta": {"nicho": "research"}}, REPO_ROOT)
    check("fr.3 Capa C presente en research", _CAPA_MARK in f_res)
    check("fr.4 domain research presente en research", _RESEARCH_MARK in f_res)
    check("fr.5 orden Capa C → domain", f_res.index(_CAPA_MARK) < f_res.index(_RESEARCH_MARK))

    # inline del autor → se appendea AL FINAL (después de Capa C y del domain)
    CANARY = "CANARIO-INLINE-7788"
    f_inl = ra._build_framing(
        {"meta": {"nicho": "research"}, "framing": {"inline": CANARY}}, REPO_ROOT)
    check("fr.6 inline del autor presente", CANARY in f_inl)
    check("fr.7 inline va DESPUÉS del domain",
          f_inl.index(_RESEARCH_MARK) < f_inl.index(CANARY))

    # sin meta / sin framing → Capa C igual (nunca devuelve vacío; no rompe)
    f_bare = ra._build_framing({}, REPO_ROOT)
    check("fr.8 Capa C presente sin meta", _CAPA_MARK in f_bare)

    # nicho desconocido → Capa C sin domain (no explota, no inventa domain)
    f_unk = ra._build_framing({"meta": {"nicho": "marciano"}}, REPO_ROOT)
    check("fr.9 nicho desconocido → solo Capa C", _CAPA_MARK in f_unk and _RESEARCH_MARK not in f_unk)


def main():
    print("=== recipe_assembler test suite (no mocks; real stdio MCP) ===\n")
    test_resolver()
    test_curated_subset_and_drop()
    test_lazy_loading()
    test_context_management()
    test_framing_composition()
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
