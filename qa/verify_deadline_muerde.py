#!/usr/bin/env python3
"""verify_deadline_muerde — ¿el deadline corta a un proceso que EMITE, o sólo al mudo?

POR QUÉ EXISTE
---------------
El 2026-08-16 se levantó esta sospecha, desde el registro de eventos:

    «Cada spawn arranca con remaining_s: 180 y corrió 15 minutos sin que el deadline lo
     tocara. Sólo decrementa en los silencios. Un proceso que emite sin parar no tiene
     deadline efectivo: puede correr indefinidamente.»

**Se midió, y es falsa.** El lector (`_run_streaming`) recalcula `restante_total` en CADA
vuelta del `while`, no sólo cuando la cola queda vacía; una línea que llega no repone
presupuesto, sólo evita el evento de silencio. Medido con procesos de verdad:

    EMITE sin parar (una línea cada 0,05 s), deadline 3 s  → cortado a los 3,01 s
    MUDO del todo,                           deadline 3 s  → cortado a los 3,01 s

LO QUE SÍ PASÓ, Y ES OTRA COSA: LA MÁQUINA DURMIÓ
--------------------------------------------------
Los tres procesos «largos» del registro, con sus dos relojes puestos uno al lado del otro
(los eventos guardan `ts` de pared y `mono` monotónico, que es justo lo que permitió
zanjarlo en dos minutos):

    turno                  pared        monotónico    diferencia   corte
    chatcmpl-95ab18fd599c  10.151,0 s      180,4 s     9.970,7 s   deadline  ← cortó BIEN
    chatcmpl-3af50f5a3000     906,1 s        5,2 s       900,9 s   salió solo
    chatcmpl-8b0244e31172     906,9 s        6,3 s       900,6 s   salió solo

El primero se cortó **exactamente en su presupuesto** (180,4 s de reloj monotónico); lo que
duró 2 h 49 fue la PARED, porque `time.monotonic()` no avanza mientras macOS duerme. Los
otros dos ni siquiera son largos: son turnos de 5-6 segundos con una siesta en el medio.

**Y la semántica monotónica es la correcta, no un accidente**: el presupuesto de un turno
mide cuánto TRABAJÓ el CLI. Un proceso suspendido no consume cuota ni produce nada, y
matarlo por una siesta de la laptop sería cobrarle al usuario un tiempo que nadie usó.

Esta vara no cambia comportamiento: lo fija, para que la próxima sesión no vuelva a
deducirlo del reloj equivocado.

Uso:  python3 qa/verify_deadline_muerde.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "platform"))

from assembler.cli_brain import base                          # noqa: E402

#: Un hijo que escribe una línea cada `cadencia` segundos, para siempre.
_HIJO_ETERNO = ("import sys,time\n"
                "while True:\n"
                "    sys.stdout.write('linea\\n'); sys.stdout.flush(); time.sleep({c})\n")
#: Un hijo que dice tres cosas y se va solo, mucho antes del deadline.
_HIJO_CORTO = ("import sys\n"
               "for _ in range(3): sys.stdout.write('linea\\n')\n"
               "sys.stdout.flush()\n")

_FALLOS: list[str] = []
DEADLINE = 3.0
#: Margen: el corte es `<= 0` en el `while`, así que llega en la vuelta siguiente.
TOLERANCIA = 1.0


def check(titulo: str, ok: bool, evidencia: str = "") -> None:
    print("   %s %-58s %s" % ("✅" if ok else "❌", titulo, evidencia))
    if not ok:
        _FALLOS.append(titulo)


#: El caso corre en un proceso APARTE con techo de pared. No es ceremonia: si el deadline
#: dejara de cortar, `_run_streaming` con un hijo eterno no falla — se CUELGA, y una vara
#: colgada no es una vara roja, es una vara que no contesta. Con techo, «no cortó» sale
#: como rojo con nombre.
_CASO = """
import subprocess, sys, time
sys.path.insert(0, {raiz!r})
from assembler.cli_brain import base
t0 = time.monotonic()
try:
    r, _st = base._run_streaming([sys.executable, "-c", {fuente!r}],
                                 timeout=600, chunk_timeout=1.0,
                                 deadline_mono=time.monotonic() + {deadline!r})
    print("VIVO %.3f %s" % (time.monotonic() - t0, r.returncode))
except subprocess.TimeoutExpired:
    print("CORTADO %.3f -" % (time.monotonic() - t0))
"""


def correr(fuente: str, deadline: float):
    """Devuelve `(cortado_por_deadline, segundos, returncode)`.

    `cortado=None` significa que NADIE cortó dentro del techo de pared — el estado que la
    sospecha del 2026-08-16 describía."""
    techo = deadline + 8.0
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            [sys.executable, "-c", _CASO.format(raiz=str(_RAIZ / "platform"),
                                                fuente=fuente, deadline=deadline)],
            capture_output=True, text=True, timeout=techo)
    except subprocess.TimeoutExpired:
        return None, time.monotonic() - t0, None
    partes = (r.stdout or "").strip().split()
    if len(partes) != 3:
        return None, time.monotonic() - t0, (r.stderr or "")[-120:]
    return partes[0] == "CORTADO", float(partes[1]), partes[2]


def main() -> int:
    print("verify_deadline_muerde · ¿el reloj corre siempre, o sólo en los silencios?\n")

    print("── A · el que EMITE sin parar (una línea cada 0,05 s) ──")
    cortado, s, _rc = correr(_HIJO_ETERNO.format(c="0.05"), DEADLINE)
    check("1 · lo corta el deadline, no la falta de líneas", cortado is True,
          "%.2f s" % s if cortado is not None else "NADIE LO CORTÓ en %.1f s" % s)
    check("2 · y lo corta EN su presupuesto, no más tarde",
          cortado is True and abs(s - DEADLINE) <= TOLERANCIA,
          "esperado ≈ %.1f s · medido %.2f s" % (DEADLINE, s))

    print("\n── B · el MUDO del todo (el caso que ya sabíamos) ──")
    cortado_m, s_m, _rc = correr(_HIJO_ETERNO.format(c="999"), DEADLINE)
    check("3 · también muere en el deadline, no en el silencio de 1 s",
          cortado_m is True and abs(s_m - DEADLINE) <= TOLERANCIA, "%.2f s" % s_m)

    print("\n── C · el brazo que hace que esta vara pueda dar ROJO ──")
    cortado_c, s_c, rc_c = correr(_HIJO_CORTO, DEADLINE)
    check("4 · el que termina antes NO lo mata nadie (rc=0, sin TimeoutExpired)",
          cortado_c is False and rc_c == "0", "%.2f s · rc=%s" % (s_c, rc_c))

    print("\n── D · los dos relojes, dichos ──")
    print("     El presupuesto se mide en reloj MONOTÓNICO: no avanza mientras la máquina")
    print("     duerme, y eso es deliberado. Medido en el registro: un turno con 180,4 s de")
    print("     monotónico ocupó 10.151 s de pared. Si un número no cierra, comparar pared")
    print("     contra monotónico ANTES de acusar al código.")

    print("\n══ VEREDICTO ══")
    if _FALLOS:
        for f in _FALLOS:
            print("  ❌ %s" % f)
        return 1
    print("  ✅ el reloj corre siempre: emitir no repone presupuesto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
