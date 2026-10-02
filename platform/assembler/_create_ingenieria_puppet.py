#!/usr/bin/env python3
"""Crea el puppet 'Agente de Ingenieria' (belt FreeCAD) para un owner explícito.
Valida la receta con recipe_validator (igual que POST /v1/puppets) ANTES de insertar.
Idempotente-ish: si ya existe uno con ese nombre para el owner, lo reporta y NO duplica.
"""
import os
import sys
sys.path.insert(0, "product/backend")
from pathlib import Path
from app.phase1 import repo
from app.phase1 import recipe_validator as rv

NAME = "Agente de Ingeniería"
NICHO = "ingenieria"
REPO_ROOT = Path(".").resolve()

CONFIG = {
    "schema_version": "v1",
    "meta": {
        "name": NAME,
        "nicho": NICHO,
        "descripcion": "Modela piezas paramétricas en FreeCAD (CAD real): crea y edita objetos, "
                       "corre Python de FreeCAD y lee geometría REAL (volumen, masa, bounding box). "
                       "No inventa medidas: las computa en FreeCAD.",
    },
    "belt": {
        "belt_ref": "catalog/templates/ingenieria/belt-ingenieria.mcp.json",
        "tool_filters": {
            "freecad": [
                "create_document", "create_object", "edit_object", "get_object", "get_objects",
                "execute_code", "insert_part_from_library", "get_parts_list", "list_documents",
                "reload_document", "delete_object", "run_fem_analysis",
            ]
        },
    },
    "keys": {},
    "gates": {"send": "needs_ok", "money_touch": "needs_ok"},
    "model": {
        "primary": "openai/gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1",
        "fallback": "llama-3.3-70b-versatile",
        "max_turns": 14,
        "max_tokens": 1400,
        "temperature": 0,
    },
    "framing": {
        "inline": "Eres un agente de ingeniería mecánica equipado con FreeCAD. Modelas piezas "
                  "paramétricas de verdad con las tools de FreeCAD (create_object, edit_object, "
                  "execute_code); no describes un modelo que no construiste. Toda propiedad que "
                  "reportes —volumen, bounding box, masa— la lees de la geometría real "
                  "(get_object o execute_code consultando Shape.Volume / Shape.BoundBox). "
                  "Unidades siempre explícitas (FreeCAD usa mm por defecto). Si algo no se puede "
                  "computar, lo dices; nunca inventas. Cero verde falso.",
    },
    "rag": {"enabled": False},
}


def main():
    owner = os.environ.get("ALEPH_TARGET_OWNER_ID", "").strip()
    if not owner:
        raise SystemExit("ALEPH_TARGET_OWNER_ID es obligatorio; no hay cuenta implícita")
    # 1) validar como el endpoint
    try:
        warnings = rv.validate_recipe(CONFIG, repo_root=REPO_ROOT)
        print("VALIDA: OK", ("· warnings=%s" % warnings) if warnings else "· sin warnings")
    except rv.RecipeValidationError as exc:
        print("VALIDA: RECHAZADA")
        print("  errors:", exc.errors)
        print("  warnings:", exc.warnings)
        sys.exit(2)

    conn = repo.get_conn()
    try:
        # 2) no duplicar
        existing = repo.list_puppets(conn, owner, nicho=NICHO)
        dup = [p for p in existing if p.get("name") == NAME]
        if dup:
            print("YA_EXISTE id=%s — no se duplica" % dup[0]["id"])
            print("PUPPET_ID=%s" % dup[0]["id"])
            return
        # 3) crear
        puppet = repo.create_puppet(conn, owner_id=owner, name=NAME, nicho=NICHO,
                                    config=CONFIG, status="active")
        print("CREADO id=%s status=%s nicho=%s" % (puppet["id"], puppet.get("status"), puppet.get("nicho")))
        print("PUPPET_ID=%s" % puppet["id"])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
