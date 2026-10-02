#!/usr/bin/env python3
"""verify_perillas_gobiernan.py — LA VARA DE LAS PERILLAS PINTADAS.

    python3 qa/verify_perillas_gobiernan.py

──────────────────────────────────────────────────────────────────────────────────────────
QUÉ MIDE

Un **switch** (el control de riel + knob) le promete al usuario que hay algo que él
gobierna. Si al moverlo lo único que pasa es un `setState`, la promesa es falsa: no
persiste, no viaja al servidor, y a la siguiente carga vuelve solo. Es la misma familia
del verde falso — una pantalla afirmando un estado que no midió.

Esta casa ya extirpó una perilla así una vez, y dejó el porqué escrito en el archivo
(`Settings.dc.html`, «acá vivía "Modo por defecto · Guiado | Técnico"»). Esta vara existe
para que la próxima no dure cuatro meses sin que nadie la mida.

LA REGLA, en una línea:

    ningún switch del árbol de diseño puede tener por único efecto un `setState`.

Un switch se reconoce por su `knobStyle` (el bolito que se desliza) — es la firma del
control de riel, y no la comparte ningún otro control del sistema. Los botones que sólo
abren/cierran un panel NO son switches y quedan fuera a propósito: ahí `setState` es el
efecto correcto y completo.

CÓMO PUEDE DAR ROJO

Alguien agrega —o devuelve— un switch cuyo handler no sale del componente. La vara imprime
el archivo, la clave de estado que toca, y qué le falta.

CONTRA QUÉ SE PROBÓ CAYENDO

Corrida sobre `main` ANTES de la obra: **ROJA**, 1 hallazgo en `Settings.dc.html` — la
declaración `notif`, que pinta TRES filas (`done` · `gate` · `fail`) desde un solo `map`.
La vara cuenta declaraciones, no filas: es donde vive el defecto y donde se arregla.
Es el hallazgo A.5 de `CONVERGENCIA-3-AJUSTES.md`, medido de nuevo acá en vez de creerle
al acta.
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "product" / "app" / "design"

# Lo que hace que un `setState` NO sea el único efecto: cualquiera de estas señales en el
# cuerpo del handler significa que el valor sale del componente y sobrevive a la recarga.
SALIDAS = ("fetch(", "localStorage", "sessionStorage", "AlephTheme", "AlephSession",
           "navigator.", "postMessage", "document.cookie")



def revisar(path: Path) -> list[str]:
    txt = path.read_text("utf-8")
    if "knobStyle" not in txt:
        return []
    fallos = []
    # cada switch declara su knob junto al handler que lo mueve, en el mismo objeto
    for m in re.finditer(r"knobStyle\s*:", txt):
        # el objeto del switch: desde el `return {` / `{` anterior hasta el `}` que cierra
        ini = txt.rfind("return {", 0, m.start())
        if ini < 0:
            ini = max(0, m.start() - 600)
        bloque = txt[ini:m.start() + 400]
        mt = re.search(r"toggle\s*:\s*\(\s*\)\s*=>\s*(.{0,300})", bloque, re.S)
        if not mt:
            fallos.append(f"{path.name}: un switch sin handler `toggle:` que lo mueva")
            continue
        cuerpo = mt.group(1)
        if any(s in cuerpo for s in SALIDAS):
            continue
        mk = re.search(r"setState\(\s*st\s*=>\s*\(\{\s*(\w+)", cuerpo)
        clave = mk.group(1) if mk else "?"
        fallos.append(
            f"{path.name}: switch `{clave}` — su handler sólo hace setState. "
            f"No persiste, no viaja, vuelve solo en la próxima carga.")
    return fallos


def main() -> int:
    if not RAIZ.is_dir():
        print(f"✗ no encuentro el árbol de diseño en {RAIZ}")
        return 2
    archivos = sorted(RAIZ.rglob("*.html"))
    if not archivos:
        print(f"✗ 0 archivos .html bajo {RAIZ} — la vara no midió nada")
        return 2
    fallos = []
    for p in archivos:
        if "node_modules" in p.parts:
            continue
        fallos.extend(revisar(p))
    print(f"— {len(archivos)} pantallas revisadas —")
    if fallos:
        print(f"\n✗ ROJO · {len(fallos)} perilla(s) pintada(s):\n")
        for f in fallos:
            print(f"   · {f}")
        print("\n  Una perilla que no gobierna nada se saca o se cablea. No se deja.")
        return 1
    print("✓ VERDE · ningún switch del árbol tiene por único efecto un setState")
    return 0


if __name__ == "__main__":
    sys.exit(main())
