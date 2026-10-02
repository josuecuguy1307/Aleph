#!/usr/bin/env python3
"""
test_gate_in_path.py — el ENFORCER DE GATES está EN EL PATH del run (Security §3.5).

Prueba el CABLEADO (no la lógica interna del enforcer, que tiene su propio suite en
platform/gates/tests_recipe_enforcer.py): que `assemble_and_run` construye el gate
DESDE la receta vía recipe_enforcer.build_enforced_gate ANTES de ejecutar tools, y
que TODA tool-call del loop pasa por el gate antes de correr.

Sin mocks de nuestras piezas: bootea el MCP calc REAL por stdio. El ÚNICO stub es el
LLM (_asm._chat) — no llamamos a ningún modelo ni gateway (no hay API key, no hay plata
en juego), pero el loop, el registro de tools, el gate y el MCP server son los reales.

Casos:
  1. El run construye el gate desde la receta (gate_enforced=True), el gate evalúa
     CADA tool-call en el path, y CON aprobación (callback human-in-the-loop, hook de
     la fase Verificación) la tool corre de verdad contra el MCP calc real. SIN
     aprobación, el gate fail-cierra la tool (la duda nunca ejecuta sola) — el candado
     está en el camino, no al costado.
  2. Una receta con gates 'off' IGUAL queda needs_ok para money/send: el gate derivado
     fuerza los mandatorios (la invariante §3.5). Verificado sobre el gate construido
     por el MISMO build_enforced_gate que usa el assembler.
  3. Una tool money/send cae a NEEDS_OK en el path y NO se ejecuta (MONEY-TOUCH OFF
     hasta la verificación E2E): la tool queda registrada como needs_ok, sin correr.
  4. Fail-closed: si la matriz base intenta degradar el gate, build_enforced_gate
     LANZA y el run devuelve error gate fail-closed (no se levanta el puppet).

Run: python3 test_gate_in_path.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import recipe_assembler as ra  # noqa: E402

REPO_ROOT = _THIS.parents[1]
CALC_BELT_REF = "platform/assembler/fixtures/belt-calc.mcp.json"

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


def _recipe(tool_filters: dict, gates: dict | None = None) -> dict:
    """Receta v1 anidada mínima apuntando al belt calc real (credential-free)."""
    return {
        "schema_version": "v1",
        "meta": {"name": "Gate Path Test", "nicho": "test"},
        "model": {
            "primary": "stub-model",
            "base_url": "http://127.0.0.1:0/v1",  # nunca se contacta: _chat está stubbeado
            "temperature": 0,
            "max_tokens": 256,
            "max_turns": 4,
        },
        "belt": {"belt_ref": CALC_BELT_REF, "tool_filters": tool_filters},
        "framing": {"inline": "Sos un test."},
        "rag": {"enabled": False},
        "keys": {},
        "gates": gates if gates is not None else {},
    }


def _stub_chat_calling(tool_name: str, arguments: dict):
    """Devuelve un _chat falso: primera llamada pide `tool_name`, segunda responde stop.

    Imita la forma de respuesta OpenAI que el loop espera. NO contacta ningún modelo.
    """
    state = {"turn": 0}

    def fake_chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kw):
        # **kw absorbe kwargs aditivos del contrato real de _asm._chat (p.ej. cli_model,
        # que el annex BYO-CLI de cuarto-ui empezó a pasar SIEMPRE) sin acoplar el stub.
        state["turn"] += 1
        if state["turn"] == 1:
            return {
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": tool_name,
                                         "arguments": json.dumps(arguments)},
                        }],
                    },
                }]
            }
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "listo"},
            }]
        }

    return fake_chat


# ── 1. el gate está EN EL PATH: sin OK frena; con OK ejecuta de verdad ───────────
def test_gate_in_path_blocks_then_runs_with_approval():
    # 1a) SIN aprobación: el gate fail-cierra la tool desconocida (add no es lectura
    #     obvia por nombre) — queda needs_ok y NO se ejecuta. El candado está en medio.
    orig = ra._asm._chat
    ra._asm._chat = _stub_chat_calling("add", {"a": 2, "b": 3})
    try:
        out_no = ra.assemble_and_run(_recipe({"calc": ["add", "mul"]}),
                                     "sumá 2 y 3", repo_root=REPO_ROOT)
    finally:
        ra._asm._chat = orig

    check("1.1 gate_enforced=True (se construyó el gate desde la receta)",
          out_no.get("gate_enforced") is True, f"out.error={out_no.get('error')}")
    decs = out_no.get("gate_decisions", [])
    check("1.2 el gate evaluó la tool-call en el path",
          any(d["tool"] == "add" for d in decs), f"gate_decisions={decs}")
    tc_no = next((t for t in out_no.get("tool_calls", []) if t["tool"] == "add"), {})
    check("1.3 SIN OK la tool no corre (fail-closed: la duda no ejecuta sola)",
          tc_no.get("gate_action") == "needs_ok"
          and "gate:" in str(tc_no.get("result", "")).lower(),
          f"tool_call={tc_no}")

    # 1b) CON aprobación (callback de la fase Verificación): el gate pasa a EXECUTE y
    #     la tool corre de verdad contra el MCP calc real (5 = 2+3).
    orig = ra._asm._chat
    ra._asm._chat = _stub_chat_calling("add", {"a": 2, "b": 3})
    try:
        out_ok = ra.assemble_and_run(_recipe({"calc": ["add", "mul"]}),
                                     "sumá 2 y 3", repo_root=REPO_ROOT,
                                     approve=lambda s, t, p: True)
    finally:
        ra._asm._chat = orig

    tc_ok = next((t for t in out_ok.get("tool_calls", []) if t["tool"] == "add"), {})
    check("1.4 CON OK la tool SE EJECUTÓ de verdad (resultado real del MCP calc: 5)",
          "5" in str(tc_ok.get("result", "")), f"tool_call={tc_ok}")


# ── 2. receta con gates 'off' -> money/send IGUAL needs_ok (invariante §3.5) ─────
def test_recipe_off_still_forces_mandatory():
    recipe = _recipe({"calc": ["add"]}, gates={"money_touch": "off", "send": "off"})
    # el MISMO punto de entrada que usa el assembler en el path:
    gate = ra._enforcer.build_enforced_gate(recipe)
    dm = gate.evaluate("broker", "place_order", {"symbol": "AAPL"})
    ds = gate.evaluate("mailer", "send_message", {"to": "x@y.z"})
    check("2.1 money_touch forzado a needs_ok aunque la receta diga off",
          dm.action == "needs_ok" and dm.level == "confirma-siempre",
          f"place_order -> {dm.action}/{dm.level}")
    check("2.2 send forzado a needs_ok aunque la receta diga off",
          ds.action == "needs_ok" and ds.level == "confirma-siempre",
          f"send_message -> {ds.action}/{ds.level}")


# ── 3. una tool money cae a NEEDS_OK en el path y NO se ejecuta ──────────────────
def test_money_tool_gated_in_path_not_executed():
    # El loop pide una tool con nombre money ("place_order"). No está cableada en calc,
    # pero el gate la clasifica por NOMBRE (no por el belt) y la frena ANTES de llamar
    # registry.call. Verificamos que el path la registró como needs_ok y NO la ejecutó.
    orig = ra._asm._chat
    ra._asm._chat = _stub_chat_calling("place_order", {"symbol": "AAPL", "qty": 10})
    try:
        rec = _recipe({"calc": ["add"]}, gates={"money_touch": "off"})
        out = ra.assemble_and_run(rec, "comprá 10 AAPL", repo_root=REPO_ROOT)
    finally:
        ra._asm._chat = orig

    decs = out.get("gate_decisions", [])
    pd = next((d for d in decs if d["tool"] == "place_order"), {})
    check("3.1 place_order evaluado por el gate en el path",
          bool(pd), f"gate_decisions={decs}")
    check("3.2 place_order -> NEEDS_OK aunque la receta puso money_touch off",
          pd.get("action") == "needs_ok", f"place_order_dec={pd}")
    tc = next((t for t in out.get("tool_calls", []) if t["tool"] == "place_order"), {})
    check("3.3 la tool money NO se ejecutó (resultado = aviso de gate, no salida real)",
          "gate:" in str(tc.get("result", "")).lower()
          and tc.get("gate_action") == "needs_ok",
          f"tool_call={tc}")


# ── 4. fail-closed: matriz que degrada el gate -> build LANZA, run no levanta ─────
def test_fail_closed_when_gate_cannot_be_built():
    # base_matrix que intenta degradar 'confirma-siempre' a no-requires_ok: el enforcer
    # re-asegura el nivel, así que para forzar el fallo pasamos una receta cuyo gate no
    # se pueda construir. Probamos el contrato real: si build_enforced_gate LANZA, el
    # run devuelve error gate fail-closed y NO corre el loop.
    orig = ra._enforcer.build_enforced_gate

    def boom(recipe, base_matrix=None, **kw):
        raise AssertionError("falta el gate mandatorio money_touch")

    ra._enforcer.build_enforced_gate = boom
    try:
        out = ra.assemble_and_run(_recipe({"calc": ["add"]}), "x", repo_root=REPO_ROOT)
    finally:
        ra._enforcer.build_enforced_gate = orig

    check("4.1 run fail-closed: error de gate, no se levantó el puppet",
          out.get("ok") is False and "gate fail-closed" in str(out.get("error", "")),
          f"out.error={out.get('error')}")
    check("4.2 no se ejecutó ninguna tool bajo fail-closed",
          out.get("tool_calls") == [], f"tool_calls={out.get('tool_calls')}")


def main():
    print("=== gate-in-path integration suite (real calc MCP; LLM stubbed) ===\n")
    test_gate_in_path_blocks_then_runs_with_approval()
    test_recipe_off_still_forces_mandatory()
    test_money_tool_gated_in_path_not_executed()
    test_fail_closed_when_gate_cannot_be_built()
    print(f"\n=== {_passed} passed, {_failed} failed ===")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
