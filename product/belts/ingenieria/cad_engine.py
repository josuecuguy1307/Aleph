#!/usr/bin/env python3
"""
cad_engine.py — corre BAJO freecadcmd (intérprete de FreeCAD). Construye un soporte
("bracket") en L paramétrico con barrenos de perno y exporta una malla ASCII STL +
metadatos. Cero fabricación: la malla sale de la geometría REAL de FreeCAD (tessellate),
no de un modelo prefab ni de números inventados.

E/S por entorno (lo setea cad_server.py):
  CAD_PARAMS  json de entrada (dimensiones)
  CAD_OUT     json de salida  (metadatos: triángulos, bbox, volumen)
  CAD_STL     ruta del STL ASCII de salida
"""
import os
import json
import math

import FreeCAD as App
import Part


def _facet_normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    m = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / m, ny / m, nz / m


def main():
    p = json.load(open(os.environ["CAD_PARAMS"]))
    L = float(p.get("base_length_mm", 120.0))
    W = float(p.get("base_width_mm", 80.0))
    T = float(p.get("plate_thickness_mm", 10.0))
    Hf = float(p.get("flange_height_mm", 60.0))
    Tf = float(p.get("flange_thickness_mm", 10.0))
    r = float(p.get("hole_diameter_mm", 9.0)) / 2.0
    inset = float(p.get("hole_inset_mm", 15.0))
    tol = float(p.get("tessellation_mm", 0.2))

    App.newDocument("bracket")
    base = Part.makeBox(L, W, T)                       # placa base
    flange = Part.makeBox(Tf, W, Hf)                   # ala vertical en el borde trasero
    flange.translate(App.Vector(0, 0, T))
    solid = base.fuse(flange)

    # 4 barrenos verticales en la placa base (despejados del ala: inset > Tf)
    for (x, y) in [(inset, inset), (L - inset, inset), (inset, W - inset), (L - inset, W - inset)]:
        solid = solid.cut(Part.makeCylinder(r, T + 2, App.Vector(x, y, -1), App.Vector(0, 0, 1)))
    # 2 barrenos horizontales en el ala
    for z in (T + Hf * 0.35, T + Hf * 0.70):
        solid = solid.cut(Part.makeCylinder(r, Tf + 2, App.Vector(-1, W * 0.5, z), App.Vector(1, 0, 0)))

    pts, tris = solid.tessellate(tol)                  # malla REAL (no prefab)
    out_lines = ["solid bracket"]
    for (i, j, k) in tris:
        a = (pts[i].x, pts[i].y, pts[i].z)
        b = (pts[j].x, pts[j].y, pts[j].z)
        c = (pts[k].x, pts[k].y, pts[k].z)
        nx, ny, nz = _facet_normal(a, b, c)
        out_lines.append("  facet normal %.6e %.6e %.6e" % (nx, ny, nz))
        out_lines.append("    outer loop")
        for v in (a, b, c):
            out_lines.append("      vertex %.6e %.6e %.6e" % (v[0], v[1], v[2]))
        out_lines.append("    endloop")
        out_lines.append("  endfacet")
    out_lines.append("endsolid bracket")
    stl = "\n".join(out_lines) + "\n"
    with open(os.environ["CAD_STL"], "w") as f:
        f.write(stl)

    bb = solid.BoundBox
    json.dump({
        "ok": True,
        "triangles": len(tris),
        "vertices": len(pts),
        "bbox_mm": {"x": round(bb.XLength, 2), "y": round(bb.YLength, 2), "z": round(bb.ZLength, 2)},
        "volume_mm3": round(solid.Volume, 1),
        "stl_bytes": len(stl),
    }, open(os.environ["CAD_OUT"], "w"))


main()
