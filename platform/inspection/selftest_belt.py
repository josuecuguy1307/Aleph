#!/usr/bin/env python3
"""
selftest_belt.py — DELIVERABLE de FASE 4: la tool sintetizada, EQUIPABLE de verdad.

Recon → synthesize_tool → synthesize_belt (belt .mcp.json + spec). Después prueba que
es una capability real usando el CLIENTE REAL del assembler (MCPServer): lanza el
synth server, hace initialize/tools/list/tools/call — igual que cuando el agente la
equipa. Y confirma que belt_resolver la resuelve/cablea.

GATE (guard): el server arranca en DRY-RUN por defecto; la ejecución real del write
exige SYNTH_EXECUTE=1 + SYNTH_ALLOW_WRITE=1 en el env del belt (= la aprobación humana
en prod). Acá se ejecuta sólo contra el target BENIGNO que controlamos.

Uso:  python platform/inspection/selftest_belt.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

_PLATFORM_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DIR))
sys.path.insert(0, str(_REPO_ROOT / "platform" / "assembler"))   # belt_resolver bare import

from inspection.fixtures.demos.attendance import demo as attendance_demo
from inspection.fixtures.test_app import BenignTestApp
from inspection.observe.correlate import correlate
from inspection.observe.emit_belt import synthesize_belt
from inspection.observe.recorder import record_demonstration
from inspection.observe.synthesize import synthesize_tool
from inspection.session.cloud import CloudSession

_OUT = _PLATFORM_DIR / "inspection" / ".state" / "synth-belt"
NEW_ARGS = {"alumno": "Carlos Líder", "codigo": "C-9090"}   # valores nuevos otra vez


def _load_mcpserver_cls():
    p = _REPO_ROOT / "platform" / "assembler" / "assembler.py"
    spec = importlib.util.spec_from_file_location("puppet_assembler_base_belt", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MCPServer


def _call_via_client(MCPServer, server_name, cfg, env_extra, tool_name, args):
    """Lanza el synth server con el cliente REAL del assembler y llama la tool."""
    env = dict(os.environ)
    env.update(cfg.get("env", {}))
    env.update(env_extra or {})
    srv = MCPServer(server_name, cfg["command"], cfg["args"], env=env)
    started = srv.start()
    tools = srv.list_tools() if started else []
    out_text = srv.call_tool(tool_name, args) if started else "(no start)"
    srv.stop()
    try:
        out = json.loads(out_text)
    except (json.JSONDecodeError, TypeError):
        out = {"raw": out_text}
    return started, tools, out


async def _recon_spec():
    with BenignTestApp() as app:
        base = app.base_url
        session = CloudSession(headless=True)
        ctx = await session.provide_context()
        try:
            bundle = await record_demonstration(
                ctx, intent="registrar asistencia", target_url=base,
                demo=attendance_demo, settle_ms=2200,
            )
            action = correlate(bundle)
        finally:
            await ctx.aclose()
        spec = synthesize_tool(action)
        # el server se prueba con el fixture VIVO → todo dentro del with
        return spec, _drive(spec)


def _drive(spec):
    MCPServer = _load_mcpserver_cls()
    art = synthesize_belt(spec, out_dir=_OUT)
    cfg = art["belt"]["mcpServers"][art["server_name"]]
    tool_name = art["tool_name"]

    # 1) DRY-RUN (server sin flags de ejecución) — vía el cliente real
    started_d, tools_d, dry = _call_via_client(MCPServer, art["server_name"], cfg, {}, tool_name, NEW_ARGS)
    # 2) EJECUCIÓN GATEADA (SYNTH_EXECUTE + SYNTH_ALLOW_WRITE) contra el fixture benigno
    started_x, _, real = _call_via_client(
        MCPServer, art["server_name"], cfg,
        {"SYNTH_EXECUTE": "1", "SYNTH_ALLOW_WRITE": "1"}, tool_name, NEW_ARGS)
    # 3) belt_resolver: ¿se resuelve/cablea?
    import belt_resolver
    resolved = belt_resolver.resolve_belt_ref(str(art["belt_path"]), _REPO_ROOT)

    return {"art": art, "tool_name": tool_name, "started_d": started_d, "tools_d": tools_d,
            "dry": dry, "started_x": started_x, "real": real,
            "resolved_servers": resolved.servers}


def main() -> int:
    spec, r = asyncio.run(_recon_spec())

    print("\n========== BELT SINTETIZADO ==========")
    print("belt:", r["art"]["belt_path"])
    print("spec:", r["art"]["spec_path"])
    print("server:", json.dumps(r["art"]["belt"]["mcpServers"][r["art"]["server_name"]], ensure_ascii=False))

    print("\n========== VÍA EL CLIENTE REAL DEL ASSEMBLER ==========")
    print("initialize ok:", r["started_d"])
    print("tools/list:", [t.get("name") for t in r["tools_d"]])
    print("dry-run body:", (r["dry"].get("request") or {}).get("body"))
    resp = r["real"].get("response", {})
    print("gated exec → status:", resp.get("status"), "echo:", (resp.get("json") or {}).get("echo"))
    print("belt_resolver servers:", r["resolved_servers"])

    print("\n========== VERIFY ==========")
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    tool_name = r["tool_name"]
    check("el assembler HIZO initialize con el synth server", r["started_d"] is True)
    check("tools/list expone la tool sintetizada", tool_name in [t.get("name") for t in r["tools_d"]])
    check("la tool trae inputSchema con alumno+codigo",
          set((next((t for t in r["tools_d"] if t.get("name") == tool_name), {}).get("inputSchema", {})
               .get("required", []))) == {"alumno", "codigo"})
    db = (r["dry"].get("request") or {}).get("body") or {}
    check("DRY-RUN por defecto (no ejecutó) e inyectó valores nuevos",
          r["dry"].get("dry_run") is True and db.get("alumno") == "Carlos Líder" and db.get("codigo") == "C-9090")
    check("EJECUCIÓN GATEADA: el fixture respondió 200", resp.get("status") == 200)
    echo = (resp.get("json") or {}).get("echo") or {}
    check("el fixture recibió los valores nuevos (tool real end-to-end)",
          echo.get("alumno") == "Carlos Líder" and echo.get("codigo") == "C-9090")
    check("belt_resolver resuelve y cablea el server sintetizado",
          r["art"]["server_name"] in (r["resolved_servers"] or []))

    print(f"\n[belt] {'OK ✅' if ok else 'FALLÓ ❌'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
