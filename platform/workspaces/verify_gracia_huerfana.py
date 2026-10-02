#!/usr/bin/env python3
"""verify_gracia_huerfana.py — LA GRACIA DE UN PACK QUE NUNCA SE TOMÓ NO MATA AL QUE SÍ.

EL DEFECTO, MEDIDO CONTRA LA PANTALLA (2026-08-23, sidecar recién levantado, Diseño):

    ts …143  POST /v1/workspaces/diseno/leave   200   ← la pantalla limpia antes de entrar
    ts …144  POST /v1/workspaces/diseno/enter   200   ← el pack arranca, Electron vivo
    ts …164  (vencen los 20 s de gracia)              ← el pack MUERTO · «Failed to fetch»

La cadena entera está en el comentario de `pack.salir`. En una frase: con el registro
vacío, el `leave` arma la gracia en `usuario::ws`; el `enter` registra el pack en `-::ws`
porque es único por máquina y cancela **la otra**; a los 20 s la gracia huérfana corre,
no encuentra préstamo y llama a `apagar()`, que vuelve a resolver la clave y ahora sí
encuentra la del pack VIVO.

Es un defecto del árbol de code execution que traje (`_clave_existente`), no de la obra de
identidad. Se arregla acá porque bloquea la medición de las cruces.

    python3 platform/workspaces/verify_gracia_huerfana.py
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspaces import pack                                          # noqa: E402

_ROJAS = 0


def ok(cond: bool, titulo: str, detalle: str = "") -> None:
    global _ROJAS
    if not cond:
        _ROJAS += 1
    print(f"  {'✅' if cond else '❌'} {titulo}" + (f"   [{detalle}]" if detalle else ""))


class _PrestamoFalso:
    def __init__(self):
        self.suelto = False

    def soltar(self):
        self.suelto = True


def _limpiar():
    for d in (pack._PRESTAMOS, pack._PUERTOS, pack._GRACIAS):
        d.clear()


APAGADOS: list = []


def main() -> int:
    print("═" * 78)
    print("LA GRACIA HUÉRFANA NO SE LLEVA PUESTO AL PACK VIVO")
    print("═" * 78)
    USUARIO = "bae96eaa-bac7-4bc2-86d4-d459cf6d2813"

    # El apagado real habla con el dueño del ciclo de vida; acá se intercepta para poder
    # ver SI se llamó, que es el hecho que importa.
    real_apagar = pack.apagar

    def _espia(ws, *, user_id=None, motivo=""):
        APAGADOS.append((ws, user_id, motivo))
        return 0
    pack.apagar = _espia
    try:
        # ── A · EL `leave` DE ALGO QUE NUNCA SE TOMÓ ─────────────────────────────────
        print("\nA · un `leave` sobre un registro vacío")
        _limpiar()
        r = pack.salir("diseno", user_id=USUARIO, gracia_s=0.4)
        ok(r.get("causa") == "no_estaba_tomado",
           "A1 · lo dice, no lo hace en silencio", str(r))
        ok(not pack._GRACIAS,
           "A2 · y NO deja ninguna gracia armada", str(list(pack._GRACIAS)))

        # ── B · LA SECUENCIA EXACTA QUE MATÓ EL PACK ─────────────────────────────────
        print("\nB · la secuencia medida: leave (…143) → enter (…144) → 20 s")
        _limpiar()
        APAGADOS.clear()
        pack.salir("diseno", user_id=USUARIO, gracia_s=0.4)        # el leave de la pantalla
        # el `enter` de un pack ÚNICO POR MÁQUINA registra en `-::ws`
        clave_unica = pack._clave("diseno", USUARIO, unico=True)
        pack._PRESTAMOS[clave_unica] = _PrestamoFalso()
        pack._PUERTOS[clave_unica] = 51555
        time.sleep(0.9)                                            # vence la gracia
        ok(not APAGADOS,
           "B1 · pasada la gracia, el pack VIVO sigue vivo: nadie llamó a `apagar`",
           str(APAGADOS))
        ok(pack._PRESTAMOS.get(clave_unica) is not None,
           "B2 · y su préstamo sigue en pie", clave_unica)

        # ── C · LA GRACIA DE VERDAD SIGUE FUNCIONANDO ────────────────────────────────
        # Si la guarda apagara la gracia legítima, el arreglo sería peor que el defecto.
        print("\nC · la gracia LEGÍTIMA no se tocó")
        _limpiar()
        APAGADOS.clear()
        pack._PRESTAMOS[clave_unica] = _PrestamoFalso()
        pack._PUERTOS[clave_unica] = 51555
        r = pack.salir("diseno", user_id=USUARIO, gracia_s=0.4)
        ok(r.get("apagado") is False and r.get("gracia_s") == 0.4,
           "C1 · un `leave` sobre un pack tomado SÍ arma la gracia", str(r))
        time.sleep(0.9)
        ok(len(APAGADOS) == 1 and APAGADOS[0][0] == "diseno",
           "C2 · y al vencer, apaga — el pack que nadie volvió a tomar se va", str(APAGADOS))

        # ── D · VOLVER A ENTRAR DENTRO DE LA GRACIA LA CANCELA ───────────────────────
        print("\nD · volver a entrar dentro de la gracia")
        _limpiar()
        APAGADOS.clear()
        pack._PRESTAMOS[clave_unica] = _PrestamoFalso()
        pack._PUERTOS[clave_unica] = 51555
        pack.salir("diseno", user_id=USUARIO, gracia_s=0.6)
        pack._PRESTAMOS[clave_unica] = _PrestamoFalso()             # el `enter` que vuelve
        time.sleep(1.0)
        ok(not APAGADOS,
           "D1 · el que volvió a entrar no se apaga al vencer la gracia", str(APAGADOS))
    finally:
        pack.apagar = real_apagar
        _limpiar()
        for t in list(threading.enumerate()):
            if isinstance(t, threading.Timer):
                t.cancel()

    print("\n" + "─" * 78)
    print(f"ROJAS: {_ROJAS}")
    return 1 if _ROJAS else 0


if __name__ == "__main__":
    raise SystemExit(main())
