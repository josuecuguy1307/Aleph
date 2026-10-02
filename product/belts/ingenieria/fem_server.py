#!/usr/bin/env python3
"""
fem_server.py — MCP stdio server del belt de INGENIERIA: análisis FEM REAL.

Tool `run_fem_analysis`: corre CalculiX (ccx) headless vía freecadcmd sobre una
viga en voladizo paramétrica (Part::Box) y devuelve la tensión de von Mises
máxima, el desplazamiento máximo y un MAPA DE CAMPO (fieldplot) renderizable en
La Sala. Cero fabricación: todo número sale del solver, no del modelo.

Por qué headless: el bridge GUI de freecad-mcp (RPC :9875) cuelga el event-loop
en ops pesadas; freecadcmd corre el solver de forma determinística y aislada.

Vía de salida a La Sala: además del texto-resumen (lo que lee el cerebro), el
server ESCRIBE `vonmises.fieldplot.json` en ${PUPPET_WORKDIR}; el run lo captura
y el frontend lo rinde con el renderer `fieldplot` (heatmap viridis + colorbar).
"""
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE = os.path.join(_HERE, "fem_engine.py")
_FREECADCMD = os.environ.get(
    "FREECADCMD", "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"
)
_TIMEOUT = int(os.environ.get("FEM_TIMEOUT", "300"))

# [i18n-bi] Ola 1 — bilingüe server-side: el server hornea sus strings al idioma del run
# (PUPPET_LANG, default es; no-op hasta que el runtime lo setee). Lo que RENDERIZA La Sala en
# vivo (la métrica del convergence chart) NO se hornea: se emite como CLAVE y render.js la
# resuelve con t(). El verdict reusa la clave canónica render.convergence.verdict_*.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
FEM_I18N = {
    "es": {
        "obra.fem.tool_description": "Corre un análisis FEM (elementos finitos) REAL con CalculiX sobre una viga en voladizo paramétrica de acero (empotrada en un extremo, carga transversal en el otro). Devuelve la tensión de von Mises máxima y mínima (MPa), el desplazamiento máximo (mm) y un mapa de campo renderizable. Úsalo cuando el usuario pida análisis estructural, de esfuerzos/tensiones, deflexión o FEM. Todo número sale del solver, nunca de memoria. Para DIMENSIONAR de forma iterativa: llámala con la geometría actual, lee max_von_mises_MPa, compara contra yield_strength_MPa, y si excede, llámala DE NUEVO con una sección mayor. Cada llamada en el mismo run se acumula como una iteración de convergencia.",
        "obra.fem.param_length": "Largo de la viga en mm (default 1000).",
        "obra.fem.param_width": "Ancho de sección en mm (default 100).",
        "obra.fem.param_height": "Alto de sección en mm (default 100).",
        "obra.fem.param_force": "Carga transversal en N (default 10000).",
        "obra.fem.param_material_name": "Nombre del material (default Steel).",
        "obra.fem.param_youngs_modulus": "Módulo de Young en MPa (default 210000).",
        "obra.fem.param_poisson": "Coef. de Poisson (default 0.30).",
        "obra.fem.param_density": "Densidad kg/m^3 (default 7900).",
        "obra.fem.param_mesh_size": "Tamaño de elemento de malla en mm (opcional).",
        "obra.fem.param_yield_strength": "Límite admisible de von Mises del material (yield) en MPa para el chequeo de falla y el gráfico de convergencia (default 250, acero).",
        "obra.fem.err_freecadcmd_missing": "freecadcmd no encontrado en %s (FreeCAD no instalado)",
        "obra.fem.err_timeout": "tiempo de FEM agotado (>%ss)",
        "obra.fem.err_no_result": "el motor FEM no produjo resultado (ver freecadcmd)",
        "obra.fem.title": "Convergencia FEM — dimensionado de viga",
        "obra.fem.fieldplot_title": "Tensión de von Mises — viga en voladizo",
        "obra.fem.metric_von_mises": "von Mises máx",
        "obra.fem.note": "Análisis FEM real con CalculiX. La decisión de qué geometría probar es tuya.",
        "obra.fem.err_unknown_tool": "herramienta desconocida %s",
        "obra.fem.err_internal": "error: %s",
        "obra.fem.err_method_not_found": "método no encontrado: %s",
        "render.convergence.verdict_pass": "PASA",
        "render.convergence.verdict_fail": "FALLA",
    },
    "en": {
        "obra.fem.tool_description": "Runs a REAL FEM (finite-element) analysis with CalculiX on a parametric steel cantilever beam (fixed at one end, transverse load at the other). Returns the maximum and minimum von Mises stress (MPa), the maximum displacement (mm), and a renderable field map. Use it when the user asks for structural, stress/strain, deflection, or FEM analysis. Every number comes from the solver, never from memory. To size iteratively: call it with the current geometry, read max_von_mises_MPa, compare against yield_strength_MPa, and if it exceeds, call it AGAIN with a larger section. Each call within the same run accumulates as a convergence iteration.",
        "obra.fem.param_length": "Beam length in mm (default 1000).",
        "obra.fem.param_width": "Section width in mm (default 100).",
        "obra.fem.param_height": "Section height in mm (default 100).",
        "obra.fem.param_force": "Transverse load in N (default 10000).",
        "obra.fem.param_material_name": "Material name (default Steel).",
        "obra.fem.param_youngs_modulus": "Young's modulus in MPa (default 210000).",
        "obra.fem.param_poisson": "Poisson's ratio (default 0.30).",
        "obra.fem.param_density": "Density in kg/m^3 (default 7900).",
        "obra.fem.param_mesh_size": "Mesh element size in mm (optional).",
        "obra.fem.param_yield_strength": "Allowable von Mises stress (yield) in MPa, for the failure check and the convergence chart (default 250, steel).",
        "obra.fem.err_freecadcmd_missing": "freecadcmd not found at %s (FreeCAD not installed)",
        "obra.fem.err_timeout": "FEM timeout (>%ss)",
        "obra.fem.err_no_result": "the FEM solver produced no result (see freecadcmd)",
        "obra.fem.title": "Beam sizing via FEM convergence",
        "obra.fem.fieldplot_title": "von Mises stress — cantilever beam",
        "obra.fem.metric_von_mises": "max von Mises",
        "obra.fem.note": "Real FEM analysis with CalculiX. Which geometry to test is your call.",
        "obra.fem.err_unknown_tool": "unknown tool %s",
        "obra.fem.err_internal": "error: %s",
        "obra.fem.err_method_not_found": "Method not found: %s",
        "render.convergence.verdict_pass": "PASS",
        "render.convergence.verdict_fail": "FAIL",
    },
}
def _t(key):
    return FEM_I18N.get(PUPPET_LANG, {}).get(key) or FEM_I18N["es"].get(key) or key

