#!/usr/bin/env python3
"""
verify_medicina_segmentacion.py — verificación REAL del visor + segmentación (1C-1).

  L1 · DATO REAL (runtime MCPServer) sobre el volumen CT de Orthanc
      windowing (3 presets → la imagen cambia), extract_slice (3 planos), segment_structure
      (pulmón + hueso → máscara con voxels/volumen). Todo medido del CT real.

  L2 · CAPACIDAD POR OPUS (assemble_and_run + brain shim :8923)
      El puppet de medicina llama las tools (mini-flujo: corte axial preset pulmón + segmentar
      pulmón) y produce los resultados. model_final=claude-code-opus-4.8 / degraded=null.

  BADGE READ-ONLY · legal_precheck(medicina) → require_human + aviso HIPAA dev/test + el belt
      declara read_only=true. (No es loop de convergencia: es CAPACIDAD.)

  L3 · IMAGEN capturada — _capture_rich_obra surfacea segmentation.imagen.json (overlay).

Uso:  product/backend/.venv/bin/python platform/assembler/verify_medicina_segmentacion.py
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


def _mk_server(workdir):
    belt = json.loads(_BELT.read_text(encoding="utf-8"))
    scfg = belt["mcpServers"]["segmentacion"]
    env = dict(os.environ)
    env["PUPPET_WORKDIR"] = workdir
    env["PUPPET_BELTS"] = str(_REPO / "product" / "belts")
    command = scfg["command"]
    args = [a.replace("${PUPPET_BELTS}", env["PUPPET_BELTS"]) for a in scfg.get("args", [])]
    return MCPServer("segmentacion", command, args, env=env)


# ════════════════════════════════════════════════════════════════════════════
def level1_real():
    print("\n=== L1 · DATO REAL del CT (runtime MCPServer, Orthanc) ===")
    workdir = tempfile.mkdtemp(prefix="verify-med-")
    srv = _mk_server(workdir)
    if not srv.start():
        check("M1 initialize handshake", False, "el server segmentacion no inicializó")
        return
    check("M1 initialize handshake", True)
    tools = [t.get("name") for t in srv.list_tools()]
    check("M2 tools/list expone windowing + extract_slice + segment_structure",
          {"windowing", "extract_slice", "segment_structure"}.issubset(set(tools)), f"tools={tools}")

    print("\n  ── WINDOWING (la misma imagen cambia entre presets) ──")
    means = {}
    for preset in ("lung", "bone", "mediastinum"):
        d = json.loads(srv.call_tool("windowing", {"preset": preset}))
        means[preset] = d.get("windowed_mean")
        print(f"     {preset:12} WL{d.get('window_level')}/WW{d.get('window_width')} → "
              f"mean={d.get('windowed_mean')} blanco%={d.get('saturated_white_pct')} negro%={d.get('saturated_black_pct')}")
    distinct = len(set(round(v, 1) for v in means.values() if v is not None)) == 3
    check("M3 windowing cambia entre presets (3 medias distintas)", distinct, str(means))

    print("\n  ── 3 PLANOS (reslice del volumen) ──")
    planes_ok = True
    for plane in ("axial", "coronal", "sagittal"):
        d = json.loads(srv.call_tool("extract_slice", {"plane": plane}))
        print(f"     {plane:9} #{d.get('index')} voxel_dims={d.get('voxel_dims')} "
              f"mm={d.get('mm_extent')} HU[{d.get('hu_min')},{d.get('hu_max')}]")
        planes_ok = planes_ok and d.get("ok") and d.get("voxel_dims")
    check("M4 extrae los 3 planos (axial/coronal/sagittal)", planes_ok)

    print("\n  ── SEGMENTACIÓN (máscara real, voxels/volumen) ──")
    seg = {}
    for st in ("lung", "bone"):
        d = json.loads(srv.call_tool("segment_structure", {"structure": st, "plane": "axial"}))
        seg[st] = d
        print(f"     {st:5} HU{d.get('hu_threshold')} → voxels={d.get('mask_voxels')} "
              f"volumen={d.get('segmented_volume_ml')} mL  área_corte={d.get('slice_mask_area_mm2')} mm²")
    lung = seg.get("lung", {})
    check("M5 segmenta pulmón → máscara con volumen plausible (3–8 L)",
          lung.get("ok") and 3000 <= (lung.get("segmented_volume_ml") or 0) <= 8000,
          f"{lung.get('segmented_volume_ml')} mL, {lung.get('mask_voxels')} voxels")
    bone = seg.get("bone", {})
    check("M6 segmenta hueso → máscara con voxels reales",
          bone.get("ok") and (bone.get("mask_voxels") or 0) > 50000,
          f"{bone.get('segmented_volume_ml')} mL, {bone.get('mask_voxels')} voxels")
    check("M7 las tools se declaran READ-ONLY",
          all(seg[s].get("read_only") for s in seg), "read_only=True en cada resultado")
    # patient/study provenance (de-prueba, no real)
    srv.stop()


# ════════════════════════════════════════════════════════════════════════════
def _recipe():
    return {
        "schema_version": "v1",
        "meta": {"name": "Agente de Medicina", "nicho": "medicina",
                 "descripcion": "Visor radiológico READ-ONLY: windowing, cortes y segmentación (dev/test)."},
        "belt": {
            "belt_ref": "catalog/templates/medicina/belt-medicina.mcp.json",
            "tool_filters": {"segmentacion": ["windowing", "extract_slice", "segment_structure"]},
        },
        "keys": {},
        "gates": {"send": "needs_ok", "money_touch": "needs_ok"},
        "model": {"alias": "brain", "max_turns": 12, "max_tokens": 2200, "temperature": 0},
        "framing": {"inline": _FRAMING.read_text(encoding="utf-8")},
        "rag": {"enabled": False},
    }


PROMPT = ("Sobre el CT de tórax: mostrá el corte axial con la ventana de PULMÓN y segmentá el "
          "PULMÓN, decime el volumen pulmonar medido en mL. Después extraé un corte CORONAL "
          "para ver la anatomía. Aclarame que es dev/test, no diagnóstico.")


def level2_opus():
    print("\n=== L2 · CAPACIDAD POR OPUS (assemble_and_run + brain shim :8923) ===")
    workdir = tempfile.mkdtemp(prefix="verify-med-e2e-")
    rec = ra.assemble_and_run(_recipe(), PROMPT, repo_root=_REPO, deadline_s=300.0, workdir=workdir)
    model_final = rec.get("model_final")
    degraded = rec.get("degraded")
    tool_calls = rec.get("tool_calls", []) or []
    names = [c.get("tool") for c in tool_calls]
    print(f"\n  model_final = {model_final}")
    print(f"  degraded    = {degraded}")
    print(f"  tool_calls  = {names}")
    seg_call = next((c for c in tool_calls if c.get("tool") == "segment_structure"), None)
    if seg_call:
        res = seg_call.get("result", "")
        try:
            rj = json.loads(res) if isinstance(res, str) else res
            print(f"\n  ── tool_call segment_structure (Opus) ──\n     structure={rj.get('structure')} "
                  f"volumen={rj.get('segmented_volume_ml')} mL voxels={rj.get('mask_voxels')}")
        except Exception:
            print("  segment_structure result:", str(res)[:200])
    print("\n  ── RESPUESTA del agente ──")
    print("   " + (rec.get("answer", "") or "").replace("\n", "\n   ")[:1300])

    check("E1 el run terminó OK", rec.get("ok"), rec.get("error") or "")
    check("E2 Opus usó las tools del visor (windowing/extract_slice/segment_structure)",
          any(n in ("windowing", "extract_slice", "segment_structure") for n in names), str(names))
    check("E3 Opus segmentó (segment_structure ejecutada)", seg_call is not None, str(names))
    check("E4 model_final = claude-code-opus-4.8", model_final == "claude-code-opus-4.8", str(model_final))
    check("E5 degraded = null (Opus real, sin fallback)", degraded is None, str(degraded))
    return workdir


# ════════════════════════════════════════════════════════════════════════════
def badge_readonly():
    print("\n=== BADGE READ-ONLY (legal-gate medicina + belt) ===")
    sys.path.insert(0, str(_REPO / "platform"))
    from safety.guards import legal_precheck
    pol = legal_precheck(_recipe(), env="dev")
    print(f"   legal: allow={pol.get('allow')} require_human={pol.get('require_human')} basis={pol.get('basis')}")
    print(f"   notice: {pol.get('notice')}")
    notice = (pol.get("notice") or "").lower()
    check("B1 legal-gate medicina: require_human + aviso HIPAA dev/test",
          pol.get("require_human") and ("hipaa" in notice or "dev/test" in notice or "sint" in notice),
          pol.get("basis"))
    belt = json.loads(_BELT.read_text(encoding="utf-8"))
    ro = belt["_meta"].get("read_only") and belt["mcpServers"]["segmentacion"].get("read_only")
    check("B2 el belt declara READ-ONLY (badge)", bool(ro), f"badge='{belt['_meta'].get('badge')}'")


def level3_capture(workdir):
    print("\n=== L3 · IMAGEN capturada por el executor (La Sala la rinde) ===")
    if not workdir:
        check("C1 _capture_rich_obra → imagen", False, "no hubo workdir del L2")
        return
    sys.path.insert(0, str(_REPO / "product" / "backend"))
    from app.phase1.executor import _capture_rich_obra
    obra = _capture_rich_obra(workdir)
    ok = bool(obra and obra.get("type") == "imagen" and isinstance(obra.get("content"), str)
              and obra["content"].startswith("data:image/png;base64,"))
    check("C1 _capture_rich_obra → obra imagen (overlay de segmentación)", ok,
          f"type={obra.get('type') if obra else None} title={obra.get('title') if obra else None}")


def main():
    level1_real()
    badge_readonly()
    wd = level2_opus()
    level3_capture(wd)
    passed = sum(1 for ok, _, _ in _results if ok)
    total = len(_results)
    print(f"\n=== RESULTADO: {passed}/{total} VERDE ===")
    if passed != total:
        print("ROJO en:", [lbl for ok, lbl, _ in _results if not ok])
        return 1
    print("Visor + segmentación de medicina verificado: CT real + Opus + READ-ONLY + imagen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
