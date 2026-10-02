#!/usr/bin/env python3
"""
selftest_forja_agentes.py — GATE VERDE del PASO 4 (la FORJA equipa un AGENTE).

Headless, sin red, sin keys, sin :8923. El camino del AGENTE corre EN PARALELO al de
tools y no lo rompe. Seis candados, todos contra disco/runtime real (cero mocks):

  1. REGRESIÓN tool (lo más importante): MCPEmitter.emit sigue dando ForgedMCP{tools};
     el belt-<slug>.mcp.json sigue con mcpServers{} y SIN agentServers{}; el evento
     'forged' sigue llevando tools:[] (+ agents:[] aditivo).
  2. AGENTE equipado: verify_agent_ref → VerifiedAgent; AgentEmitter.emit_agent →
     ForgedAgent{recipe_ref}; el belt-<slug>.agent.json trae agentServers{} (descriptor
     paralelo a mcpServers{}) y NO mcpServers{}.
  3. DUAL-MODE: el evento 'forged' lleva tools:[] Y agents:[] a la vez; un lector que
     SÓLO mira `tools` sigue funcionando en los 3 casos (tool-only / agent-only / ambos).
  4. REGLA LOAD-BEARING: un agente equipado NUNCA cae en belt_refs[]/mcpServers; el merge
     de la receta lo pone en agent_refs[] (y el merge de tool jamás toca agent_refs[]).
  5. VALIDA (paso 1): la receta con el agente equipado pasa validate_recipe del paso 1.
  6. RESOLVER (paso 1): el recipe_ref forjado resuelve a ResolvedAgent type='agent' con la
     receta hija v1 cargada → el motor del paso 2 ramifica a DELEGAR en ese agent_ref.

Uso:
    PYTHONPATH=platform python platform/inspection/loop/selftest_forja_agentes.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_REPO_ROOT / "platform"),
           str(_REPO_ROOT / "product" / "backend"),
           str(_REPO_ROOT / "product" / "backend" / "app" / "phase1"),
           str(_REPO_ROOT / "platform" / "assembler")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from inspection import contracts as C  # noqa: E402
from inspection.loop.emit import MCPEmitter, AgentEmitter, verify_agent_ref  # noqa: E402
from inspection.loop.engine import _build_forged_event  # noqa: E402
from inspection import registry  # noqa: E402
from recipe_validator import validate_recipe, RecipeValidationError  # noqa: E402
import belt_resolver as R  # noqa: E402

_FAILS: list[str] = []
_AGENT_REF_FIXTURE = "catalog/agents/research-sub.config.json"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


def _valid_parent() -> dict:
    """Receta v1 mínima válida (espeja _valid_base del paso 1) — el padre que equipará."""
    return {
        "schema_version": "v1",
        "meta": {"name": "Padre", "nicho": "general"},
        "model": {"primary": "x", "base_url": "y", "temperature": 0,
                  "max_tokens": 256, "max_turns": 8},
        "belt": {"belt_ref": "calc", "tool_filters": {"calc": ["add"]}},
        "rag": {"enabled": False},
    }


def _verified_tool() -> C.VerifiedTool:
    cand = C.CandidateTool(name="get_thing", kind=C.ToolKind.READ,
                           endpoint="/things", method="GET",
                           input_schema={"type": "object", "x-sample-call": {"query": {}}})
    return C.VerifiedTool(candidate=cand, verified_by="200-OK+schema-match", sample_response="{}")


# ── 1 · REGRESIÓN tool — el camino de tools queda EXACTAMENTE como hoy ───────────
def gate_regression_tool() -> dict:
    print("\n[1] REGRESIÓN tool — equipar una tool funciona como hoy")
    root = Path(tempfile.mkdtemp(prefix="forja-tool-"))
    principal = C.Principal(anon_id="sess-TOOL-0001")
    emitter = MCPEmitter(principal, "tool-slug", "https://api.example.test", cred_root=root)
    forged = emitter.emit((_verified_tool(),))

    check("MCPEmitter.emit devuelve ForgedMCP", isinstance(forged, C.ForgedMCP))
    check("ForgedMCP.tools intacto (las tools verificadas)", forged.tools == ("get_thing",),
          str(forged.tools))
    belt_path = root / C.credential_namespace(principal) / "tool-slug" / "belt-tool-slug.mcp.json"
    belt = json.loads(belt_path.read_text(encoding="utf-8"))
    check("belt manifest de tool SIGUE con mcpServers{}", "mcpServers" in belt,
          f"keys={sorted(belt.keys())}")
    check("belt manifest de tool NO trae agentServers{} (es una tool, no un agente)",
          "agentServers" not in belt)

    ev = _build_forged_event(forged, ())
    check("evento 'forged' tool-only sigue con tools:[] (no vacío)", ev["tools"] == ["get_thing"],
          str(ev["tools"]))
    check("evento 'forged' tool-only: server_name/belt_ref presentes (byte-equiv)",
          ev["server_name"] == forged.server_name and ev["belt_ref"] == forged.belt_ref)
    check("evento 'forged' tool-only: agents:[] presente y VACÍO (aditivo, invisible)",
          ev.get("agents") == [])
    return {"forged": forged, "event": ev}


# ── 2 · AGENTE equipado — verify → emit_agent → ForgedAgent + agentServers ───────
def gate_equip_agent() -> dict:
    print("\n[2] AGENTE equipado — agent_refs[] / agentServers{} / SSE agents:[]")
    root = Path(tempfile.mkdtemp(prefix="forja-agent-"))
    principal = C.Principal(anon_id="sess-AGENT-0001")

    va = verify_agent_ref(_AGENT_REF_FIXTURE, _REPO_ROOT)
    check("verify_agent_ref → VerifiedAgent (receta hija v1 cargada)",
          isinstance(va, C.VerifiedAgent) and va.recipe.get("schema_version") == "v1",
          f"hijo={va.recipe.get('meta',{}).get('name')!r}")
    check("VerifiedAgent.source_ref es la ref relativa a la receta hija en disco",
          va.source_ref == _AGENT_REF_FIXTURE, str(va.source_ref))

    emitter = AgentEmitter(principal, "padre-slug", cred_root=root)
    forged_agents = emitter.emit_agent((va,))
    check("AgentEmitter.emit_agent → tuple[ForgedAgent] (1 por agente)",
          len(forged_agents) == 1 and isinstance(forged_agents[0], C.ForgedAgent))
    fa = forged_agents[0]
    check("ForgedAgent.recipe_ref = la ref que aterriza en belt.agent_refs[]",
          fa.recipe_ref == _AGENT_REF_FIXTURE, fa.recipe_ref)
    check("ForgedAgent NO tiene campo `tools` (un agente delega, no inlinea tools)",
          not hasattr(fa, "tools"))

    manifest = json.loads((_REPO_ROOT / fa.manifest_ref).read_text(encoding="utf-8"))
    check("belt-agent manifest trae agentServers{} (descriptor paralelo a mcpServers{})",
          "agentServers" in manifest, f"keys={sorted(manifest.keys())}")
    check("belt-agent manifest NO trae mcpServers{} (no es una tool)",
          "mcpServers" not in manifest)
    srv = next(iter(manifest["agentServers"].values()))
    check("agentServers[...] apunta a la receta hija por recipe_ref + type=agent",
          srv.get("type") == "agent" and srv.get("recipe_ref") == _AGENT_REF_FIXTURE,
          json.dumps(srv, ensure_ascii=False))
    return {"forged_agents": forged_agents, "va": va}


# ── 3 · DUAL-MODE — tools:[] Y agents:[] a la vez; lector viejo sigue OK ─────────
def gate_dual_mode(forged: C.ForgedMCP, forged_agents) -> None:
    print("\n[3] DUAL-MODE — el evento 'forged' lleva tools:[] Y agents:[]")

    def reads_tools_only(ev: dict) -> list:
        """Un cliente VIEJO: sólo conoce `tools`. No debe romperse con agents presente."""
        return ev.get("tools") or []

    ev_both = _build_forged_event(forged, forged_agents)
    check("ambos: tools:[] no vacío Y agents:[] no vacío en el MISMO evento",
          bool(ev_both["tools"]) and bool(ev_both["agents"]),
          f"tools={len(ev_both['tools'])} agents={len(ev_both['agents'])}")
    check("ambos: lector viejo (sólo tools) sigue leyendo las tools",
          reads_tools_only(ev_both) == ["get_thing"])
    check("ambos: agents[i] trae agent_name+recipe_ref (payload del sub-agente)",
          ev_both["agents"][0].get("recipe_ref") == _AGENT_REF_FIXTURE
          and bool(ev_both["agents"][0].get("agent_name")))

    ev_agent_only = _build_forged_event(None, forged_agents)
    check("agent-only: tools:[] VACÍO, agents:[] no vacío",
          ev_agent_only["tools"] == [] and bool(ev_agent_only["agents"]))
    check("agent-only: lector viejo (sólo tools) NO se rompe (lee [])",
          reads_tools_only(ev_agent_only) == [])

    ev_tool_only = _build_forged_event(forged, ())
    check("tool-only: lector viejo lee las tools, agents:[] vacío e inocuo",
          reads_tools_only(ev_tool_only) == ["get_thing"] and ev_tool_only["agents"] == [])


# ── 4 · REGLA LOAD-BEARING — agente JAMÁS en belt_refs[]/mcpServers ─────────────
def gate_load_bearing(forged_agents) -> None:
    print("\n[4] LOAD-BEARING — el agente vive en agent_refs[], NUNCA en belt_refs[]")
    fa = forged_agents[0]

    # merge del AGENTE: cae en belt.agent_refs[], jamás en belt_refs[]
    parent = _valid_parent()
    new_cfg, already = registry._merge_agent_into_config(parent, fa.recipe_ref)
    belt = new_cfg["belt"]
    check("_merge_agent_into_config pone el agent_ref en belt.agent_refs[]",
          fa.recipe_ref in (belt.get("agent_refs") or []))
    check("LOAD-BEARING: el agent_ref NO aparece en belt.belt_refs[]",
          fa.recipe_ref not in (belt.get("belt_refs") or [])
          and fa.recipe_ref != belt.get("belt_ref"))
    check("el merge de agente NO toca belt_ref/tool_filters previos (tool y agente conviven)",
          belt.get("belt_ref") == "calc" and belt.get("tool_filters") == {"calc": ["add"]})
    check("merge idempotente: re-merge no duplica",
          registry._merge_agent_into_config(new_cfg, fa.recipe_ref)[1] is True
          and registry._merge_agent_into_config(new_cfg, fa.recipe_ref)[0]["belt"]["agent_refs"].count(fa.recipe_ref) == 1)

    # merge de la TOOL: cae en belt_refs[], jamás toca agent_refs[]
    cfg2, _ = registry._merge_belt_into_config(_valid_parent(), "data/x/belt-x.mcp.json",
                                               "forged-x", "get_thing")
    check("_merge_belt_into_config (tool) NO crea/escribe belt.agent_refs[]",
          "agent_refs" not in cfg2["belt"])
    check("_merge_belt_into_config (tool) pone la ref en belt.belt_refs[]",
          "data/x/belt-x.mcp.json" in cfg2["belt"]["belt_refs"])


# ── 5 · VALIDA (paso 1) — la receta con el agente equipado pasa validate_recipe ──
def gate_validates(forged_agents) -> dict:
    print("\n[5] VALIDA — la receta resultante pasa el validador del paso 1")
    fa = forged_agents[0]
    parent = _valid_parent()
    new_cfg, _ = registry._merge_agent_into_config(parent, fa.recipe_ref)
    try:
        warnings = validate_recipe(new_cfg, repo_root=_REPO_ROOT)
        ok = True
        detail = f"valida (warnings={len(warnings)})"
    except RecipeValidationError as e:
        ok = False
        detail = str(e.errors[:2])
    check("receta padre + agent_ref equipado VALIDA con validate_recipe (paso 1)", ok, detail)
    return {"recipe": new_cfg}


# ── 6 · RESOLVER (paso 1) — el recipe_ref resuelve a un AGENTE (no a una tool) ──
def gate_resolver(forged_agents) -> None:
    print("\n[6] RESOLVER paso 1 — recipe_ref → ResolvedAgent type='agent' (paso 2 delega)")
    fa = forged_agents[0]
    ra = R.resolve_agent_ref(fa.recipe_ref, _REPO_ROOT)
    check("el recipe_ref forjado resuelve a ResolvedAgent type='agent'",
          ra.type == "agent")
    check("el resolver carga la receta hija v1 (el motor del paso 2 ramifica a DELEGAR)",
          isinstance(ra.recipe, dict) and ra.recipe.get("schema_version") == "v1"
          and ra.recipe.get("meta", {}).get("name") == "Sub-agente Research",
          f"hijo={ra.recipe.get('meta',{}).get('name')!r}")
    # negativa: un belt (mcpServers, no receta) NO se cuela como agente
    try:
        R.resolve_agent_ref("platform/assembler/fixtures/belt-calc.mcp.json", _REPO_ROOT)
        check("un belt (mcpServers) NO resuelve como agente", False, "no lanzó")
    except R.AgentResolutionError:
        check("un belt (mcpServers) NO resuelve como agente (check estructural v1 lo frena)", True)


def main() -> int:
    print("═" * 74)
    print("  GATE VERDE · PASO 4 — la FORJA equipa un AGENTE (camino paralelo al de tools)")
    print("═" * 74)
    t = gate_regression_tool()
    a = gate_equip_agent()
    gate_dual_mode(t["forged"], a["forged_agents"])
    gate_load_bearing(a["forged_agents"])
    gate_validates(a["forged_agents"])
    gate_resolver(a["forged_agents"])
    print("\n" + "═" * 74)
    if _FAILS:
        print(f"  ROJO — {len(_FAILS)} check(s) fallaron: {_FAILS}")
        return 1
    print("  VERDE — la forja equipa un AGENTE sin romper el camino de tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
