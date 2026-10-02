#!/usr/bin/env python3
"""verify_tres_cables.py — F2d · LOS TRES CABLES, PUESTOS Y CORRIENDO.

F2d dejó tres funciones listas y **sin cablear**, porque los tres puntos viven fuera de
`cli_brain/`: dos en `product/backend/app/main.py::_lifespan` y uno en
`deploy/fase4/sidecar_serve.py`. Esta vara verifica que estén puestos **y que corran**.

⚠️ **UN CABLE QUE NO HACE NADA SE VE IGUAL QUE UN CABLE QUE NO ESTÁ.** El barrido sólo
imprime si mató algo, y `stop_managed_service()` sobre un backend que nunca levantó el
servicio es un no-op sano. Correr el lifespan y ver silencio no prueba nada. Por eso acá se
ESPÍA: se reemplazan las dos funciones por testigos y se exige que el lifespan las LLAME.

  1. barrido de CLI al arrancar   `main.py::_lifespan`, antes de `purge_task=`
  2. cierre del CLI               `main.py::_lifespan`, en el `finally`
  3. force-exit                   `sidecar_serve.py`, en su `finally`

El 3 no se puede ejercer en proceso —`os._exit(0)` mataría a esta vara— así que se verifica
sobre el código: que llame al detallado, que mire `colgado`, y que use `os._exit` y no
`sys.exit`.

    product/backend/.venv/bin/python platform/assembler/cli_brain/verify_tres_cables.py
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[2]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/assembler",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("ALEPH_ROLE", "client")

_fallos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f" — {detalle}" if detalle else ""))


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 72 - len(t)))


_MAIN = _RAIZ / "product/backend/app/main.py"
_SIDECAR = _RAIZ / "deploy/fase4/sidecar_serve.py"

print("F2d · LOS TRES CABLES")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 y 2 · EL LIFESPAN LOS LLAMA DE VERDAD (espiados)")

sys.path.insert(0, str(_RAIZ / "qa" / "lib"))

import app.main as M                                        # noqa: E402
import higiene_store as _HIG                                # noqa: E402
from cli_brain import lifecycle as LC                       # noqa: E402
from cli_brain import registro as REG                       # noqa: E402

# [H1] El `mkdtemp` de `base.invoke` se borra solo; el ESPEJO que el CLI crea en
# `~/.claude/projects/` no. Barrido al salir, y sólo de lo que apareció acá.
_HIG.vigilar()

_llamadas: list = []
_barrer, _stop = REG.barrer_cli_al_arrancar, LC.stop_managed_service


def _espia_barrer(**kw):
    _llamadas.append("barrer")
    return {"anotados": 0, "matados": 0, "ajenos": 0, "sin_pid": 0, "motivos": {}}


def _espia_stop():
    _llamadas.append("stop")
    return 0


REG.barrer_cli_al_arrancar = _espia_barrer
LC.stop_managed_service = _espia_stop
try:
    async def _correr():
        async with M._lifespan(M.app):
            ok("barrer" in _llamadas, "el ARRANQUE llamó al barrido de CLI")
            ok("stop" not in _llamadas, "…y todavía no al cierre (va en el finally)")
    asyncio.run(_correr())
    ok("stop" in _llamadas, "el CIERRE llamó a `stop_managed_service`")
    ok(_llamadas.index("barrer") < _llamadas.index("stop"),
       f"en ese orden: {_llamadas}")
finally:
    REG.barrer_cli_al_arrancar, LC.stop_managed_service = _barrer, _stop

# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 y 2 · Y NO TUMBAN EL BOOT SI EXPLOTAN")


def _explota(*a, **k):
    raise RuntimeError("boom a propósito")


REG.barrer_cli_al_arrancar = _explota
LC.stop_managed_service = _explota
try:
    async def _correr2():
        async with M._lifespan(M.app):
            pass
    asyncio.run(_correr2())
    ok(True, "con las dos explotando, el lifespan arranca y cierra igual")
except Exception as e:                                      # noqa: BLE001
    ok(False, "el lifespan se cayó por un cable de cli_brain", f"{type(e).__name__}: {e}")
finally:
    REG.barrer_cli_al_arrancar, LC.stop_managed_service = _barrer, _stop

# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 y 2 · EN EL PUNTO EXACTO QUE F2d PIDIÓ")
_src = _MAIN.read_text()
_arbol = ast.parse(_src)
_fn = next(n for n in ast.walk(_arbol)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and n.name == "_lifespan")


def _linea(aguja: str) -> int:
    for i, l in enumerate(_src.splitlines(), 1):
        if aguja in l:
            return i
    return -1


l_dueno = _linea("barrer_al_arrancar()")
l_barrer = _linea("from cli_brain.registro import barrer_cli_al_arrancar")
l_purge = _linea("purge_task = (asyncio.create_task")
l_apagar = _linea('apagar_todo(motivo="cierre del sidecar")')
l_stop = _linea("from cli_brain.lifecycle import stop_managed_service")
print(f"      dueño:{l_dueno} · barrido cli:{l_barrer} · purge:{l_purge} · "
      f"apagar_todo:{l_apagar} · stop cli:{l_stop}")
ok(0 < l_dueno < l_barrer < l_purge,
   "el barrido de CLI va DESPUÉS del dueño y ANTES de `purge_task=`")
ok(0 < l_apagar < l_stop, "el cierre de CLI va junto al `apagar_todo` del dueño")

# ── que estén FUERA del `if db_ok`: un CLI huérfano no depende de la base ──────────
_dentro_de_db_ok = False
for nodo in ast.walk(_fn):
    if isinstance(nodo, ast.If) and ast.dump(nodo.test).find("db_ok") >= 0:
        ini, fin = nodo.lineno, (nodo.end_lineno or nodo.lineno)
        if ini <= l_barrer <= fin:
            _dentro_de_db_ok = True
ok(not _dentro_de_db_ok,
   "el barrido está FUERA del `if db_ok` — dejar vivo un CLI porque la DB está rota sería "
   "sumar una fuga a un fallo")

# ══════════════════════════════════════════════════════════════════════════════════
seccion("3 · EL FORCE-EXIT, sobre el código (no se puede ejercer en proceso)")
_ssrc = _SIDECAR.read_text()
_sarbol = ast.parse(_ssrc)
ok("stop_managed_service_detallado()" in _ssrc,
   "el `finally` usa el cierre DETALLADO, que es el que nombra el paso colgado")
ok('parte.get("colgado")' in _ssrc, "y mira `colgado`")
ok("os._exit(0)" in _ssrc,
   "fuerza la salida con `os._exit`, no con `sys.exit`: si un paso quedó colgado hay un "
   "hilo no-daemon y una salida limpia esperaría por él")

# el `os._exit` tiene que estar DENTRO del `if colgado`, no suelto
_forzado_condicionado = False
for nodo in ast.walk(_sarbol):
    if isinstance(nodo, ast.If) and "colgado" in ast.dump(nodo.test):
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "_exit" for n in ast.walk(nodo)):
            _forzado_condicionado = True
ok(_forzado_condicionado,
   "y SÓLO si quedó colgado: un `os._exit` incondicional mataría todo cierre limpio")

print(f"\n{'TODO VERDE' if _fallos == 0 else str(_fallos) + ' FALLO(S)'}")
sys.exit(0 if _fallos == 0 else 1)
