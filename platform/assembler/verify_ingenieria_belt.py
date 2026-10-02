#!/usr/bin/env python3
"""
verify_ingenieria_belt.py — verificación REAL del belt INGENIERIA por el runtime.

Arranca los servers del belt-ingenieria.mcp.json con el MISMO cliente MCP que usa
:8080 (platform/assembler/assembler.MCPServer: subprocess stdio + JSON-RPC 2.0) y
ejecuta tool-calls de verdad. Cero stub para FreeCAD: habla con la instancia local
viva (RPC 127.0.0.1:9875).

Checks:
  FREECAD
    F1  initialize handshake OK (el server bootea por el path de prod).
    F2  tools/list expone las tools curadas (create_object, execute_code, ...).
    F3  tools/call create_document → doc creado.
    F4  tools/call execute_code → box 10x20x30 con Volume=6000.0 mm3 (geometria REAL).
  GMAIL
    G1  initialize handshake OK.
    G2  tools/list expone create_draft (y send_email existe en el server, NO en la receta).
    G3  build != inject: SIN GMAIL_TOKEN, create_draft devuelve error honesto
        ('no hay credencial'), no un falso OK. (No toca ninguna cuenta real.)

Uso:
    python3 platform/assembler/verify_ingenieria_belt.py
Requiere para los checks F3/F4: FreeCAD abierto + workbench 'MCP Addon' + 'Start RPC Server'.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from assembler import MCPServer  # el MCPServer real del runtime

_REPO = _HERE.parent.parent
_BELT = _REPO / "catalog" / "templates" / "ingenieria" / "belt-ingenieria.mcp.json"


def _base_env() -> dict:
    """Replica el entorno del run: PUPPET_WORKDIR (temp real) + PUPPET_BELTS=product/belts
    (BELTS-ROOT unico, decision T7). NO inyectamos GMAIL_TOKEN a proposito (check G3)."""
    env = dict(os.environ)
    env["PUPPET_WORKDIR"] = tempfile.mkdtemp(prefix="verify-ing-")
    env["PUPPET_BELTS"] = str(_REPO / "product" / "belts")
    return env


def _expand(s: str, env: dict) -> str:
    out = s
    for k, v in env.items():
        out = out.replace("${" + k + "}", v)
    return out


def _mk_server(name: str, scfg: dict, base_env: dict) -> MCPServer:
    command = _expand(scfg.get("command", ""), base_env)
    args = [_expand(a, base_env) for a in (scfg.get("args", []) or [])]
    child_env = dict(base_env)
    for k, v in (scfg.get("env", {}) or {}).items():
        child_env[k] = _expand(v, base_env)
    return MCPServer(name, command, args, env=child_env)


def main() -> int:
    belt = json.loads(_BELT.read_text(encoding="utf-8"))
    servers = belt["mcpServers"]
    base_env = _base_env()
    results = []

    def check(label, cond, detail=""):
        results.append((bool(cond), label, detail))
        mark = "VERDE" if cond else "ROJO "
        print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))

    # ── FREECAD ──────────────────────────────────────────────────────────────
    print("\n=== FREECAD (puente local, RPC vivo) ===")
    fc = _mk_server("freecad", servers["freecad"], base_env)
    if not fc.start():
        check("F1 initialize handshake", False, "el server no inicializo (¿uvx freecad-mcp?)")
        _summary(results)
        return 2
    check("F1 initialize handshake", True)

    tools = [t.get("name") for t in fc.list_tools()]
    want = {"create_document", "create_object", "edit_object", "execute_code", "get_object"}
    check("F2 tools/list expone el set CAD", want.issubset(set(tools)),
          f"{len(tools)} tools; faltan={sorted(want - set(tools)) or 'ninguna'}")

    doc = fc.call_tool("create_document", {"name": "verify_ing"})
    check("F3 create_document", "verify_ing" in doc or "success" in doc.lower(), doc[:120])

    code = (
        "import FreeCAD\n"
        "doc = FreeCAD.getDocument('verify_ing')\n"
        "box = doc.addObject('Part::Box','VBox')\n"
        "box.Length=10.0; box.Width=20.0; box.Height=30.0\n"
        "doc.recompute()\n"
        "bb = box.Shape.BoundBox\n"
        "print('VOL=%.1f' % box.Shape.Volume)\n"
        "print('BBOX=%.1fx%.1fx%.1f' % (bb.XLength, bb.YLength, bb.ZLength))\n"
    )
    out = fc.call_tool("execute_code", {"code": code})
    geom_ok = ("VOL=6000.0" in out) and ("BBOX=10.0x20.0x30.0" in out)
    check("F4 execute_code → geometria REAL (Vol=6000 mm3)", geom_ok, out.replace("\n", " ")[:160])
    fc.stop()

    # ── GMAIL ────────────────────────────────────────────────────────────────
    print("\n=== GMAIL (borrador + send-gate; build != inject) ===")
    gm = _mk_server("gmail", servers["gmail"], base_env)
    if not gm.start():
        check("G1 initialize handshake", False, "el server gmail no inicializo")
    else:
        check("G1 initialize handshake", True)
        gtools = [t.get("name") for t in gm.list_tools()]
        check("G2 tools/list expone create_draft", "create_draft" in gtools, f"tools={gtools}")
        # G3: sin GMAIL_TOKEN, create_draft NO debe fingir exito. Espera error honesto.
        draft = gm.call_tool("create_draft", {"to": "a@b.com", "subject": "verify", "body": "x"})
        honest = ("credencial" in draft.lower()) or ("[tool error]" in draft.lower())
        check("G3 build!=inject (sin token → error honesto, no green)", honest, draft[:160])
        gm.stop()

    return _summary(results)


def _summary(results) -> int:
    passed = sum(1 for ok, _, _ in results if ok)
    total = len(results)
    print(f"\n=== RESULTADO: {passed}/{total} VERDE ===")
    if passed != total:
        print("ROJO en:", [lbl for ok, lbl, _ in results if not ok])
        return 1
    print("Belt ingenieria verificado por el runtime real (assembler.MCPServer).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
