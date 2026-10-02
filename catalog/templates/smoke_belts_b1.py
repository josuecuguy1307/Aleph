#!/usr/bin/env python3
"""
smoke_belts_b1.py — PRUEBA REAL de los belts B1 de nicho (stem/research/programacion/cowork).

Para cada belt:
  1. resuelve el belt_ref de la receta via platform/assembler/belt_resolver.resolve_belt_ref
  2. arranca los servers KEYLESS del .mcp.json y verifica init (JSON-RPC) + tools/list
  3. exige que AL MENOS UN server arranque (criterio de la misión)

Los servers BYOK/OAuth (exa/huggingface/context7/github/google_*/slack) se SALTAN a
proposito: requieren credencial del usuario (guardrail #6). Se listan como skipped, no
como fallo. Sin false-green: si ningun keyless arranca, el belt FALLA.

Usa el harness del squad (product/belts/client/mcp_client.py); NO toca el assembler salvo
el resolver puro (belt_resolver), que es funcion sin side-effects.
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "platform" / "assembler"))
sys.path.insert(0, str(REPO / "product" / "belts" / "client"))

from belt_resolver import resolve_belt_ref          # noqa: E402
import mcp_client                                     # noqa: E402

# servers que requieren credencial del usuario (BYOK/OAuth) -> se saltan, no fallan
KEYED = {"exa", "huggingface", "context7", "github",
         "google_drive", "google_calendar", "gmail", "slack"}

# belt_ref tal como aparece en cada receta de product/recipes/*.config.json
BELTS = {
    "stem (educacion)":      "catalog/belts/stem.md",
    "research":              "catalog/belts/research.md",
    "programacion":          "catalog/belts/programacion.md",
    "cowork":                "catalog/belts/cowork.md",
}


def smoke_one(label: str, belt_ref: str, workdir: str) -> bool:
    print(f"\n========== {label}  (belt_ref={belt_ref}) ==========")
    resolved = resolve_belt_ref(belt_ref, REPO)
    print(f"[RESOLVER] -> {resolved.mcp_json_path}")
    print(f"[RESOLVER] servers declarados: {resolved.servers}")

    os.environ["PUPPET_WORKDIR"] = workdir
    os.environ["PUPPET_BELTS"] = str(REPO / "product" / "belts")
    servers = mcp_client.load_belt(str(resolved.mcp_json_path))

    started, skipped = [], []
    procs = []
    for name, scfg in servers.items():
        if name in KEYED and not _has_creds(scfg):
            skipped.append(name)
            continue
        srv = mcp_client.MCPServer(name, scfg["command"], scfg.get("args", []), scfg.get("env"))
        if srv.start():
            tools = [t["name"] for t in srv.list_tools()]
            print(f"[OK]   {name}: INIT + tools/list -> {len(tools)} tools (muestra: {tools[:6]})")
            started.append(name)
            procs.append(srv)
        else:
            print(f"[FAIL] {name}: no arranco")
    for p in procs:
        p.stop()
    if skipped:
        print(f"[SKIP] keyed/BYOK (sin credencial, no falla): {skipped}")
    ok = len(started) >= 1
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {len(started)} server(s) arrancaron -> {started}")
    return ok


def _has_creds(scfg: dict) -> bool:
    """True solo si todas las ${VAR} de env estan presentes en el entorno."""
    env = scfg.get("env", {}) or {}
    for v in env.values():
        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            if not os.environ.get(v[2:-1]):
                return False
    return bool(env)


def main() -> int:
    results = {}
    with tempfile.TemporaryDirectory(prefix="puppet_belt_smoke_") as wd:
        for label, ref in BELTS.items():
            try:
                results[label] = smoke_one(label, ref, wd)
            except Exception as e:                    # noqa: BLE001
                print(f"[FAIL] {label}: excepcion {e!r}")
                results[label] = False
    print("\n================ RESUMEN ================")
    for label, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    allok = all(results.values())
    print(f"\n{'ALL PASS' if allok else 'FALLOS PRESENTES'}")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
