"""Vara mínima de Diseño: configuración del borde y un cruce de artefacto real.

No invoca modelo ni proveedor. Toma markup de un export de Diseño como el stack lo
produciría y prueba el adaptador de forma que usa el endpoint de la Biblioteca.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
from artifacts import bridge  # noqa: E402


def main() -> None:
    source = "<!doctype html><html><body><main>Tarjeta Diseño</main></body></html>"
    crossed = bridge.cross("diseno", {
        "kind": "design_export",
        "name": "tarjeta.html",
        "data": {"name": "tarjeta.html", "content": source},
    })
    # [Convergencia · superficie 7] ERA `informe`, Y ASÍ SE PERDÍA EL FORMATO DE ORIGEN:
    # `formats_for("informe")` es `md · pdf · docx`, o sea que entraba un .html y la obra
    # ya no se podía volver a bajar como .html. El contenido nunca se falseó —es el markup
    # exacto, y esta vara lo sigue comprobando— pero el envase mentía sobre qué era.
    assert crossed == {"type": "web", "title": "tarjeta.html", "content": source}, crossed
    # Y que el tipo sirva de algo: el formato de origen tiene que volver a salir.
    from artifacts import vocabulary  # noqa: PLC0415
    assert vocabulary.formats_for(crossed["type"]) == ["html"], vocabulary.formats_for(crossed["type"])
    # La degradación declarada sigue viva: sin contenido, ficha honesta, jamás un `web` vacío.
    ficha = bridge.cross("diseno", {
        "kind": "design_export", "name": "vacio.html",
        "data": {"name": "vacio.html", "path": "/p/vacio.html", "size": 0},
    })
    assert ficha["type"] == "informe", ficha
    print("OK F6 Diseño: design_export → web (bajable .html), y sin contenido → ficha")


if __name__ == "__main__":
    main()
