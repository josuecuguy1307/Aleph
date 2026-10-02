#!/usr/bin/env python3
"""verify_disco_lleno_se_dice.py — el disco lleno no vuelve a salir disfrazado.

LOS TRES DISFRACES, medidos el 2026-08-28/29 en la misma máquina y el mismo día:

    en la app     `[Errno 28]` al escribir un `.json.tmp`  →  HTTP 500, y el modelo se lo
                  contó al usuario como «el entorno bloqueó la escritura temporal requerida»
    en el build   el mismo disco lleno                     →  `internal error in Code
                  Signing subsystem`
    en un pack    `cache write failed: [Errno 28]`         →  enterrado en el log

Ninguno decía «no hay espacio». El costo no es el error: es que cada uno manda a investigar
una superficie distinta y equivocada.

QUÉ CUIDA ESTA VARA: que la causa se RECONOZCA aunque llegue envuelta —que es como llega
siempre— y que las tres superficies la nombren.

Correr:  python3 qa/verify_disco_lleno_se_dice.py
"""
from __future__ import annotations

import errno
import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "product/backend"))
sys.path.insert(0, os.path.join(RAIZ, "platform"))

from app.infra import disco  # noqa: E402

fallos: list[str] = []


def ok(cond, que):
    print(("  ✓ " if cond else "  ✗ ") + que)
    if not cond:
        fallos.append(que)


def envuelto(niveles: int) -> BaseException:
    """El `[Errno 28]` como llega de verdad: enterrado bajo `json.dump`, `shutil`, el turno."""
    exc: BaseException = OSError(errno.ENOSPC, "No space left on device", "/x/pref.json.tmp")
    for i in range(niveles):
        try:
            try:
                raise exc
            except BaseException as causa:
                raise RuntimeError(f"capa {i}") from causa
        except RuntimeError as nueva:
            exc = nueva
    return exc


print("\n── se reconoce, esté donde esté en la cadena ──")
ok(disco.es_disco_lleno(envuelto(0)), "crudo")
ok(disco.es_disco_lleno(envuelto(1)), "envuelto una vez")
ok(disco.es_disco_lleno(envuelto(3)), "tres capas abajo — el caso real")
ok(disco.es_disco_lleno(OSError("write failed: No space left on device")),
   "sin errno, sólo el texto (librerías que re-lanzan)")

print("\n── y NO acusa a lo que no es ──")
ok(not disco.es_disco_lleno(OSError(errno.EACCES, "Permission denied")), "permiso denegado")
ok(not disco.es_disco_lleno(OSError(errno.ENOENT, "No such file")), "archivo inexistente")
ok(not disco.es_disco_lleno(ValueError("otra cosa")), "un error cualquiera")
ok(not disco.es_disco_lleno(None), "sin excepción")

print("\n── la causa tiene copy, y el copy dice qué hacer ──")
ok(disco.CAUSA == "disco_lleno", "la causa se llama `disco_lleno`")
ok("espacio" in disco.COPY.lower(), "el copy nombra el espacio")
ok("liber" in disco.COPY.lower(), "el copy dice qué hacer")
ok("errno" not in disco.COPY.lower(), "el copy NO le muestra un errno a una persona")

print("\n── /health lo publica ──")
est = disco.estado()
ok(est.get("estado") in {"ok", "bajo", "desconocido"}, f"estado declarado: {est.get('estado')}")
ok("libre_gb" in est or est.get("estado") == "desconocido", "dice cuánto queda")

print("\n── las tres superficies lo nombran ──")
main_py = io.open(os.path.join(RAIZ, "product/backend/app/main.py"), encoding="utf-8").read()
ok("_disco_lleno_visible" in main_py, "la app: middleware que lo traduce a 507")
ok('out["disco"]' in main_py, "la app: /health lo reporta")
build = io.open(os.path.join(RAIZ, "deploy/fase4/build_app.sh"), encoding="utf-8").read()
ok("DISCO_MIN_GB" in build, "el build: avisa antes de empezar")
ok("Code Signing subsystem" in build, "el build: nombra el disfraz, para que se reconozca")

print("\n" + ("PASS el disco lleno se dice en las tres superficies"
              if not fallos else f"FAIL {len(fallos)} punto(s)"))
sys.exit(1 if fallos else 0)
