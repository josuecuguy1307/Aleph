#!/usr/bin/env python3
"""con_lock.py — corre un comando SOSTENIENDO un lock exclusivo de archivo.

    python3 qa/lib/con_lock.py /tmp/aleph-frozen.lock -- pyinstaller ...

── POR QUÉ EXISTE ───────────────────────────────────────────────────────────────
La regla del org para las varas frozen es "bajo flock /tmp/aleph-frozen.lock": con 8
terminales en paralelo, dos builds de PyInstaller a la vez se pisan el cache y se comen la
RAM, y dos sidecars frozen a la vez pelean por el disco con sus `_MEI` de ~170 MB.

**macOS NO trae `flock(1)`** (es de util-linux). Un `flock` que "no se encuentra" en un
script con `set -e` mata el build; en un script sin `set -e` lo deja correr SIN CANDADO y
nadie se entera — que es peor. Esto es el candado de verdad: `fcntl.flock` (la misma
llamada que usa `flock(1)`) sobre el mismo archivo, así que interopera con cualquier otro
proceso que lo tome, en Linux o en macOS.

Sale con el código de salida del comando. Si no puede tomar el lock en `--timeout`
segundos, falla VISIBLE con código 75 (EX_TEMPFAIL) — jamás corre igual sin candado.
"""
from __future__ import annotations

import errno
import fcntl
import os
import subprocess
import sys
import time


def main(argv: list[str]) -> int:
    if "--" not in argv or len(argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    corte = argv.index("--")
    cabeza, comando = argv[:corte], argv[corte + 1:]
    if not comando:
        print("con_lock: falta el comando después de '--'", file=sys.stderr)
        return 2

    lock_path = cabeza[0]
    timeout = 3600.0
    if "--timeout" in cabeza:
        timeout = float(cabeza[cabeza.index("--timeout") + 1])

    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    t0, avisado = time.monotonic(), False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if not avisado:
                    print(f"[con_lock] esperando {lock_path} (lo tiene otra sesión)…",
                          flush=True)
                    avisado = True
                if time.monotonic() - t0 > timeout:
                    print(f"[con_lock] ✗ no se pudo tomar {lock_path} en {timeout:.0f}s. "
                          f"NO se corre sin candado.", file=sys.stderr, flush=True)
                    return 75  # EX_TEMPFAIL
                time.sleep(1.0)
        os.write(fd, f"{os.getpid()}\n".encode())
        return subprocess.call(comando)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
