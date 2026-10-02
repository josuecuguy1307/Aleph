#!/usr/bin/env python3
"""Vara mutante del colapso de inventario textual en el borde."""
from __future__ import annotations

import copy
import sys
from pathlib import Path


ASSEMBLER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ASSEMBLER))

from cli_brain.tool_inventory_dedup import (  # noqa: E402
    _render_vibetrading_inventory,
    colapsar_inventario_textual,
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a workspace file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "financial_rigor",
            "description": "Audit every reported number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Audit command"},
                    "values": {"type": "array"},
                },
                "required": ["command"],
            },
        },
    },
]


def messages(tools=TOOLS):
    inventory = _render_vibetrading_inventory(tools)
    return [{
        "role": "system",
        "content": (
            "finance contract\n\n## Tools\n\n"
            f"{inventory}\n\n## Skills (use load_skill to read full docs)\n\n"
            "keep narrating"
        ),
    }, {"role": "user", "content": "task"}]


def ok(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"OK  {label}")


original = messages()
collapsed, changed, removed = colapsar_inventario_textual(original, TOOLS)
ok(changed and removed > 0, "la copia exacta se colapsa")
ok("### read_file" not in collapsed[0]["content"], "desaparece el inventario textual")
ok("keep narrating" in collapsed[0]["content"], "el contrato narrativo sobrevive")
ok(original[0]["content"] != collapsed[0]["content"], "la entrada no se muta")
ok([t["function"]["name"] for t in TOOLS] == ["read_file", "financial_rigor"],
   "el conjunto estructurado conserva financial_rigor")

# Mutantes: cada diferencia tiene que dar rojo (no colapsar), no crashear.
for label, mutate in (
    ("nombre distinto", lambda ts: ts[0]["function"].__setitem__("name", "read_document")),
    ("descripción distinta", lambda ts: ts[0]["function"].__setitem__("description", "changed")),
    ("required distinto", lambda ts: ts[0]["function"]["parameters"].__setitem__("required", [])),
    ("orden distinto", lambda ts: ts.reverse()),
):
    altered = copy.deepcopy(TOOLS)
    mutate(altered)
    unchanged, did_change, chars = colapsar_inventario_textual(original, altered)
    ok(not did_change and chars == 0 and unchanged == original, f"fail-closed: {label}")

duplicated_marker = copy.deepcopy(original)
duplicated_marker[0]["content"] += "\n## Tools\n\nambiguo"
unchanged, did_change, _ = colapsar_inventario_textual(duplicated_marker, TOOLS)
ok(not did_change and unchanged == duplicated_marker, "fail-closed: delimitador ambiguo")

unchanged, did_change, _ = colapsar_inventario_textual(original, [])
ok(not did_change and unchanged is original, "sin schemas no se toca el system")

print("PASS — inventario textual sólo colapsa ante identidad byte a byte")
