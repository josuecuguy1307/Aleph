#!/usr/bin/env python3
"""verificar_entorno_packs.py — un pack no se hornea pelado.

QUÉ MIDE. Le pregunta AL BINARIO congelado qué módulos lleva adentro, leyendo el archivo
CArchive que PyInstaller le pega al ejecutable y el TOC del PYZ que va adentro. No mira el
árbol de build ni el `requirements-lock.txt`: eso mide intenciones. Mide lo que viaja.

POR QUÉ EXISTE. Un pack sin sus dependencias arranca igual y muere recién cuando el usuario
usa la tool que importa lo que falta — o sea, en la cara del dueño y no en el build. Es el
mismo criterio que ya aplican los gates de Vane, Ciencia y Oficina en `aleph_sidecar.spec`:
si falta una pieza, se dice CUÁL y CÓMO se produce, y se corta.

DOS TRAMPAS QUE YA MORDIERON, y por eso está escrito así:
  · los módulos de Python PURO no están en el disco del onedir: viven en el PYZ, adentro
    del ejecutable. Buscarlos con `find` da AUSENTE para cosas que sí viajan.
  · la firma de código se agrega DESPUÉS de la cookie de PyInstaller, así que buscarla en
    los últimos 4 KiB del archivo no la encuentra. Se busca en todo el archivo.

Uso:  verificar_entorno_packs.py <nombre-del-pack> <ejecutable> <modulo> [modulo...]
"""
from __future__ import annotations

import marshal
import struct
import sys

_COOKIE = struct.Struct("!8sIIII64s")
_MAGIC = b"MEI\014\013\012\013\016"

#: Cómo se vuelve a producir cada pack, para que el corte diga qué hacer y no sólo qué falta.
_COMO_SE_PRODUCE = {
    "finanzas": (
        "Se produce en build_app.sh [0/3·d]: uv pip sync desde\n"
        "      third_party/vibetrading/requirements-lock.txt y después vibetrading_pack.spec.\n"
        "      Si un módulo falta, casi siempre es que NO está en el lock, o que\n"
        "      PyInstaller no lo vio por importarse por nombre en runtime: agregarlo al\n"
        "      lock, o a `_PAQUETES` del spec para que entre por collect_submodules."
    ),
    "educacion": (
        "Se produce en build_app.sh [0/3]: uv pip sync desde\n"
        "      third_party/deeptutor/requirements-lock.txt y después deeptutor_pack.spec."
    ),
}


def _archivo(ruta: str):
    """Devuelve `(inicio, entradas)` del CArchive pegado al ejecutable."""
    with open(ruta, "rb") as fh:
        todo = fh.read()
    i = todo.rfind(_MAGIC)
    if i < 0:
        raise SystemExit(f"✗ {ruta} no es un binario de PyInstaller (no tiene cookie)")
    magic, largo, toc_off, toc_len, _pyv, _lib = _COOKIE.unpack(todo[i:i + _COOKIE.size])
    inicio = i + _COOKIE.size - largo
    crudo = todo[inicio + toc_off: inicio + toc_off + toc_len]
    entradas, p = [], 0
    while p < len(crudo):
        (elen,) = struct.unpack("!I", crudo[p:p + 4])
        dpos, dlen, _ulen, _flag, typcd = struct.unpack("!IIIBc", crudo[p + 4:p + 18])
        nombre = crudo[p + 18:p + elen].rstrip(b"\0").decode("utf-8", "replace")
        entradas.append((nombre, typcd.decode(), dpos, dlen))
        p += elen
    return todo, inicio, entradas


def modulos_de(ruta: str) -> set[str]:
    """Las RAÍCES de todos los módulos que el binario lleva adentro."""
    todo, inicio, entradas = _archivo(ruta)
    nombres: set[str] = set()
    for nombre, typcd, dpos, dlen in entradas:
        nombres.add(nombre)
        if typcd != "z" and not nombre.endswith(".pyz"):
            continue
        blob = todo[inicio + dpos: inicio + dpos + dlen]
        if blob[:4] != b"PYZ\0":
            continue
        (toc_pos,) = struct.unpack("!I", blob[8:12])
        toc = marshal.loads(blob[toc_pos:])
        # PyInstaller viejo devuelve dict; el nuevo, lista de (nombre, (typ, pos, len)).
        nombres.update(toc.keys() if isinstance(toc, dict) else (e[0] for e in toc))
    return {n.split(".")[0].lower() for n in nombres}


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        raise SystemExit(__doc__)
    pack, binario, pedidos = argv[1], argv[2], [a.lower() for a in argv[3:]]
    presentes = modulos_de(binario)
    faltan = [m for m in pedidos if m not in presentes]
    if not faltan:
        print(f"   ✓ entorno de {pack}: {len(pedidos)}/{len(pedidos)} módulos adentro "
              f"({len(presentes)} raíces en el pack)")
        return 0
    print(f"✗ el pack de {pack} viajaría PELADO: le faltan {len(faltan)} de "
          f"{len(pedidos)} módulos que sus tools importan")
    for m in faltan:
        print(f"      · {m}")
    print("      " + _COMO_SE_PRODUCE.get(pack, "(sin receta declarada para este pack)"))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
