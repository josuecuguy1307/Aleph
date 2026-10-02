#!/usr/bin/env python3
"""
selftest_synth.py — DELIVERABLE de FASE 3: la demostración → una TOOL MCP que FUNCIONA.

Corre el recon contra el target benigno, sintetiza una tool MCP real (name +
inputSchema + template de request) y la LLAMA con valores NUEVOS:
  1) DRY-RUN: arma la request con los params nuevos, sin mandarla (siempre seguro).
  2) GATE: una tool write con execute=True pero sin allow_write → REHUSADA.
  3) EJECUCIÓN GATEADA: execute=True + allow_write=True contra el fixture benigno →
     el server recibe los valores NUEVOS (los devuelve en echo) → la tool es real
     y parametrizable. (En prod, allow_write = el gate human-in-the-loop por Telegram.)

verify-from-environment: chequea la request construida y la respuesta REAL del server.
Uso:  python platform/inspection/selftest_synth.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))

from inspection.fixtures.demos.attendance import demo as attendance_demo
from inspection.fixtures.test_app import BenignTestApp
from inspection.observe.correlate import correlate
from inspection.observe.recorder import record_demonstration
from inspection.observe.replay import SynthesizedTool
from inspection.observe.synthesize import synthesize_tool
from inspection.session.cloud import CloudSession

# valores NUEVOS, distintos a los de la demostración (persona usuaria Arcos / A-7731)
NEW_ARGS = {"alumno": "María Pérez", "codigo": "B-1234"}


async def _run() -> int:
    with BenignTestApp() as app:
        print(f"[synth] target benigno {app.base_url}")
        session = CloudSession(headless=True)
        ctx = await session.provide_context()
        try:
            bundle = await record_demonstration(
                ctx, intent="registrar asistencia", target_url=app.base_url,
                demo=attendance_demo, settle_ms=2200,
            )
            action = correlate(bundle)
        finally:
            await ctx.aclose()

        spec = synthesize_tool(action)
        tool = SynthesizedTool(spec)

        print("\n========== TOOL MCP SINTETIZADA ==========")
        print(json.dumps(spec["mcp_tool"], indent=2, ensure_ascii=False))
        print("request template:", json.dumps(spec["request"], ensure_ascii=False, default=str))

        dry = tool.call(NEW_ARGS, execute=False)
        refused = tool.call(NEW_ARGS, execute=True, allow_write=False)
        real = tool.call(NEW_ARGS, execute=True, allow_write=True)   # gate explícito (fixture benigno)

        print("\n========== LLAMADAS ==========")
        print("dry-run request:", json.dumps(dry["request"], ensure_ascii=False, default=str))
        print("gate (sin allow_write):", refused.get("refused"), "·", refused.get("reason"))
        print("ejecución real → status:", real.get("response", {}).get("status"),
              "echo:", (real.get("response", {}).get("json") or {}).get("echo"))

    # ── verify-before-trust ──
    print("\n========== VERIFY ==========")
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    schema = spec["mcp_tool"]["inputSchema"]
    check("la tool MCP expone alumno+codigo como params requeridos",
          set(schema.get("required", [])) == {"alumno", "codigo"})
    db = dry["request"]["body"]
    check("dry-run: inyectó los valores NUEVOS en el body", db.get("alumno") == "María Pérez" and db.get("codigo") == "B-1234")
    check("dry-run: preservó la constante curso=FIS-101", db.get("curso") == "FIS-101")
    check("dry-run: método/url correctos", dry["request"]["method"] == "POST" and dry["request"]["url"].endswith("/api/attendance"))
    check("GATE: write con execute pero sin allow_write fue REHUSADO", refused.get("refused") is True)
    resp = real.get("response", {})
    echo = (resp.get("json") or {}).get("echo") or {}
    check("ejecución gateada: el server respondió 200", resp.get("status") == 200)
    check("ejecución gateada: el server recibió los valores NUEVOS (parametrización real)",
          echo.get("alumno") == "María Pérez" and echo.get("codigo") == "B-1234")

    print(f"\n[synth] {'OK ✅' if ok else 'FALLÓ ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
