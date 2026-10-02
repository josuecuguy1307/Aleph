#!/usr/bin/env python3
"""
fem_engine.py — motor FEM headless (FreeCAD + CalculiX) para el belt de INGENIERIA.

Se ejecuta DENTRO de freecadcmd (no como python normal):
    freecadcmd fem_engine.py <params.json> <out.json>

Construye una viga en voladizo paramétrica (Part::Box), la malla con Gmsh,
le pone material + empotramiento (Face1, x=0) + carga transversal (Face2, x=L,
direccion Edge5 invertida = -Z, flexion), corre ccx REAL y devuelve:
  max/min von Mises, desplazamiento maximo, y un CAMPO ESCALAR proyectado a una
  grilla nx*ny (plano largo x alto) en el formato `fieldplot` que consume La Sala.

Cero fabricacion: todo numero sale del .frd de CalculiX.
"""
import json
import os
import sys
import traceback

CCX = "/Applications/FreeCAD.app/Contents/Resources/bin/ccx"


def run(params: dict) -> dict:
    import FreeCAD as App
    import ObjectsFem
    from femmesh.gmshtools import GmshTools
    from femtools import ccxtools

    L = float(params.get("length_mm", 1000.0))
    W = float(params.get("width_mm", 100.0))
    H = float(params.get("height_mm", 100.0))
    force_N = float(params.get("force_N", 10000.0))
    mat = params.get("material", {})
    E = float(mat.get("youngs_modulus_MPa", 210000.0))
    nu = float(mat.get("poisson_ratio", 0.30))
    rho = float(mat.get("density_kg_m3", 7900.0))
    mesh_size = float(params.get("mesh_size_mm", max(min(L, W, H) / 4.0, 8.0)))
    gnx = int(params.get("grid_nx", 80))
    gny = int(params.get("grid_ny", 24))

    # FEM solver pref → CalculiX bundleado
    p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
    p.SetBool("UseStandardCcxLocation", False)
    p.SetString("ccxBinaryPath", CCX)

    doc = App.newDocument("fem")
    box = doc.addObject("Part::Box", "Box")
    box.Length = L; box.Width = W; box.Height = H
    doc.recompute()

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver")
    solver.AnalysisType = "static"
    solver.GeometricalNonlinearity = "linear"
    solver.MatrixSolverType = "default"
    analysis.addObject(solver)

    material = ObjectsFem.makeMaterialSolid(doc, "Material")
    md = material.Material
    md["Name"] = params.get("material_name", "Steel")
    md["YoungsModulus"] = "%g MPa" % E
    md["PoissonRatio"] = "%g" % nu
    md["Density"] = "%g kg/m^3" % rho
    material.Material = md
    analysis.addObject(material)

    # constraints (topologia canonica de Part::Box)
    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [(box, "Face1")]      # x=0
    analysis.addObject(fixed)

    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [(box, "Face2")]      # x=L
    force.Force = "%g N" % force_N
    force.Direction = (box, ["Edge5"])
    force.Reversed = True                    # -Z → flexion
    analysis.addObject(force)

    # malla Gmsh
    femmesh = ObjectsFem.makeMeshGmsh(doc, "FEMMeshGmsh")
    femmesh.Shape = box
    femmesh.CharacteristicLengthMax = mesh_size
    femmesh.ElementOrder = "2nd"
    analysis.addObject(femmesh)
    doc.recompute()
    gmsh = GmshTools(femmesh)
    err = gmsh.create_mesh()
    if err:
        # error puede ser un str de Gmsh; lo reportamos
        if isinstance(err, str) and err.strip():
            raise RuntimeError("gmsh: " + err.strip()[:300])
    n_mesh_nodes = femmesh.FemMesh.NodeCount
    if n_mesh_nodes == 0:
        raise RuntimeError("malla vacia (gmsh no genero nodos)")

    # resolver ccx
    fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=False)
    fea.purge_results()
    fea.update_objects()
    fea.setup_working_dir()
    fea.setup_ccx(CCX)
    msg = fea.check_prerequisites()
    if msg:
        raise RuntimeError("prereq: " + str(msg))
    fea.write_inp_file()
    fea.ccx_run()
    fea.load_results()

    res = next(o for o in doc.Objects if o.isDerivedFrom("Fem::FemResultObject"))
    vm = list(res.vonMises)
    disp = list(res.DisplacementLengths) if hasattr(res, "DisplacementLengths") else []
    nodes_map = res.Mesh.FemMesh.Nodes          # {id: Vector}
    node_ids = list(res.NodeNumbers) if hasattr(res, "NodeNumbers") and res.NodeNumbers else sorted(nodes_map.keys())

    max_vm = max(vm); min_vm = min(vm)
    max_disp = max(disp) if disp else None

    # ── proyeccion a grilla nx*ny en el plano (X=largo, Z=alto): envolvente MAX ──
    cells = [[None] * gnx for _ in range(gny)]
    for i, nid in enumerate(node_ids):
        v = nodes_map.get(nid)
        if v is None or i >= len(vm):
            continue
        ix = int(min(gnx - 1, max(0, (v.x / L) * gnx)))
        iz = int(min(gny - 1, max(0, (v.z / H) * gny)))
        cur = cells[iz][ix]
        if cur is None or vm[i] > cur:
            cells[iz][ix] = vm[i]
    # rellenar huecos con el vecino mas cercano (grilla mas fina que la malla)
    flat = []
    for iz in range(gny):
        for ix in range(gnx):
            val = cells[iz][ix]
            if val is None:
                best = None; bestd = 1e18
                for jz in range(gny):
                    for jx in range(gnx):
                        if cells[jz][jx] is None:
                            continue
                        d = (jz - iz) ** 2 + (jx - ix) ** 2
                        if d < bestd:
                            bestd = d; best = cells[jz][jx]
                val = best if best is not None else 0.0
            flat.append(round(float(val), 4))
    # fila iz=0 abajo → la Sala dibuja y=0 arriba; invertimos para que el "alto" suba
    rows = [flat[iz * gnx:(iz + 1) * gnx] for iz in range(gny)]
    rows.reverse()
    values = [x for row in rows for x in row]

    fieldplot = {
        "type": "fieldplot",
        "title": "Tension de von Mises — viga en voladizo",
        "source": "FreeCAD FEM + CalculiX ccx (real)",
        "slice": "plano X(largo)-Z(alto), envolvente max en Y",
        "grid": {
            "nx": gnx, "ny": gny, "values": values,
            "min": round(min(values), 4), "max": round(max(values), 4),
            "unit": "MPa", "interpolate": True,
        },
    }
    return {
        "ok": True,
        "max_von_mises_MPa": round(max_vm, 4),
        "min_von_mises_MPa": round(min_vm, 4),
        "max_displacement_mm": round(max_disp, 6) if max_disp is not None else None,
        "mesh_nodes": n_mesh_nodes,
        "result_nodes": len(vm),
        "geometry_mm": {"length": L, "width": W, "height": H},
        "load_N": force_N,
        "material": {"youngs_modulus_MPa": E, "poisson_ratio": nu, "density_kg_m3": rho},
        "fieldplot": fieldplot,
    }


def main():
    # freecadcmd trata los args posicionales como archivos a ABRIR → pasamos por ENV.
    params_path = os.environ.get("FEM_PARAMS") or (sys.argv[1] if len(sys.argv) > 1 else "")
    out_path = os.environ.get("FEM_OUT") or (sys.argv[2] if len(sys.argv) > 2 else "")
    with open(params_path) as f:
        params = json.load(f)
    try:
        out = run(params)
    except Exception as e:
        out = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
               "trace": traceback.format_exc()[-1500:]}
    with open(out_path, "w") as f:
        json.dump(out, f)
    print("FEM_ENGINE_DONE ok=%s" % out.get("ok"))


main()
