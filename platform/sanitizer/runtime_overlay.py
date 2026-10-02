#!/usr/bin/env python3
"""
runtime_overlay.py — Additive wiring of FormulaGuard onto the agent write path.

NON-INVASIVE BY CONTRACT
------------------------
This module does NOT import or modify assembler.py. It exposes:

  • guard_tool_arguments(tool_name, arguments, guard, *, write_tools) -> (new_args, events)
        Pure function. Given a tool call about to be dispatched, returns a NEW
        arguments dict with every cell-bearing field run through the guard.
        Untouched if the tool is not a known write tool.

  • install(registry, *, guard=None, write_tools=None)
        Monkeypatch-free* wrapper: wraps `registry.call` so every dispatched tool
        call passes through `guard_tool_arguments` first. Works on the assembler's
        ToolRegistry AND the run_once _RecordingRegistry (subclass) without either
        knowing this module exists. Returns the registry for chaining.
        (*it rebinds one bound method on the instance, not the class — additive,
         reversible, and scoped to the instance the caller owns.)

WHY AT THE REGISTRY BOUNDARY
----------------------------
assembler.ToolRegistry.call(tool_name, arguments) is the single chokepoint every
tool dispatch flows through (both assembler.run_agent and run_once._run_loop call
it). Intercepting here means ONE generic interceptor covers every template that
writes files — exactly the "pieza del runtime, no parche por template" the mission
requires. No per-template code, no assembler edit.

WRITE-TOOL FIELD MAP
--------------------
Which argument of which tool carries user-/model-authored cell values:

  apply_formula(filepath, sheet_name, cell, formula)          → scalar field "formula"
  write_data_to_excel(filepath, sheet_name, data, start_cell) → grid field "data"
  update_cells / batch_update_cells (Sheets)                  → grid field, common keys
  add_rows (Sheets)                                           → grid field

The map is data, not code — extend it for any new write tool / vertical.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

try:
    # normal package-style import
    from .formula_guard import FormulaGuard, FINANZAS_TEMPLATE_FUNCTIONS
except ImportError:  # pragma: no cover — loaded by file path (no package)
    from formula_guard import FormulaGuard, FINANZAS_TEMPLATE_FUNCTIONS  # type: ignore


# tool_name -> {"scalar": [arg names], "grid": [arg names]}
# scalar = a single formula string; grid = a List[List] of cell values.
DEFAULT_WRITE_TOOLS: dict[str, dict[str, list]] = {
    # excel-mcp-server
    "apply_formula": {"scalar": ["formula"], "grid": []},
    "write_data_to_excel": {"scalar": [], "grid": ["data"]},
    # mcp-google-sheets (Sheets live writes — same class of payload, T05)
    "update_cells": {"scalar": [], "grid": ["data", "values"]},
    "batch_update_cells": {"scalar": [], "grid": ["data", "values"]},
    "add_rows": {"scalar": [], "grid": ["data", "values", "rows"]},
}


def default_guard(on_event: Optional[Callable[[dict], None]] = None,
                  policy: str = "prefix") -> FormulaGuard:
    """A guard preloaded with the finanzas template whitelist (the P010 instance)."""
    return FormulaGuard(
        policy=policy,
        allowed_functions=FINANZAS_TEMPLATE_FUNCTIONS,
        on_event=on_event,
    )


def guard_tool_arguments(
    tool_name: str,
    arguments: dict,
    guard: FormulaGuard,
    *,
    write_tools: Optional[dict] = None,
) -> tuple[dict, list]:
    """
    Return (sanitized_arguments, events). If `tool_name` is not a known write tool,
    returns the arguments unchanged (identity) and an empty event list.

    Trust posture: values arriving as tool-call arguments are the model's output,
    which may carry ingested untrusted text → inspected as trusted=False. Legitimate
    template formulas survive via the whitelist (shape-based), not via a trust flag —
    that is what keeps SUMIFS/variance alive (control-positive, lesson M002).
    """
    spec = (write_tools or DEFAULT_WRITE_TOOLS).get(tool_name)
    if not spec or not isinstance(arguments, dict):
        return arguments, []

    events: list = []
    sink = guard.on_event
    # temporarily tee events into our local list too
    def _tee(ev: dict):
        events.append(ev)
        if sink:
            sink(ev)

    local_guard = FormulaGuard(
        policy=guard.policy,
        allowed_functions=guard.allowed_functions,
        on_event=_tee,
    )

    new_args = dict(arguments)

    for fld in spec.get("scalar", []):
        if fld in new_args:
            d = local_guard.inspect(new_args[fld], trusted=False, where=f"{tool_name}.{fld}")
            new_args[fld] = d.sanitized

    for fld in spec.get("grid", []):
        if fld in new_args:
            new_args[fld] = local_guard.sanitize_grid(
                new_args[fld], trusted=False, where=f"{tool_name}.{fld}"
            )

    return new_args, events


def install(
    registry,
    *,
    guard: Optional[FormulaGuard] = None,
    write_tools: Optional[dict] = None,
):
    """
    Wrap `registry.call` so every dispatched tool call is sanitized first.

    Additive: rebinds ONE bound method on the instance the caller passes in. The
    original method is preserved and re-invoked, so subclass behavior (e.g.
    run_once's _RecordingRegistry, which records calls) is fully retained — the
    sanitized arguments are what get recorded and dispatched, which is correct.
    """
    g = guard or default_guard()
    original_call = registry.call  # bound method

    def guarded_call(tool_name: str, arguments: dict) -> str:
        new_args, _events = guard_tool_arguments(
            tool_name, arguments, g, write_tools=write_tools
        )
        return original_call(tool_name, new_args)

    registry.call = guarded_call  # type: ignore[assignment]
    registry._formula_guard = g   # handle for tests / introspection
    return registry
