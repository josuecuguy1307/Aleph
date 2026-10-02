#!/usr/bin/env python3
"""verify_sobre_del_turno — ¿el sobre del turno cruza el borde, y sólo hacia adentro?

QUÉ MIDE, Y CONTRA QUÉ ESTADO
------------------------------
El sobre de un turno son dos datos que tienen que sobrevivir dos saltos HTTP:

    X-Aleph-Turno-Id        el mismo id para el pedido y todos sus reintentos
    X-Aleph-Deadline-Epoch  el mismo instante de corte para todos ellos

MEDIDO 2026-08-15 contra la `.app` instalada, el salto del borde los TIRABA:

    directo a :8926 con el sobre    → turno_id propio, remaining_s = 24,98   ✔
    por el borde con el MISMO sobre → turno_id inventado, remaining_s = 180,0 ✘

y la consecuencia, medida en el turno Apple: sus 5 ejecuciones del CLI recibieron
`remaining_s = 180,0` cada una. El techo no era 180 s por turno sino por ejecución.

POR QUÉ ESTA VARA PUEDE DAR ROJO
---------------------------------
Tiene los dos brazos, no sólo el que confirma: comprueba que el sobre SALE hacia el server
BYO-CLI y que NO sale hacia un proveedor remoto. Sin el segundo brazo, «mandarle el sobre a
todo el mundo» pasaría verde — y ése es justo el error que no queremos.
Probada cayendo: con el `assembler.py` anterior a la obra, el caso 5 falla.

Uso:  python3 qa/verify_sobre_del_turno.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "platform"))
sys.path.insert(0, str(_RAIZ / "platform" / "assembler"))

import sobre_turno                                            # noqa: E402
import assembler as _asm                                      # noqa: E402

_FALLOS: list[str] = []


def check(titulo: str, ok: bool, evidencia: str = "") -> None:
    print("   %s %s%s" % ("✅" if ok else "❌", titulo,
                          ("   " + evidencia) if evidencia else ""))
    if not ok:
        _FALLOS.append(titulo)


def _pedido_a(base_url: str) -> tuple:
    """`(cabeceras, cuerpo)` REALES del `urllib.Request` que saldría a ese destino."""
    req, _timeout, _endpoint = _asm._preparar_pedido(
        [{"role": "user", "content": "hola"}], [], base_url, "codex-cli", "",
        256, 0.0)
    # urllib normaliza los nombres a Capitalized-lower; se compara sin distinguir.
    return ({k.lower(): v for k, v in req.headers.items()},
            json.loads(req.data.decode()))


def _cabeceras_del_pedido(base_url: str) -> dict:
    return _pedido_a(base_url)[0]


CLI_BRAIN = "http://127.0.0.1:8926/v1"
REMOTO = "https://api.openai.com/v1"


def main() -> int:
    print("verify_sobre_del_turno · ¿el sobre cruza el borde, y sólo hacia adentro?\n")

    print("── A · el sobre puesto y sacado ──")
    tok = sobre_turno.poner("attempt-1", 1_800_000_000.25)
    check("1 · con sobre puesto, las dos cabeceras salen hacia el CLI",
          sobre_turno.cabeceras(True) == {
              "X-Aleph-Turno-Id": "attempt-1",
              "X-Aleph-Deadline-Epoch": "1800000000.250000"},
          str(sobre_turno.cabeceras(True)))
    check("2 · el mismo sobre NO sale hacia un destino que no es el nuestro",
          sobre_turno.cabeceras(False) == {}, str(sobre_turno.cabeceras(False)))
    sobre_turno.sacar(tok)
    check("3 · sacado el sobre, no queda nada para el pedido siguiente",
          sobre_turno.cabeceras(True) == {}, str(sobre_turno.cabeceras(True)))

    print("\n── B · lo que no es un sobre, se descarta entero ──")
    tok = sobre_turno.poner("id\r\nX-Inyectada: 1", float("inf"))
    check("4 · un id con CR/LF y un deadline no finito no viajan",
          sobre_turno.cabeceras(True) == {}, str(sobre_turno.cabeceras(True)))
    sobre_turno.sacar(tok)

    print("\n── C · el pedido de verdad, tal como sale por urllib ──")
    tok = sobre_turno.poner("attempt-9", 1_700_000_000.5)
    cab_cli = _cabeceras_del_pedido(CLI_BRAIN)
    cab_rem = _cabeceras_del_pedido(REMOTO)
    sobre_turno.sacar(tok)
    check("5 · el pedido al server BYO-CLI (:8926) LLEVA el sobre",
          cab_cli.get("x-aleph-turno-id") == "attempt-9"
          and cab_cli.get("x-aleph-deadline-epoch") == "1700000000.500000",
          str({k: v for k, v in cab_cli.items() if k.startswith("x-aleph")}))
    check("6 · el pedido a un proveedor REMOTO no lo lleva",
          not any(k.startswith("x-aleph") for k in cab_rem),
          str({k: v for k, v in cab_rem.items() if k.startswith("x-aleph")}) or "{}")

    print("\n── D · la CONVERSACIÓN viaja en el CUERPO, que es donde el server la lee ──")
    tok = sobre_turno.poner("attempt-9", None, "finanzas:d30b89aa0830")
    cuerpo_cli = _pedido_a(CLI_BRAIN)[1]
    cuerpo_rem = _pedido_a(REMOTO)[1]
    sobre_turno.sacar(tok)
    check("8 · el pedido al `:8926` lleva `sesion` en el cuerpo",
          cuerpo_cli.get("sesion") == "finanzas:d30b89aa0830", str(cuerpo_cli.get("sesion")))
    check("9 · el pedido remoto NO lleva la conversación",
          "sesion" not in cuerpo_rem, str(cuerpo_rem.get("sesion")))

    print("\n── E · sin sobre, el pedido es el de siempre ──")
    cab_sin, cuerpo_sin = _pedido_a(CLI_BRAIN)
    check("10 · sin sobre puesto, ni cabecera nueva ni `sesion` en el cuerpo",
          not any(k.startswith("x-aleph") for k in cab_sin) and "sesion" not in cuerpo_sin,
          str({k: v for k, v in cab_sin.items() if k.startswith("x-aleph")}) or "{}")

    print("\n══ VEREDICTO ══")
    if _FALLOS:
        for f in _FALLOS:
            print("  ❌ %s" % f)
        return 1
    print("  ✅ el sobre cruza hacia el CLI, no se filtra afuera, y no sobrevive al pedido.")
    print("  ⏳ LO QUE ESTA VARA NO MIDE: que el `:8926` lo HONRE. Eso es el binario, y se")
    print("     mide con la `.app` instalada (medido el 2026-08-15: remaining_s = 24,98).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
