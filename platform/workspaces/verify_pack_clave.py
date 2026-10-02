#!/usr/bin/env python3
"""verify_pack_clave.py — la vara del pack con proceso único por máquina.

    python3 platform/workspaces/verify_pack_clave.py
    python3 platform/workspaces/verify_pack_clave.py --caer

Mide el defecto MEDIDO contra la `.app` instalada el 2026-08-22:
misma clave → 200 en 16-29 ms · otra clave → 503 «murió al arrancar (exit 0)» con el
pack VIVO. La causa era `_clave` metiendo el `user_id` en la clave de un proceso que es
uno solo por máquina.
"""
from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RAIZ, "platform"))
from workspaces import pack as P                                      # noqa: E402

MUTAR = "--caer" in sys.argv
if MUTAR:
    print("!! MODO --caer: la pieza va MUTADA\n")
    P._clave = lambda ws, user_id, **kw: f"{user_id or '-'}::{ws}"    # ignora `unico`

RES = []
def chk(n, c, d=""):
    RES.append((n, bool(c))); print(f"  [{'VERDE' if c else 'ROJO '}] {n}" + (f"  · {d}" if d else ""))

U1 = "bb374d5f-9ac2-459e-b39c-b5d4c41a7c00"
U2 = "otro-usuario-9999"

print("── A · un pack ÚNICO POR MÁQUINA: todos los usuarios comparten clave ──")
a = P._clave("diseno", U1, unico=True)
b = P._clave("diseno", U2, unico=True)
c = P._clave("diseno", None, unico=True)
chk("A1: dos usuarios distintos dan la MISMA clave", a == b, f"{a!r} == {b!r}")
chk("A2: y sin usuario (la carrera de hidratación) también", a == c, f"{a!r} == {c!r}")
chk("A3: la clave no lleva el usuario", U1 not in a and U2 not in a, a)

print("\n── B · un pack normal CONSERVA la separación por usuario ──")
d1 = P._clave("ciencia", U1)
d2 = P._clave("ciencia", U2)
d3 = P._clave("ciencia", None)
chk("B1: dos usuarios dan claves DISTINTAS", d1 != d2, f"{d1!r} != {d2!r}")
chk("B2: y sin usuario es otra más", d1 != d3 and d2 != d3)
chk("B3: no se rompió el formato de siempre", d1 == f"{U1}::ciencia", d1)

print("\n── C · `exit 0` NO se anuncia como muerte (EJECUTANDO la rama) ──")
# Se corre el código de verdad: un binario que sale 0 al instante y una URL que no
# contesta. Antes esta vara comparaba TEXTO FUENTE y daba rojo por mi propio comentario:
# medía el comentario, no el código.
def _correr(cmd):
    srv = P.ServidorDePack("pack:prueba", cmd, [], env={}, rpc_timeout=2, cwd="/tmp")
    srv.url, srv.salud = "http://127.0.0.1:1", "/"
    ok = srv.start()
    return ok, srv._detalle, srv._exit_code

ok0, det0, code0 = _correr("/usr/bin/true")     # sale 0
chk("C1: exit 0 sigue siendo un arranque fallido (no se finge vivo)", ok0 is False, f"ok={ok0}")
chk("C2: y NO dice «se murió»", "se murió" not in det0, det0[:110])
chk("C3: dice que salió LIMPIO y qué significa",
    "salió limpio (exit 0)" in det0 and "compartirlo, no relanzarlo" in det0)
chk("C4: el código de salida se declara", code0 == 0, f"exit={code0!r}")

ok1, det1, code1 = _correr("/usr/bin/false")    # sale 1
chk("C5: una muerte de verdad SÍ dice «se murió»", "se murió al arrancar" in det1, det1[:90])
chk("C6: con su código", "(exit 1)" in det1, det1[:90])

print("\n── D · apagar/salir encuentran la clave AUNQUE sea la única ──")
P._PUERTOS.clear(); P._PRESTAMOS.clear(); P._GRACIAS.clear()
P._PUERTOS["-::diseno"] = 4321          # como lo registró un pack único
chk("D1: con la clave única registrada, `_clave_existente` la encuentra",
    P._clave_existente("diseno", U1) == "-::diseno", P._clave_existente("diseno", U1))
P._PUERTOS.clear(); P._PUERTOS[f"{U1}::ciencia"] = 5555
chk("D2: y con la del usuario registrada, devuelve ÉSA",
    P._clave_existente("ciencia", U1) == f"{U1}::ciencia")
chk("D3: sin nada registrado, cae en la del usuario (comportamiento de antes)",
    P._clave_existente("legal", U1) == f"{U1}::legal")
P._PUERTOS.clear()

print("\n" + "=" * 64)
v = sum(1 for _, o in RES if o); print(f"VERDES {v} / {len(RES)}")
rojas = [n for n, o in RES if not o]
for n in rojas: print(f"  ROJO · {n}")
if MUTAR:
    print(f"\nPRUEBA DE CAÍDA: {'la vara SE PUSO ROJA — mide' if rojas else 'siguió verde — NO MIDE'}")
    sys.exit(0 if rojas else 1)
sys.exit(0 if not rojas else 1)
