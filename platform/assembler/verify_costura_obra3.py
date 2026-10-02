#!/usr/bin/env python3
"""Vara única Gate 3 · Obra 3: scrub de la costura y remapeo D7.

Usa el loop productivo con belt calc. El callback de eventos escribe un events.jsonl
simulado y genera sus frames SSE con el formateador real; ninguna aserción confía en
un mock de la costura.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "product" / "backend"
for path in (HERE, ROOT / "platform", BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import recipe_assembler as ra  # noqa: E402
from app.phase1.event_stream import format_sse  # noqa: E402
from tool_result import CausaCostura  # noqa: E402

BELT = "platform/assembler/fixtures/belt-calc.mcp.json"
SECRET = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
MARKER = "[contenido retenido por scrub]"
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
        "meta": {"name": "Costura Obra 3", "nicho": "test"},
        "model": {"primary": "stub", "base_url": "http://127.0.0.1:0/v1",
                  "temperature": 0, "max_tokens": 128, "max_turns": 3},
        "belt": {"belt_ref": BELT, "tool_filters": {"calc": ["add"]}},
        "framing": {"inline": "test"}, "rag": {"enabled": False},
        "keys": {}, "gates": {},
    }


def run_case(arguments_text: str, *, simulated_result: str = "5.0",
             force_gate: bool = False, cause_detail_secret: bool = False,
             broken_scrubber: bool = False) -> dict:
    events: list[dict] = []
    second_messages: list[dict] = []
    calls = {"registry": 0, "gate": 0, "args": None}
    turn = {"n": 0}

    original_chat = ra._asm._chat
    original_call = ra.LazyToolRegistry.call
    original_build_gate = ra._enforcer.build_enforced_gate
    original_classifier = ra.clasificar_error_de_tool
    original_scrubber = ra._scrubber_mod
    original_token = ra.secrets.token_hex

    def chat(messages, tools, base_url, model, api_key, max_tokens, temperature, **kwargs):
        turn["n"] += 1
        if turn["n"] == 1:
            return {"choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "", "tool_calls": [{
                    "id": "call-obra3", "type": "function",
                    "function": {"name": "add", "arguments": arguments_text},
                }],
            }}]}
        second_messages.extend(dict(m) for m in messages)
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "listo"}}]}

    def call_spy(self, name, args):
        calls["registry"] += 1
        calls["args"] = dict(args)
        return simulated_result

    def build_gate_spy(*args, **kwargs):
        gate = original_build_gate(*args, **kwargs)
        original_evaluate = gate.evaluate

        def evaluate(*ev_args, **ev_kwargs):
            calls["gate"] += 1
            decision = original_evaluate(*ev_args, **ev_kwargs)
            if force_gate:
                return type(decision)(decision.NEEDS_OK, "confirma-siempre",
                                      {"leyenda": "control de gate de la vara"})
            return decision

        gate.evaluate = evaluate
        return gate

    def classifier_spy(resultado, diagnostico=None, **kwargs):
        causa = original_classifier(resultado, diagnostico, **kwargs)
        if cause_detail_secret:
            return CausaCostura(causa.causa, causa.origen, causa.reintentable,
                                 causa.timeout_s, causa.vencio_el_reloj,
                                 f"diagnóstico de prueba {SECRET}")
        return causa

    class BrokenScrubber:
        class OutputScrubber:
            def scrub(self, _text):
                raise RuntimeError("falla simulada")

    ra._asm._chat = chat
    ra.LazyToolRegistry.call = call_spy
    ra._enforcer.build_enforced_gate = build_gate_spy
    ra.clasificar_error_de_tool = classifier_spy
    ra._scrubber_mod = BrokenScrubber if broken_scrubber else original_scrubber
    ra.secrets.token_hex = lambda _n=4: "01020304"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"

            def emit(event: dict) -> None:
                events.append(dict(event))
                with events_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")

            record = ra.assemble_and_run(
                recipe(), "prueba", repo_root=ROOT,
                approve=None if force_gate else (lambda _s, _t, _p: True), on_event=emit)
            jsonl = events_path.read_text(encoding="utf-8")
            sse = "".join(format_sse(event) for event in events)
    finally:
        ra._asm._chat = original_chat
        ra.LazyToolRegistry.call = original_call
        ra._enforcer.build_enforced_gate = original_build_gate
        ra.clasificar_error_de_tool = original_classifier
        ra._scrubber_mod = original_scrubber
        ra.secrets.token_hex = original_token
    return {"record": record, "events": events, "messages": second_messages,
            "calls": calls, "jsonl": jsonl, "sse": sse}


def finished(case: dict) -> dict:
    return next(event for event in case["events"] if event.get("type") == "tool_call_finished")


def tool_message(case: dict) -> dict:
    return next(message for message in case["messages"] if message.get("role") == "tool")


def contains_secret(value: Any) -> bool:
    return SECRET in json.dumps(value, ensure_ascii=False, default=str)


def main() -> int:
    print("=== verify_costura_obra3 · D7 + remapeo ===")

    result_secret = run_case('{"a":2,"b":3}',
                             simulated_result=f"[tool error] respuesta {SECRET}",
                             cause_detail_secret=True)
    result_event = finished(result_secret)
    result_model = tool_message(result_secret)["content"]
    result_detail = result_secret["record"]["tool_calls"][0]["detalle"]
    check("V1 resultado secreto no llega a JSONL/SSE/modelo/detalle",
          not any(SECRET in value for value in (
              result_secret["jsonl"], result_secret["sse"], result_model, result_detail))
          and result_event.get("status") == "error",
          {"result": result_event.get("result"), "detalle": result_event.get("detalle")})

    args_secret = run_case(json.dumps({"a": 2, "b": 3, "byok": SECRET}))
    args_events = [event for event in args_secret["events"]
                   if event.get("type") in {"tool_call_started", "tool_call_finished"}]
    check("V2 args secretos no llegan a JSONL/SSE/eventos/modelo",
          args_secret["calls"]["args"].get("byok") == SECRET
          and not contains_secret(args_events)
          and SECRET not in args_secret["jsonl"] and SECRET not in args_secret["sse"]
          and SECRET not in tool_message(args_secret)["content"],
          {"eventos": args_events, "registry_calls": args_secret["calls"]["registry"]})

    clean = run_case('{"a":2,"b":3}')
    clean_event = finished(clean)
    clean_model = tool_message(clean)["content"]
    expected = ra._TOOL_SPOTLIGHT_HDR.format(n="01020304") + (
        "\n<<datos-01020304>>\n5.0\n<<fin-01020304>>")
    check("V3 resultado limpio conserva bytes", clean_event.get("result") == "5.0"
          and clean_model == expected and not clean["record"].get("scrub"), repr(clean_model))

    broken = run_case('{"a":2,"b":3}', simulated_result=f"[tool error] {SECRET}",
                      cause_detail_secret=True, broken_scrubber=True)
    broken_event = finished(broken)
    broken_model = tool_message(broken)["content"]
    check("V4 falla del scrubber retiene marcador y nunca crudo",
          MARKER in broken_event.get("result", "") and MARKER in broken_event.get("detalle", "")
          and MARKER in broken_model and not any(SECRET in value for value in (
              broken["jsonl"], broken["sse"], broken_model,
              broken["record"]["tool_calls"][0]["detalle"]))
          and any(item["status"].startswith("retenido_") for item in broken["record"].get("scrub", [])),
          {"evento": broken_event, "scrub": broken["record"].get("scrub")})

    invalid = run_case('{"a":2')
    invalid_event = finished(invalid)
    invalid_message = tool_message(invalid)["content"]
    gated = run_case('{"a":2,"b":3}', force_gate=True)
    gate_event = next(event for event in gated["events"] if event.get("type") == "gate_waiting")
    gate_message = tool_message(gated)["content"]
    check("V5 remapeo args usa argumentos_invalidos en evento y sufijo",
          invalid["calls"]["registry"] == 0 and invalid_event.get("causa") == "argumentos_invalidos"
          and "[causa=argumentos_invalidos origen=modelo reintentable=si]" in invalid_message,
          {"evento": invalid_event, "modelo": invalid_message})
    check("V5 remapeo gate usa gate_bloqueado en evento y sufijo",
          gated["calls"]["registry"] == 0 and gate_event.get("causa") == "gate_bloqueado"
          and "[causa=gate_bloqueado origen=aleph reintentable=no]" in gate_message,
          {"evento": gate_event, "modelo": gate_message})

    commands = [
        ("Obra 1 22/22", [sys.executable, str(HERE / "verify_costura_obra1.py")]),
        ("Obra 2 remapeada", [sys.executable, str(HERE / "verify_costura_obra2.py")]),
        ("Gate 1", [sys.executable, "-m", "pytest", "platform/assembler/test_gate_in_path.py"]),
        ("regresión assembler/executor/enforcer", [
            sys.executable, "-m", "pytest", "-q", "platform/assembler/test_gate_in_path.py",
            "product/backend/app/phase1/test_executor.py", "platform/gates/tests_recipe_enforcer.py",
        ]),
    ]
    for label, command in commands:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        tail = (completed.stdout + completed.stderr).splitlines()[-1:]
        check(f"V6 {label} verde", completed.returncode == 0, tail)

    print(f"=== {PASSED} passed, {FAILED} failed ===")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