TOOLS = [
    {
        "name": "run_fem_analysis",
        "description": _t("obra.fem.tool_description"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "length_mm": {"type": "number", "description": _t("obra.fem.param_length")},
                "width_mm": {"type": "number", "description": _t("obra.fem.param_width")},
                "height_mm": {"type": "number", "description": _t("obra.fem.param_height")},
                "force_N": {"type": "number", "description": _t("obra.fem.param_force")},
                "material_name": {"type": "string", "description": _t("obra.fem.param_material_name")},
                "youngs_modulus_MPa": {"type": "number", "description": _t("obra.fem.param_youngs_modulus")},
                "poisson_ratio": {"type": "number", "description": _t("obra.fem.param_poisson")},
                "density_kg_m3": {"type": "number", "description": _t("obra.fem.param_density")},
                "mesh_size_mm": {"type": "number", "description": _t("obra.fem.param_mesh_size")},
                "yield_strength_MPa": {"type": "number", "description": _t("obra.fem.param_yield_strength")},
            },
            "required": [],
        },
    },
]


def _run_fem(args: dict) -> dict:
    params = {
        "length_mm": args.get("length_mm", 1000.0),
        "width_mm": args.get("width_mm", 100.0),
        "height_mm": args.get("height_mm", 100.0),
        "force_N": args.get("force_N", 10000.0),
        "material_name": args.get("material_name", "Steel"),
        "material": {
            "youngs_modulus_MPa": args.get("youngs_modulus_MPa", 210000.0),
            "poisson_ratio": args.get("poisson_ratio", 0.30),
            "density_kg_m3": args.get("density_kg_m3", 7900.0),
        },
        "grid_nx": args.get("grid_nx", 80),
        "grid_ny": args.get("grid_ny", 24),
    }
    if args.get("mesh_size_mm"):
        params["mesh_size_mm"] = args["mesh_size_mm"]

    if not os.path.exists(_FREECADCMD):
        return {"ok": False, "error": _t("obra.fem.err_freecadcmd_missing") % _FREECADCMD}

    with tempfile.TemporaryDirectory() as td:
        pin = os.path.join(td, "params.json")
        pout = os.path.join(td, "out.json")
        with open(pin, "w") as f:
            json.dump(params, f)
        env = dict(os.environ, FEM_PARAMS=pin, FEM_OUT=pout)
        try:
            subprocess.run([_FREECADCMD, _ENGINE], env=env, capture_output=True,
                           text=True, timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": _t("obra.fem.err_timeout") % _TIMEOUT}
        if not os.path.exists(pout):
            return {"ok": False, "error": _t("obra.fem.err_no_result")}
        with open(pout) as f:
            res = json.load(f)

    if not res.get("ok"):
        return res

    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    fp = res.get("fieldplot")
    vm = float(res["max_von_mises_MPa"])
    yield_limit = float(args.get("yield_strength_MPa", 250.0))
    exceeds = vm > yield_limit

    # mapa de campo del último FEM (compat single-shot)
    if fp:
        # [i18n-bi] el título del fieldplot lo hornea fem_engine en ES; lo localizamos acá
        # (fem_server tiene _t/PUPPET_LANG) para que el heatmap salga en el idioma del run.
        if isinstance(fp, dict):
            fp["title"] = _t("obra.fem.fieldplot_title")
        try:
            with open(os.path.join(workdir, "vonmises.fieldplot.json"), "w") as f:
                json.dump(fp, f, ensure_ascii=False)
        except Exception:
            pass

    # ACUMULAR la iteración en convergence.json (la PROGRESIÓN del loop, compartida por el run):
    # cada llamada a run_fem_analysis con el mismo workdir agrega un paso. El executor la surfacea
    # como UNA obra `convergence` → La Sala la rinde con el display 1D (it.1 rojo → it.N verde).
    iteration_n = 1
    try:
        cpath = os.path.join(workdir, "convergence.json")
        conv = None
        if os.path.exists(cpath):
            with open(cpath) as f:
                conv = json.load(f)
        if not (isinstance(conv, dict) and isinstance(conv.get("iterations"), list)):
            conv = {"type": "convergence", "title": _t("obra.fem.title"),
                    "metric": {"name": "obra.fem.metric_von_mises", "unit": "MPa", "goal": "min"},
                    "limit": yield_limit, "iterations": []}
        conv["limit"] = yield_limit
        iteration_n = len(conv["iterations"]) + 1
        step = {"n": iteration_n, "value": round(vm, 2), "geometry_mm": res["geometry_mm"],
                "load_N": res["load_N"], "passed": (not exceeds)}
        if fp and isinstance(fp.get("grid"), dict):
            step["grid"] = fp["grid"]
        conv["iterations"].append(step)
        with open(cpath, "w") as f:
            json.dump(conv, f, ensure_ascii=False)
    except Exception:
        pass

    # el texto que lee el cerebro: los HECHOS del solver. QUÉ geometría probar después es DECISIÓN
    # del agente (este server no propone cambios; solo mide).
    return {
        "ok": True,
        "iteration": iteration_n,
        "max_von_mises_MPa": round(vm, 2),
        "yield_limit_MPa": yield_limit,
        "exceeds_limit": exceeds,
        "margin_MPa": round(yield_limit - vm, 2),
        "verdict": (_t("render.convergence.verdict_fail") if exceeds else _t("render.convergence.verdict_pass")),
        "max_displacement_mm": res["max_displacement_mm"],
        "geometry_mm": res["geometry_mm"],
        "load_N": res["load_N"],
        "note": _t("obra.fem.note"),
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
            "serverInfo": {"name": "fem-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "run_fem_analysis":
                val = _run_fem(args)
            else:
                raise ValueError(_t("obra.fem.err_unknown_tool") % name)
            is_err = not val.get("ok", True)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": is_err}})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": _t("obra.fem.err_internal") % exc}], "isError": True}})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": _t("obra.fem.err_method_not_found") % method}})


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
