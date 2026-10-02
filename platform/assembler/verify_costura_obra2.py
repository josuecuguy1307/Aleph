#!/usr/bin/env python3
"""Vara única Gate 3 · Obra 2: causa tipada con origen (D1/D2).

Ejecuta el loop productivo con el belt calc y cerebro determinista. Sólo se
simulan resultados/diagnósticos para cubrir las familias de error: la costura,
el evento y la trayectoria son las reales.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "product" / "backend"
for path in (HERE, ROOT / "platform", BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import recipe_assembler as ra  # noqa: E402
from app.phase1.executor import build_trajectory_from_record  # noqa: E402
from errores_modelo import CAUSAS  # noqa: E402
from tool_result import (clasificar_error_de_tool, es_error_de_tool,
                         resultado_de_error_para_modelo)  # noqa: E402

BELT = "platform/assembler/fixtures/belt-calc.mcp.json"
PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: Any = "") -> None:
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
        "meta": {"name": "Costura Obra 2", "nicho": "test"},
        "model": {"primary": "stub", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 128, "max_turns": 3},
        "belt": {"belt_ref": BELT, "tool_filters": {"calc": ["add"]}},
        "framing": {"inline": "test"}, "rag": {"enabled": False},
        "keys": {}, "gates": {},
    }


def run_case(arguments_text: str, *, simulated_result: str | None = None,
             diagnostico: Any = None, deadline_on_boundary: bool = False) -> dict:
    events: list[dict] = []
    second_messages: list[dict] = []
    calls = {"registry": 0, "gate": 0}
    turn = {"n": 0}

    original_chat = ra._asm._chat
    original_call = ra.LazyToolRegistry.call
    original_diagnostic = ra.LazyToolRegistry.diagnostico_for
    original_build_gate = ra._enforcer.build_enforced_gate
    original_token = ra.secrets.token_hex
    original_monotonic = ra.time.monotonic

    def chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kwargs):
        turn["n"] += 1
        if turn["n"] == 1:
            if deadline_on_boundary:
                # Sólo después de que el modelo emitió la call: el guard existente de
                # frontera debe cortar antes del registry, sin cancelar ninguna call en vuelo.
                ra.time.monotonic = lambda: original_monotonic() + 1000.0
            return {"choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "", "tool_calls": [{
                    "id": "call-obra2", "type": "function",
                    "function": {"name": "add", "arguments": arguments_text},
                }],
            }}]}
        second_messages.extend(dict(m) for m in messages)
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "listo"}}]}

    def call_spy(self, name, args):
        calls["registry"] += 1
        if simulated_result is not None:
            return simulated_result
        return original_call(self, name, args)

    def diagnostic_spy(self, name):
        return diagnostico if diagnostico is not None else original_diagnostic(self, name)

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
    ra.LazyToolRegistry.diagnostico_for = diagnostic_spy
    ra._enforcer.build_enforced_gate = build_gate_spy
    ra.secrets.token_hex = lambda _n=4: "01020304"
    try:
        record = ra.assemble_and_run(recipe(), "prueba", repo_root=ROOT,
                                     approve=lambda _s, _t, _p: True,
                                     on_event=events.append)
    finally:
        ra._asm._chat = original_chat
        ra.LazyToolRegistry.call = original_call
        ra.LazyToolRegistry.diagnostico_for = original_diagnostic
        ra._enforcer.build_enforced_gate = original_build_gate
        ra.secrets.token_hex = original_token
        ra.time.monotonic = original_monotonic
    return {"record": record, "events": events, "messages": second_messages, "calls": calls}


def finished(case: dict) -> dict:
    return next(event for event in case["events"] if event.get("type") == "tool_call_finished")


def tool_message(case: dict) -> dict:
    return next(message for message in case["messages"] if message.get("role") == "tool")


def main() -> int:
    print("=== verify_costura_obra2 · D1+D2 ===")

    timeout = run_case('{"a":2,"b":3}', simulated_result="[MCP error: request timed out]",
                       diagnostico={"timeouts": [{"timeout_s": 2.5,
                                                     "vencio_el_reloj": True}]})
    timeout_event = finished(timeout)
    timeout_step = next(step for step in build_trajectory_from_record(timeout["record"])
                        if step["kind"] == "tool_call")
    timeout_message = tool_message(timeout)["content"]
    check("V1 timeout: evento causa/origen/reintento/reloj",
          timeout_event.get("status") == "error"
          and timeout_event.get("causa") == "timeout"
          and timeout_event.get("origen") == "conector"
          and timeout_event.get("reintentable") is True
          and timeout_event.get("timeout_s", 0) > 0
          and timeout_event.get("vencio_el_reloj") is True, timeout_event)
    check("V1 timeout: sufijo al modelo", "[causa=timeout origen=conector reintentable=si]"
          in timeout_message, timeout_message)
    check("V1 timeout: trayectoria lleva la causa", timeout_step.get("causa") == "timeout"
          and timeout_step.get("timeout_s") == 2.5 and timeout_step.get("error") is not None,
          timeout_step)

    class TimeoutServer:
        def __init__(self):
            self.timeouts = [{"timeout_s": 9.0, "vencio_el_reloj": True}]

        def diagnostico(self):
            return {"timeouts": list(self.timeouts)}

        def call_tool(self, _name, _args):
            self.timeouts.append({"timeout_s": 2.5, "vencio_el_reloj": True})
            return "[MCP error: request timed out]"

    timeout_server = TimeoutServer()
    registry = object.__new__(ra.LazyToolRegistry)
    registry._servers = {"add": timeout_server}
    registry._raw_by_name = {"add": "add"}
    registry._diagnostico_antes = {}
    registry.call("add", {})
    measured_timeouts = registry.diagnostico_for("add").get("timeouts")
    check("V1 timeout: no atribuye reloj histórico a la call actual",
          measured_timeouts == [
              {"timeout_s": 2.5, "vencio_el_reloj": True}],
          measured_timeouts)

    dead = clasificar_error_de_tool("[MCP error: no response from calc]")
    no_network = clasificar_error_de_tool("[MCP error: no response from calc]",
                                          {"causa": "sin_red"})
    check("V2 server muerto es conector/proveedor", dead.causa == "proveedor_caido"
          and dead.origen == "conector" and dead.reintentable is True, dead.como_dict())
    check("V2 red medida no se confunde con server", no_network.causa == "sin_red"
          and no_network.origen == "conector", no_network.como_dict())

    uncabled = run_case('{"a":2,"b":3}',
                        simulated_result="[error: tool 'add' no está cableado en esta receta]")
    uncabled_event = finished(uncabled)
    check("V3 no cableada es aleph y no reintentable",
          uncabled_event.get("origen") == "aleph"
          and uncabled_event.get("reintentable") is False
          and uncabled_event.get("causa") == "falla_de_aleph", uncabled_event)

    invalid = run_case('{"a":2')
    invalid_event = finished(invalid)
    invalid_message = tool_message(invalid)["content"]
    check("V4 args inválidos no ejecutan", invalid["calls"] == {"registry": 0, "gate": 0},
          invalid["calls"])
    check("V4 args inválidos firma modelo", invalid_event.get("origen") == "modelo"
          and invalid_event.get("reintentable") is True
          and invalid_event.get("causa") == "argumentos_invalidos"
          and "[causa=argumentos_invalidos origen=modelo reintentable=si]" in invalid_message,
          invalid_message)
    gate = clasificar_error_de_tool("[gate: requiere tu OK antes de ejecutar]")
    check("V4 gate usa causa sellada", gate.causa == "gate_bloqueado"
          and gate.origen == "aleph" and gate.reintentable is False, gate.como_dict())

    deadline = run_case('{"a":2,"b":3}', deadline_on_boundary=True)
    deadline_final = next(event for event in deadline["events"] if event.get("type") == "final")
    check("V5 deadline no ejecuta ni pasa el gate", deadline["calls"] == {"registry": 0, "gate": 0},
          deadline["calls"])
    check("V5 deadline conserva el corte y sólo lo firma",
          deadline["record"].get("stop_reason") == "deadline"
          and deadline["record"].get("stop_causa", {}).get("causa") == "timeout"
          and deadline["record"].get("stop_causa", {}).get("origen") == "aleph"
          and deadline_final.get("causa") == "timeout" and deadline_final.get("origen") == "aleph",
          {"record": deadline["record"].get("stop_causa"), "final": deadline_final})

    secret = "sk-secret-token-123456789"
    weird_inputs = [None, b"\xff", "\x00[MCP error]", secret, object()]
    fuzzed = [clasificar_error_de_tool(value, {"origen": "runtime"}) for value in weird_inputs]
    check("V6 fuzz siempre devuelve CausaCostura válida",
          all(item.causa in CAUSAS and item.origen in {"modelo", "conector", "aleph"}
              and isinstance(item.reintentable, bool) for item in fuzzed),
          [item.como_dict() for item in fuzzed])
    check("V6 detalle jamás copia secreto", all(secret not in item.detalle for item in fuzzed),
          [item.detalle for item in fuzzed])
    check("V6 mapea cli/runtime/aleph al leer",
          clasificar_error_de_tool("[tool error] x", {"origen": "cli"}).origen == "modelo"
          and clasificar_error_de_tool("[tool error] x", {"origen": "runtime"}).origen == "modelo"
          and clasificar_error_de_tool("[tool error] x", {"origen": "aleph"}).origen == "aleph")

    valid = run_case('{"a":2,"b":3}')
    valid_event = finished(valid)
    valid_message = tool_message(valid)["content"]
    expected = ra._TOOL_SPOTLIGHT_HDR.format(n="01020304") + (
        "\n<<datos-01020304>>\n5.0\n<<fin-01020304>>")
    check("V7 éxito no lleva causa", all(key not in valid_event for key in
          ("causa", "origen", "reintentable", "timeout_s", "vencio_el_reloj")), valid_event)
    check("V7 retorno de éxito byte-comparable", valid_message == expected, repr(valid_message))

    obra1 = subprocess.run([sys.executable, str(HERE / "verify_costura_obra1.py")],
                           cwd=ROOT, text=True, capture_output=True)
    gate1 = subprocess.run([sys.executable, "-m", "pytest", "platform/assembler/test_gate_in_path.py"],
                           cwd=ROOT, text=True, capture_output=True)
    check("V8 vara Obra 1 sigue verde", obra1.returncode == 0,
          (obra1.stdout + obra1.stderr).splitlines()[-1:])
    check("V8 Gate 1 4/4 sigue verde", gate1.returncode == 0 and "4 passed" in gate1.stdout,
          (gate1.stdout + gate1.stderr).splitlines()[-3:])

    print(f"=== {PASSED} passed, {FAILED} failed ===")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
