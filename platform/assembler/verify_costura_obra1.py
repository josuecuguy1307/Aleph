#!/usr/bin/env python3
"""Vara única Gate 3 · Obra 1: honestidad del evento + arguments D4/D5.

Corre el loop productivo con calc MCP real y cerebro determinista. Sólo se simula
el texto de salida cuando la vara necesita provocar cada familia de error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "product" / "backend"
for path in (HERE, ROOT / "platform", BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import recipe_assembler as ra  # noqa: E402
from app.phase1.executor import build_trajectory_from_record  # noqa: E402
from tool_result import es_error_de_tool  # noqa: E402

BELT = "platform/assembler/fixtures/belt-calc.mcp.json"
PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail="") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"PASS {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"FAIL {name}" + (f" — {detail}" if detail else ""))


def recipe() -> dict:
    return {
        "schema_version": "v1",
        "meta": {"name": "Costura Obra 1", "nicho": "test"},
        "model": {"primary": "stub", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 128, "max_turns": 3},
        "belt": {"belt_ref": BELT, "tool_filters": {"calc": ["add"]}},
        "framing": {"inline": "test"}, "rag": {"enabled": False},
        "keys": {}, "gates": {},
    }


def run_case(arguments_text: str, *, simulated_result: str | None = None) -> dict:
    events: list[dict] = []
    second_messages: list[dict] = []
    calls = {"registry": 0, "gate": 0}
    turn = {"n": 0}

    def chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kwargs):
        turn["n"] += 1
        if turn["n"] == 1:
            return {"choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "", "tool_calls": [{
                    "id": "call-obra1", "type": "function",
                    "function": {"name": "add", "arguments": arguments_text},
                }],
            }}]}
        second_messages.extend(dict(m) for m in messages)
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "listo"}}]}

    original_chat = ra._asm._chat
    original_call = ra.LazyToolRegistry.call
    original_build_gate = ra._enforcer.build_enforced_gate
    original_token = ra.secrets.token_hex

    def call_spy(self, name, args):
        calls["registry"] += 1
        if simulated_result is not None:
            return simulated_result
        return original_call(self, name, args)

    def build_gate_spy(*args, **kwargs):
        gate = original_build_gate(*args, **kwargs)
        original_evaluate = gate.evaluate

        def evaluate(*ev_args, **ev_kwargs):
            calls["gate"] += 1
            return original_evaluate(*ev_args, **ev_kwargs)

        gate.evaluate = evaluate
        return gate

    ra._asm._chat = chat
    ra.LazyToolRegistry.call = call_spy
    ra._enforcer.build_enforced_gate = build_gate_spy
    ra.secrets.token_hex = lambda _n=4: "01020304"
    try:
        record = ra.assemble_and_run(recipe(), "prueba", repo_root=ROOT,
                                     approve=lambda _s, _t, _p: True,
                                     on_event=events.append)
    finally:
        ra._asm._chat = original_chat
        ra.LazyToolRegistry.call = original_call
        ra._enforcer.build_enforced_gate = original_build_gate
        ra.secrets.token_hex = original_token
    return {"record": record, "events": events, "messages": second_messages, "calls": calls}


def finished(case: dict) -> dict:
    return next(e for e in case["events"] if e.get("type") == "tool_call_finished")


def tool_message(case: dict) -> dict:
    return next(m for m in case["messages"] if m.get("role") == "tool")


def main() -> int:
    print("=== verify_costura_obra1 · D4+D5 ===")

    for label, result in (
        ("V1 MCP", "[MCP error: x]"),
        ("V2 tool", "[tool error] x"),
        ("V2 uncabled", "[error: tool 'x' no está cableado en esta receta]"),
    ):
        case = run_case('{"a":2,"b":3}', simulated_result=result)
        event = finished(case)
        trajectory = build_trajectory_from_record(case["record"])
        step = next(s for s in trajectory if s["kind"] == "tool_call")
        check(f"{label}: matcher único", es_error_de_tool(result))
        check(f"{label}: evento status=error", event.get("status") == "error", event)
        check(f"{label}: trayectoria error!=None", step.get("error") is not None, step)

    invalid = run_case('{"a":2')
    invalid_event = finished(invalid)
    invalid_msg = tool_message(invalid)
    check("V3 JSON inválido no ejecuta registry", invalid["calls"]["registry"] == 0,
          invalid["calls"])
    check("V3 JSON inválido no llega al gate", invalid["calls"]["gate"] == 0,
          invalid["calls"])
    check("V3 modelo recibe error y reintento", "reintenta" in invalid_msg["content"]
          and "NO se ejecutó" in invalid_msg["content"])
    check("V3 evento error + executed:false", invalid_event.get("status") == "error"
          and invalid_event.get("executed") is False, invalid_event)

    valid = run_case('{"a":2,"b":3}')
    valid_event = finished(valid)
    valid_msg = tool_message(valid)
    expected = ra._TOOL_SPOTLIGHT_HDR.format(n="01020304") + (
        "\n<<datos-01020304>>\n5.0\n<<fin-01020304>>")
    check("V4 args válidos ejecutan una vez", valid["calls"]["registry"] == 1,
          valid["calls"])
    check("V4 retorno al modelo byte-comparable", valid_msg["content"] == expected,
          repr(valid_msg["content"]))

    missing = run_case('{"a":2}')
    missing_event = finished(missing)
    check("V5 required ausente no ejecuta", missing["calls"] == {"registry": 0, "gate": 0},
          missing["calls"])
    check("V5 required explica campo y devuelve error", "required" in tool_message(missing)["content"]
          and missing_event.get("status") == "error")

    wrong_type = run_case('{"a":"dos","b":3}')
    check("V5 tipo raíz inválido no ejecuta", wrong_type["calls"] == {"registry": 0, "gate": 0},
          wrong_type["calls"])
    check("V5 tipo raíz explica el contrato", "debe ser number" in tool_message(wrong_type)["content"])

    check("V6 call medida lleva wall_s > 0", isinstance(valid_event.get("wall_s"), float)
          and valid_event["wall_s"] > 0, valid_event.get("wall_s"))
    check("V6 rechazo no medido omite wall_s", "wall_s" not in invalid_event, invalid_event)
    check("O4 evento emite ambos campos iguales", valid_event.get("gate_action") == "execute"
          and valid_event.get("gate_decision") == valid_event.get("gate_action"), valid_event)

    print(f"=== {PASSED} passed, {FAILED} failed ===")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
