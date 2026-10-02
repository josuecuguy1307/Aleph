#!/usr/bin/env python3
"""Vara Método × Conectores, cableada al vocabulario real de 5a.

Cada calibración mueve SU knob antes de aceptar el veredicto:
``permissions[]`` de 5a, filtro de pieza, gate y requires exportado.
No toca el arnés certificado.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for value in (ROOT / "product" / "backend", ROOT / "platform"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

os.environ.setdefault("PUPPET_MOTOR_PERSISTE", "0")

from app.phase1 import method_export as mx  # noqa: E402
from app.phase1 import method_match as mm  # noqa: E402
from app.phase1 import methods_repo as mr  # noqa: E402

passed = 0
failed = 0


def check(name: str, condition: bool, detail="") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS · {name}")
    else:
        failed += 1
        print(f"  FAIL · {name}" + (f" — {detail}" if detail else ""))


def onboarding(root: Path, connector: str, capabilities: list[str]) -> None:
    path = root / "catalog" / "connectors" / "onboarding" / f"{connector}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "permissions": capabilities,
    }, ensure_ascii=False), encoding="utf-8")


def belt(path: Path, connectors: list[tuple[str, str]]) -> None:
    cards, servers = [], {}
    for i, (server, connector) in enumerate(connectors):
        servers[server] = {"command": "true"}
        cards.append({
            "id": f"pieza-{i}", "backed_by": server,
            "connector": connector,
            # Estos campos son ruido deliberado: el matcher jamás los usa como
            # vocabulario ni como identidad funcional.
            "label": f"Marca {i}",
            "sub": f"capacidad inventada desde prosa {i}",
            "tools": [f"tool_{i}"],
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "_meta": {"cards": cards}, "mcpServers": servers,
    }, ensure_ascii=False), encoding="utf-8")


def config(path: Path, active: list[str]) -> dict:
    return {
        "belt": {
            "belt_ref": str(path),
            "tool_filters": {server: ["tool"] for server in active},
        }
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="vara-metodo-conectores-"))
    half = tmp / "catalog" / "templates" / "half" / "belt-half.mcp.json"
    full = tmp / "catalog" / "templates" / "full" / "belt-full.mcp.json"
    connectors = [
        ("mail", "gmail"),
        ("drive", "google_drive"),
    ]
    caps = [
        "leer correo",
        "crear borradores",
        "leer archivos",
        "crear archivos",
    ]
    onboarding(tmp, "gmail", caps[:2])
    onboarding(tmp, "google_drive", caps[2:])
    belt(half, connectors[:1])
    belt(full, connectors)
    method = {
        "id": "11111111-1111-4111-8111-111111111111",
        "name": "Preparar documentos y correo",
        "requires": caps,
        "steps": [{"text": "Preparar documentos y borradores"}],
    }

    print("— match 5a + semáforo —")
    vocabulary = mm.capability_declarations(tmp)
    check("vocabulario sale de permissions[] de 5a",
          [d["name"] for d in vocabulary] == caps
          and all(d.get("source") == "catalogo_5a" for d in vocabulary),
          vocabulary)
    check("labels/sub/tools no se convierten en capacidades",
          not any("capacidad inventada" in d["name"] for d in vocabulary),
          vocabulary)
    yellow = mm.method_state(method, config(half, ["mail"]), tmp)
    check("pide 4 / belt cubre 2 → 🟡",
          yellow["estado"] == "huecos" and yellow["semaforo"] == "detectado",
          yellow)
    check("nombra LOS 2 faltantes correctos",
          yellow["faltantes"] == ["leer archivos", "crear archivos"],
          yellow["faltantes"])
    paths = {r["capacidad"]: r for r in yellow["resoluciones"]}
    check("cada faltante de pieza trae [Traer] al registro",
          paths["leer archivos"]["camino"] == "registro"
          and paths["crear archivos"]["camino"] == "registro", paths)

    green = mm.method_state(method, config(full, ["mail", "drive"]), tmp)
    check("belt completo → 🟢", green["estado"] == "completo", green)

    removed = mm.method_state(method, config(full, ["mail"]), tmp)
    check("quitar pieza → recalcula a 🟡 SOLO",
          removed["estado"] == "huecos"
          and removed["faltantes"] == ["leer archivos", "crear archivos"], removed)

    restored = mm.method_state(method, config(full, ["mail", "drive"]), tmp)
    check("resolver faltante → 🟢 vuelve",
          restored["estado"] == "completo", restored)

    invented = {**method, "requires": ["teletransportación cuántica"]}
    red = mm.method_state(invented, config(full, ["mail", "drive"]), tmp)
    check("ROJO: capacidad inventada jamás 🟢",
          red["estado"] == "huecos"
          and red["faltantes"] == ["teletransportación cuántica"], red)
    # Calibración viva: corta SU knob (permissions[] de 5a), no una condición
    # vecina. Con Drive todavía equipado, borrar su clasificación debe volver
    # amarillo el mismo método que acaba de quedar verde.
    onboarding(tmp, "google_drive", [])
    cut_5a = mm.method_state(method, config(full, ["mail", "drive"]), tmp)
    check("ROJO: cortar permissions[] de 5a rompe el verde",
          cut_5a["estado"] == "huecos"
          and cut_5a["faltantes"] == ["leer archivos", "crear archivos"], cut_5a)
    onboarding(tmp, "google_drive", caps[2:])

    print("— gate medido, no suerte léxica —")
    yellow_method = {**method, "equipment": yellow}
    green_method = {**method, "equipment": green}
    eligible_yellow = mm.eligible_for_sala([yellow_method])
    check("método 🟡 → card JAMÁS elegible", eligible_yellow == [])
    eligible_green = mm.eligible_for_sala([green_method])
    check("método 🟢 → card SÍ elegible y matchea",
          mr.match_method(eligible_green, "preparar documentos y correo") is green_method)
    # Calibración: neutralizar EL GATE al vuelo, sin cambiar léxico ni método.
    neutralized = (lambda methods: methods)([yellow_method])
    check("ROJO: gate neutralizado → la card del 🟡 aparece",
          mr.match_method(neutralized, "preparar documentos y correo") is yellow_method)

    print("— .aleph receptor —")
    source_agent = {
        "id": "22222222-2222-4222-8222-222222222222", "name": "A", "nicho": "x",
        "config": config(full, ["mail", "drive"]),
    }
    archive = mx.agent_to_aleph(source_agent, [method])
    _kind, parsed = mx.parse_aleph(archive)
    traveled = parsed["methods"][0]["method"]
    check("export/import: requires[] viaja intacto",
          traveled["requires"] == method["requires"], traveled)
    receiver = mm.method_state(traveled, config(half, ["mail"]), tmp)
    check("import en belt distinto → veredicto de ESE belt",
          receiver["faltantes"] == ["leer archivos", "crear archivos"], receiver)

    print("— contrato JS del primer turno —")
    _sala_f = ROOT / "product" / "app" / "design" / "sala" / "sala.html"
    # [Convergencia · superficie 7 · paso 6] La Sala vieja se borró: esta mitad no tiene
    # objeto. Se saltea diciéndolo — el resto de lo que mide esta vara sigue vivo.
    if not _sala_f.exists():
        print("  ~ SALTEADO: la Sala vieja se borró (paso 6)")
        return
    sala = _sala_f.read_text()
    check("metodoEquipped es async",
          "async function metodoEquipped()" in sala)
    check("metodoMaybePropose espera la carga real",
          "var eq=await metodoEquipped();" in sala)
    check("timeout de match nace después del await",
          sala.index("var eq=await metodoEquipped();")
          < sala.index("var to=setTimeout", sala.index("function metodoMaybePropose")))
    # Calibración roja sobre el código anterior: al sacar await vuelve el bug exacto.
    old_shape = sala.replace("var eq=await metodoEquipped();",
                             "var eq=metodoEquipped();", 1)
    check("ROJO: neutralizar await reproduce contrato espurio",
          "var eq=metodoEquipped();" in old_shape
          and "var eq=await metodoEquipped();" not in old_shape)

    print(f"\n{passed} PASS / {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
