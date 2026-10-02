#!/usr/bin/env python3
"""
verify_medicina_volumen3d.py — verificación del VOLUMEN 3D rotable (1C-2).

  L1 · MESH REAL (runtime MCPServer) — render_volume_3d genera un mesh por marching cubes
      sobre la máscara real del CT de Orthanc (no un modelo prefab). Pegamos estructura,
      triángulos, vértices.
  L2 · POR OPUS (assemble_and_run + brain shim :8923) — el puppet de medicina produce el
      artifact volume3d (tool_call render_volume_3d). model_final=claude-code-opus-4.8 / null.
  BADGE READ-ONLY · legal_precheck(medicina) + belt read_only.
  CAPTURA · _capture_rich_obra surfacea *.volume3d.json → La Sala lo rinde rotable.

(La rotación fluida y la regresión 10/10 se verifican con node: rotate_proof + verify.mjs.)

Uso:  product/backend/.venv/bin/python platform/assembler/verify_medicina_volumen3d.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
os.environ["PUPPET_BRAIN_SHIM"] = "1"
os.environ["PUPPET_BRAIN_SHIM_MODEL"] = "claude-code-opus-4.8"
os.environ.setdefault("PUPPET_BELTS", str(_REPO / "product" / "belts"))

sys.path.insert(0, str(_HERE))
from assembler import MCPServer                      # noqa: E402
import recipe_assembler as ra                        # noqa: E402

_BELT = _REPO / "catalog" / "templates" / "medicina" / "belt-medicina.mcp.json"
_FRAMING = _REPO / "catalog" / "templates" / "medicina" / "framing-medicina-visor.md"
_results = []


def check(label, cond, detail=""):
    _results.append((bool(cond), label, detail))
    print(f"  [{'VERDE' if cond else 'ROJO '}] {label}" + (f" — {detail}" if detail else ""))


def level1_real_mesh():
    print("\n=== L1 · MESH REAL (runtime MCPServer, marching cubes sobre el CT de Orthanc) ===")
    workdir = tempfile.mkdtemp(prefix="verify-vol3d-")
    belt = json.loads(_BELT.read_text(encoding="utf-8"))
    scfg = belt["mcpServers"]["segmentacion"]
    env = dict(os.environ); env["PUPPET_WORKDIR"] = workdir
    env["PUPPET_BELTS"] = str(_REPO / "product" / "belts")
    args = [a.replace("${PUPPET_BELTS}", env["PUPPET_BELTS"]) for a in scfg.get("args", [])]
    srv = MCPServer("segmentacion", scfg["command"], args, env=env)
    if not srv.start():
        check("V1 initialize handshake", False, "el server no inicializó"); return
    check("V1 initialize handshake", True)
    tools = [t.get("name") for t in srv.list_tools()]
    check("V2 tools/list expone render_volume_3d", "render_volume_3d" in tools, f"tools={tools}")

    for st in ("bone", "lung"):
        d = json.loads(srv.call_tool("render_volume_3d", {"structure": st}))
        print(f"   {st:5} → triángulos={d.get('n_triangles')} vértices={d.get('n_vertices')} "
              f"voxels={d.get('mask_voxels')} vol={d.get('segmented_volume_ml')}mL fuente={d.get('note','')[:48]}…")
        if st == "bone":
            real = (d.get("ok") and (d.get("n_triangles") or 0) > 5000 and (d.get("mask_voxels") or 0) > 50000)
            check("V3 render_volume_3d(bone) → mesh REAL del CT (>5k triángulos)", real,
                  f"{d.get('n_triangles')} triángulos de {d.get('mask_voxels')} voxels")
        # artifact volume3d escrito
    art = Path(workdir) / "volume.volume3d.json"
    ok = False
    if art.exists():
        a = json.loads(art.read_text())
        ok = (a.get("type") == "volume3d" and a.get("vertices_b64") and a.get("faces_b64"))
    check("V4 escribe artifact volume3d (vertices_b64 + faces_b64)", ok)
    check("V5 read-only declarado", json.loads(srv.call_tool("render_volume_3d", {"structure": "bone"})).get("read_only") is True)
    srv.stop()


def _recipe():
    return {
        "schema_version": "v1",
        "meta": {"name": "Agente de Medicina", "nicho": "medicina",
                 "descripcion": "Visor radiológico READ-ONLY + volumen 3D (dev/test)."},
        "belt": {"belt_ref": "catalog/templates/medicina/belt-medicina.mcp.json",
                 "tool_filters": {"segmentacion": ["windowing", "extract_slice", "segment_structure", "render_volume_3d"]}},
        "keys": {}, "gates": {"send": "needs_ok", "money_touch": "needs_ok"},
        "model": {"alias": "brain", "max_turns": 10, "max_tokens": 1800, "temperature": 0},
        "framing": {"inline": _FRAMING.read_text(encoding="utf-8")},
        "rag": {"enabled": False},
    }


PROMPT = ("Generá el VOLUMEN 3D rotable del HUESO (caja torácica) del CT de tórax para verlo en 3D, "
          "y decime cuántos triángulos tiene el mesh. Aclarame que es dev/test, no diagnóstico.")


def level2_opus():
    print("\n=== L2 · POR OPUS (assemble_and_run + brain shim :8923) ===")
    workdir = tempfile.mkdtemp(prefix="verify-vol3d-e2e-")
    rec = ra.assemble_and_run(_recipe(), PROMPT, repo_root=_REPO, deadline_s=300.0, workdir=workdir)
    mf, deg = rec.get("model_final"), rec.get("degraded")
    names = [c.get("tool") for c in (rec.get("tool_calls") or [])]
    v3 = next((c for c in (rec.get("tool_calls") or []) if c.get("tool") == "render_volume_3d"), None)
    print(f"\n  model_final = {mf}\n  degraded    = {deg}\n  tool_calls  = {names}")
    if v3:
        try:
            rj = json.loads(v3.get("result")) if isinstance(v3.get("result"), str) else v3.get("result")
            print(f"  ── render_volume_3d (Opus) ── structure={rj.get('structure')} triángulos={rj.get('n_triangles')}")
        except Exception:
            pass
    print("\n  ── RESPUESTA ──\n   " + (rec.get("answer", "") or "").replace("\n", "\n   ")[:1100])
    check("E1 run OK", rec.get("ok"), rec.get("error") or "")
    check("E2 Opus llamó render_volume_3d (produjo el volumen 3D)", v3 is not None, str(names))
    check("E3 model_final = claude-code-opus-4.8", mf == "claude-code-opus-4.8", str(mf))
    check("E4 degraded = null", deg is None, str(deg))
    # captura
    sys.path.insert(0, str(_REPO / "product" / "backend"))
    from app.phase1.executor import _capture_rich_obra
    obra = _capture_rich_obra(workdir)
    ok = bool(obra and obra.get("type") == "volume3d" and obra.get("vertices_b64") and obra.get("faces_b64"))
    check("E5 _capture_rich_obra → obra volume3d (La Sala la rinde rotable)", ok,
          f"type={obra.get('type') if obra else None} tris={obra.get('n_triangles') if obra else None}")


def badge():
    print("\n=== BADGE READ-ONLY ===")
    sys.path.insert(0, str(_REPO / "platform"))
    from safety.guards import legal_precheck
    pol = legal_precheck(_recipe(), env="dev")
    check("B1 legal-gate medicina: require_human + HIPAA dev/test", pol.get("require_human") and pol.get("notice"),
          pol.get("basis"))
    belt = json.loads(_BELT.read_text(encoding="utf-8"))
    check("B2 belt READ-ONLY (badge)", bool(belt["_meta"].get("read_only")), belt["_meta"].get("badge"))


def main():
    level1_real_mesh()
    badge()
    level2_opus()
    passed = sum(1 for ok, _, _ in _results if ok); total = len(_results)
    print(f"\n=== RESULTADO: {passed}/{total} VERDE ===")
    if passed != total:
        print("ROJO en:", [l for ok, l, _ in _results if not ok]); return 1
    print("Volumen 3D de medicina verificado: mesh real del CT + Opus + READ-ONLY + captura.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
