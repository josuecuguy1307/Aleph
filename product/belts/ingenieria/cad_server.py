#!/usr/bin/env python3
"""
cad_server.py — MCP stdio server del belt de INGENIERIA: modelo CAD 3D REAL.

Tool `build_cad_model`: construye un soporte ("bracket") en L paramétrico con
freecadcmd headless y exporta una malla ASCII STL. Cero fabricación: la malla sale
de la geometría real de FreeCAD (tessellate), no de un prefab.

Por qué headless: el bridge GUI de freecad-mcp (RPC :9875) cuelga el event-loop en
ops pesadas; freecadcmd corre de forma determinística y aislada.

Vía de salida a La Sala: además del texto-resumen (lo que lee el cerebro: dimensiones,
triángulos, volumen), el server ESCRIBE `model.cad.json` (type=cad, content=STL) en
${PUPPET_WORKDIR}; el executor lo captura como obra `cad` y el frontend la rinde con el
renderer `cad` (malla 3D orbitable en three.js). El STL NO va al texto del cerebro (pesa).
"""
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE = os.path.join(_HERE, "cad_engine.py")
_FREECADCMD = os.environ.get(
    "FREECADCMD", "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"
)
_TIMEOUT = int(os.environ.get("CAD_TIMEOUT", "180"))

# [i18n-bi] bilingüe server-side: el server hornea sus strings al idioma del run
# (PUPPET_LANG, default es). El título de la obra que RENDERIZA La Sala se hornea acá.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
CAD_I18N = {
    "es": {
        "tool.desc": "Construye un modelo CAD 3D REAL (un soporte/bracket en L de acero, placa base + ala con barrenos de perno) con FreeCAD headless y lo exporta como malla STL orbitable. Todas las dimensiones (bounding box, volumen, nº de triángulos) salen de la geometría real, nunca de memoria. Úsala cuando el usuario pida modelar, diseñar o VER una pieza/soporte 3D. Parámetros opcionales para dimensionar.",
        "p.base_length": "Largo de la placa base en mm (default 120).",
        "p.base_width": "Ancho de la placa base en mm (default 80).",
        "p.plate_thickness": "Espesor de la placa en mm (default 10).",
        "p.flange_height": "Alto del ala vertical en mm (default 60).",
        "p.hole_diameter": "Diámetro de los barrenos de perno en mm (default 9).",
        "title": "Soporte en L — modelo CAD 3D",
        "note": "Modelo CAD real de FreeCAD (malla orbitable). Las dimensiones salen de la geometría, no de memoria.",
        "err_freecadcmd": "freecadcmd no encontrado en %s (FreeCAD no instalado)",
        "err_timeout": "tiempo de CAD agotado (>%ss)",
        "err_no_result": "el motor CAD no produjo malla (ver freecadcmd)",
        "err_unknown_tool": "herramienta desconocida %s",
        "err_internal": "error: %s",
        "err_method": "método no encontrado: %s",
    },
    "en": {
        "tool.desc": "Builds a REAL 3D CAD model (a steel L-bracket: base plate + flange with bolt holes) with headless FreeCAD and exports it as an orbitable STL mesh. Every dimension (bounding box, volume, triangle count) comes from the real geometry, never from memory. Use it when the user asks to model, design, or SEE a 3D part/bracket. Optional parameters to size it.",
        "p.base_length": "Base plate length in mm (default 120).",
        "p.base_width": "Base plate width in mm (default 80).",
        "p.plate_thickness": "Plate thickness in mm (default 10).",
        "p.flange_height": "Vertical flange height in mm (default 60).",
        "p.hole_diameter": "Bolt-hole diameter in mm (default 9).",
        "title": "L-bracket — 3D CAD model",
        "note": "Real FreeCAD CAD model (orbitable mesh). Dimensions come from the geometry, not from memory.",
        "err_freecadcmd": "freecadcmd not found at %s (FreeCAD not installed)",
        "err_timeout": "CAD timeout (>%ss)",
        "err_no_result": "the CAD engine produced no mesh (see freecadcmd)",
        "err_unknown_tool": "unknown tool %s",
        "err_internal": "error: %s",
        "err_method": "Method not found: %s",
    },
}


def _t(key):
    return CAD_I18N.get(PUPPET_LANG, {}).get(key) or CAD_I18N["es"].get(key) or key


TOOLS = [
    {
        "name": "build_cad_model",
        "description": _t("tool.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_length_mm": {"type": "number", "description": _t("p.base_length")},
                "base_width_mm": {"type": "number", "description": _t("p.base_width")},
                "plate_thickness_mm": {"type": "number", "description": _t("p.plate_thickness")},
                "flange_height_mm": {"type": "number", "description": _t("p.flange_height")},
                "hole_diameter_mm": {"type": "number", "description": _t("p.hole_diameter")},
            },
            "required": [],
        },
    },
]


def _build_cad(args: dict) -> dict:
    params = {
        "base_length_mm": args.get("base_length_mm", 120.0),
        "base_width_mm": args.get("base_width_mm", 80.0),
        "plate_thickness_mm": args.get("plate_thickness_mm", 10.0),
        "flange_height_mm": args.get("flange_height_mm", 60.0),
        "flange_thickness_mm": args.get("flange_thickness_mm", 10.0),
        "hole_diameter_mm": args.get("hole_diameter_mm", 9.0),
    }
    if not os.path.exists(_FREECADCMD):
        return {"ok": False, "error": _t("err_freecadcmd") % _FREECADCMD}

    with tempfile.TemporaryDirectory() as td:
        pin = os.path.join(td, "params.json")
        pout = os.path.join(td, "out.json")
        pstl = os.path.join(td, "model.stl")
        with open(pin, "w") as f:
            json.dump(params, f)
        env = dict(os.environ, CAD_PARAMS=pin, CAD_OUT=pout, CAD_STL=pstl)
        try:
            subprocess.run([_FREECADCMD, _ENGINE], env=env, capture_output=True,
                           text=True, timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": _t("err_timeout") % _TIMEOUT}
        if not (os.path.exists(pout) and os.path.exists(pstl)):
            return {"ok": False, "error": _t("err_no_result")}
        with open(pout) as f:
            meta = json.load(f)
        with open(pstl) as f:
            stl = f.read()

    if not meta.get("ok"):
        return meta

    # OBRA RICA: escribe model.cad.json (type=cad, content=STL) → executor la surfacea como
    # obra `cad` → La Sala la rinde con el renderer orbitable. El STL va ACÁ, no al texto.
    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    try:
        with open(os.path.join(workdir, "model.cad.json"), "w") as f:
            json.dump({
                "type": "cad", "format": "stl", "title": _t("title"),
                "content": stl,
                "bbox_mm": meta["bbox_mm"], "triangles": meta["triangles"],
            }, f, ensure_ascii=False)
    except Exception:
        pass

    # texto para el cerebro: los HECHOS de la geometría (sin el STL crudo, que pesa).
    return {
        "ok": True,
        "part": "L-bracket (steel): base plate + vertical flange, 6 bolt holes",
        "bbox_mm": meta["bbox_mm"],
        "volume_mm3": meta["volume_mm3"],
        "triangles": meta["triangles"],
        "vertices": meta["vertices"],
        "rendered_as": "cad (orbitable 3D mesh) in The Room",
        "note": _t("note"),
    }


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})
    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "cad-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "build_cad_model":
                val = _build_cad(args)
            else:
                raise ValueError(_t("err_unknown_tool") % name)
            is_err = not val.get("ok", True)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": is_err}})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": _t("err_internal") % exc}], "isError": True}})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": _t("err_method") % method}})


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
