#!/usr/bin/env python3
r"""verify_guarda_huella.py — LA GUARDA DEL BUILD NO PUEDE COSTAR MÁS QUE EL BUILD.

[2026-08-22]

QUÉ MIDE
--------
`deploy/fase4/build_app.sh` protege las `.app` instaladas contra otra sesión: fotografía la
huella de cada una antes del `tauri build` y la re-verifica después. La huella es
`sha256(listado ordenado de sha256 de cada archivo)`.

Esa definición está bien. Lo que estaba mal era CÓMO se calculaba: `find … -exec shasum {} \;`
levanta **un proceso por archivo**. Con onefile daba igual —el bundle entero eran 23
archivos— pero la tanda 3 lo pasó a ONEDIR y hoy son **132.476**. Medido en vivo durante un
build real: ese `find` corrió **más de 18 minutos**, y la guarda corre DOS veces (antes y
después) sobre CADA `.app` instalada. Se comía casi todo el build.

Con `-exec … {} +` los archivos van por lotes. Medido, mismo bundle onedir: **25,79 s**.

ESTA VARA MIDE LAS DOS COSAS, y la segunda es la que importa
------------------------------------------------------------
1. que el script use la forma por lotes (`+`) y no la de un proceso por archivo (`\\;`);
2. que las DOS formas den **exactamente la misma huella** sobre un árbol de prueba con la
   forma real de un bundle — archivos anidados, nombres con espacios, un binario, un vacío.

Lo segundo es el punto: una optimización que cambia el valor de la huella no es una
optimización, es una guarda distinta. `sort` ya normalizaba el orden, así que el cambio es
sólo de proceso; esta vara lo PRUEBA en vez de afirmarlo.

CORRE: `python3 qa/verify_guarda_huella.py`
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "deploy" / "fase4" / "build_app.sh"

FALLOS: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"  {'✓' if cond else '✗'} {etiqueta}" + ("" if cond or not extra else f" — {extra}"))
    if not cond:
        FALLOS.append(etiqueta)


def huella(raiz: Path, forma: str) -> str:
    """La huella tal cual la calcula el script, con la forma pedida (`+` o `\\;`)."""
    cmd = (f'find {raiz!s} -type f -exec shasum -a 256 {{}} {forma} 2>/dev/null '
           f'| sort | shasum -a 256 | cut -d" " -f1')
    return subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True).stdout.strip()


def arbol_de_prueba(base: Path) -> None:
    """La FORMA de un bundle, no un caso feliz: anidado, con espacios en el nombre, un
    binario con bytes nulos, un archivo vacío y uno grande-ish. Si la vara sólo probara
    archivos de texto planos en un solo nivel, no mediría lo que el bundle real tiene."""
    (base / "Contents" / "MacOS").mkdir(parents=True)
    (base / "Contents" / "Frameworks" / "un dir con espacios").mkdir(parents=True)
    (base / "Contents" / "MacOS" / "app").write_bytes(b"\x00\x01\x02binario\xff" * 64)
    (base / "Contents" / "Info.plist").write_text("<plist/>\n")
    (base / "Contents" / "Frameworks" / "un dir con espacios" / "hoja con espacios.txt").write_text("hola\n")
    (base / "Contents" / "Frameworks" / "vacio").write_bytes(b"")
    (base / "Contents" / "Frameworks" / "grande.bin").write_bytes(os.urandom(1 << 20))


def main() -> int:
    print("── la guarda del build ──")
    texto = SCRIPT.read_text(encoding="utf-8")
    bloque = texto[texto.index("huella_app()"):]
    bloque = bloque[:bloque.index("\n}")]

    ok("-exec shasum -a 256 {} +" in bloque,
       "la huella se calcula POR LOTES (`-exec … {} +`)",
       "con `\\;` es un proceso por archivo: 18+ minutos medidos sobre los 132.476 del onedir")
    ok(not re.search(r"-exec shasum[^\n]*\{\}\s*\\;", bloque),
       "y no quedó ninguna forma de un-proceso-por-archivo")
    ok("| sort |" in bloque,
       "el orden se sigue normalizando con `sort`",
       "sin esto los lotes darían una huella distinta en cada corrida")

    print("\n── las dos formas dan LA MISMA huella ──")
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "Prueba.app"
        arbol_de_prueba(base)
        n = sum(1 for _ in base.rglob("*") if _.is_file())
        por_lotes = huella(base, "+")
        uno_a_uno = huella(base, "\\;")
        ok(bool(por_lotes) and por_lotes == uno_a_uno,
           f"idénticas sobre un árbol con la forma real ({n} archivos)",
           f"lotes={por_lotes[:16]} uno_a_uno={uno_a_uno[:16]}")

        # Y que la huella SIRVA: tocar un byte tiene que cambiarla. Una huella que no puede
        # cambiar no protege nada, que es la otra forma de romper esta guarda.
        (base / "Contents" / "Info.plist").write_text("<plist>tocado</plist>\n")
        ok(huella(base, "+") != por_lotes,
           "y cambian si se toca un solo archivo",
           "una guarda que no distingue no es una guarda")

    print("\n" + ("✓ la guarda: todo verde" if not FALLOS else f"✗ {len(FALLOS)} roja(s)"))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
