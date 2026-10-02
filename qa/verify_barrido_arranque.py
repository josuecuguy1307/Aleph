#!/usr/bin/env python3
"""verify_barrido_arranque.py — EL BARRIDO DE ARRANQUE NO PIDE ARCHIVOS QUE NO EXISTEN.

[TANDA 1 · obra 2]

EL BUG, medido contra la `.app` instalada `d80109bb…` el 2026-08-22
---------------------------------------------------------------------
En cada arranque, `main.py:207` corre `[local] barrido de arranque` y 12 de sus 35
re-verificaciones morían así:

    [local] ✗ gmail: FileNotFoundError: [Errno 2] .../_MEIxKTYKb/assembler.py
    (igual: zotero · alphavantage · coingecko · fred · massive · github · huggingface ·
     secedgar · materialsproject · context7 · exa)

Doce conectores DEL USUARIO reportados como no verificables por un archivo NUESTRO mal
ubicado — justo lo que §8 de FIX-P1B prohíbe. La cadena:

    conexiones_verificador._ra()  ·  `import recipe_assembler` A SECAS
      → bajo PyInstaller el FrozenImporter del PYZ precede a `sys.path`, gana la copia
        congelada y su `__file__` es `<_MEIPASS>/recipe_assembler.py` (inexistente)
      → recipe_assembler.py:74  `_THIS_DIR = Path(__file__).resolve().parent` = `<_MEIPASS>`
      → recipe_assembler.py:91  `_THIS_DIR / "assembler.py"` = la ruta del error

POR QUÉ ESTA VARA TIENE DOS MITADES
-----------------------------------
El bug **sólo existe congelado**. Una vara puramente dinámica corre en dev, pasa, y no
mide nada: es la definición de verde mudo. Así que:

  · MITAD ESTÁTICA — la forma del código: `_ra()` tiene que resolver por
    `resource_root()`, y no puede quedar un `import recipe_assembler` a secas. Ésta da
    rojo en dev, que es donde se edita.
  · MITAD DINÁMICA — la ruta resuelta EXISTE en disco. Corriendo dentro del binario
    congelado (`sys.frozen`) ésta es la vara de verdad; en dev protege contra apuntar la
    raíz al lugar equivocado.

CORRE: `python3 qa/verify_barrido_arranque.py`
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# Los MISMOS directorios que el producto pone en `sys.path` al importar
# `conexiones_verificador` (:38). `platform/assembler` también, porque `recipe_assembler`
# importa a sus vecinos (`belt_resolver`, …) por nombre corto — y eso NO es el bug: es
# cómo está escrito el módulo, dentro y fuera del bundle.
for _d in ("platform", "platform/db", "platform/inspection", "platform/assembler",
           "product/backend"):
    sys.path.insert(0, str(RAIZ / _d))

FALLOS: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"  {'✓' if cond else '✗'} {etiqueta}" + ("" if cond or not extra else f" — {extra}"))
    if not cond:
        FALLOS.append(etiqueta)


def main() -> int:
    fuente = (RAIZ / "product" / "backend" / "app" / "phase1"
              / "conexiones_verificador.py").read_text(encoding="utf-8")

    # ── MITAD ESTÁTICA ───────────────────────────────────────────────────────────────
    m = re.search(r"\ndef _ra\(\):(.*?)\ndef ", fuente, re.S)
    ok(bool(m), "`_ra()` sigue existiendo en conexiones_verificador")
    cuerpo = m.group(1) if m else ""

    ok(not re.search(r"^\s*import recipe_assembler\s*(#.*)?$", cuerpo, re.M),
       "`_ra()` NO usa `import recipe_assembler` a secas (el PYZ le ganaría a sys.path)")
    ok("resource_root()" in cuerpo,
       "`_ra()` resuelve por `aleph_paths.resource_root()` (el remedio de byo_mcp.py:42-55)")
    ok("load_module_by_path" in cuerpo,
       "`_ra()` carga POR RUTA, igual que centro_conexiones.py:647")

    # Ningún otro `import recipe_assembler` a secas en el módulo: arreglar uno y dejar el
    # de al lado es cómo este bug volvió otras veces.
    sueltos = re.findall(r"^\s*import recipe_assembler\s*(?:#.*)?$", fuente, re.M)
    ok(not sueltos, "no queda ningún `import recipe_assembler` a secas en el archivo",
       f"{len(sueltos)} encontrado(s)")

    # ── MITAD DINÁMICA ───────────────────────────────────────────────────────────────
    try:
        import aleph_paths

        root = aleph_paths.resource_root()
        ra_py = root / "platform" / "assembler" / "recipe_assembler.py"
        asm_py = root / "platform" / "assembler" / "assembler.py"
        ok(ra_py.exists(), "recipe_assembler.py existe en la raíz de recursos", str(ra_py))
        ok(asm_py.exists(), "assembler.py existe en la raíz de recursos", str(asm_py))

        from app.phase1 import conexiones_verificador as CV

        mod = CV._ra()
        archivo = Path(getattr(mod, "__file__", "") or "")
        ok(archivo.name == "recipe_assembler.py",
           "`_ra()` devuelve el módulo recipe_assembler", str(archivo))
        # ⚠️ LA ASERCIÓN QUE HABRÍA CAZADO EL BUG: no basta con que el módulo cargue —
        # lo que reventaba era el vecino que ÉL resuelve desde su propio `__file__`.
        vecino = archivo.parent / "assembler.py"
        ok(vecino.exists(),
           "el `assembler.py` que ese módulo resolverá desde su `__file__` EXISTE",
           str(vecino))
        ok(archivo.parent.name == "assembler" and archivo.parent.parent.name == "platform",
           "y vive en `platform/assembler/`, no en la raíz del bundle", str(archivo.parent))
    except Exception as exc:  # noqa: BLE001 — un fallo acá ES el rojo, no un salteo
        ok(False, "la mitad dinámica corrió", f"{type(exc).__name__}: {exc}")

    print("\n✗ %d fallo(s)" % len(FALLOS) if FALLOS else "\n✓ barrido de arranque: todo verde")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
