#!/usr/bin/env python3
"""verify_pool.py — el ciclo de vida del pool, con dobles. Sin red, sin CLIs.

Lo que asserta es lo que decide si el broker se puede prender:
  P1 · comparte con la MISMA clave y NO comparte con otro dueño / otra config
  P2 · el techo desaloja por LRU y **jamás** un proceso prestado
  P3 · la ociosidad cosecha, y un proceso prestado NO envejece
  P4 · un proceso que se muere solo se saca del pool y no se le presta a nadie
  P5 · el cruce de dueño en una Session levanta, no pasa callado
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from assembler.cli_brain.broker.pool import Pool, BrokerError       # noqa: E402
from assembler.cli_brain.broker.vocabulario import (                # noqa: E402
    Capabilities, Harness, huella_de_config)

_FALLOS, _OK = [], 0


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1
        print(f"  ✅ {t}")
    else:
        _FALLOS.append(t)
        print(f"  ❌ {t}" + (f"\n      → {d}" if d else ""))


CAPS_MULTI = Capabilities(True, True, False, True, "cache_read_input_tokens", "x")
CAPS_SOLO = Capabilities(False, True, False, True, "cache_read_input_tokens", "x")


class _Doble:
    """Un adaptador que no spawnea nada. `vivo=False` simula el que se murió solo."""
    creados = 0
    cerrados = 0

    def __init__(self, vivo=True):
        self._vivo = vivo
        self.proc = type("P", (), {"pid": 1000 + _Doble.creados})()
        _Doble.creados += 1

    def vive(self):
        return self._vivo

    def cerrar(self):
        _Doble.cerrados += 1
        self._vivo = False


def _h(dueno="ana", cfg=None, pid="grok_cli"):
    return Harness(pid, dueno, huella_de_config(cfg or {"m": 1}))


def _pool(tmp, **kw):
    return Pool(libro=Path(tmp) / "libro.jsonl", **kw)


def p1(tmp):
    print("\n[P1] comparte con la misma clave; no comparte con otro dueño ni otra config")
    P = _pool(tmp)
    a = P.pedir(harness=_h(), caps=CAPS_MULTI, clave_conversacion="c1",
                fabricar=lambda: _Doble())
    b = P.pedir(harness=_h(), caps=CAPS_MULTI, clave_conversacion="c2",
                fabricar=lambda: _Doble())
    ok(a.pid == b.pid, "misma clave (multiplexa) → MISMO proceso para dos charlas")
    a.soltar(); b.soltar()
    c = P.pedir(harness=_h(dueno="beto"), caps=CAPS_MULTI, clave_conversacion="c1",
                fabricar=lambda: _Doble())
    ok(c.pid != a.pid, "otro DUEÑO → otro proceso")
    c.soltar()
    d = P.pedir(harness=_h(cfg={"m": 2}), caps=CAPS_MULTI, clave_conversacion="c1",
                fabricar=lambda: _Doble())
    ok(d.pid != a.pid, "otra CONFIG → otro proceso")
    d.soltar()
    e = P.pedir(harness=_h(), caps=CAPS_SOLO, clave_conversacion="cX",
                fabricar=lambda: _Doble())
    f = P.pedir(harness=_h(), caps=CAPS_SOLO, clave_conversacion="cY",
                fabricar=lambda: _Doble())
    ok(e.pid != f.pid, "harness que NO multiplexa → una charla, un proceso")
    e.soltar(); f.soltar()
    P.apagar_todo()


def p2(tmp):
    print("\n[P2] el techo desaloja por LRU y JAMÁS un proceso prestado")
    P = _pool(tmp, max_vivos=2)
    a = P.pedir(harness=_h(dueno="u1"), caps=CAPS_MULTI, clave_conversacion="c",
                fabricar=lambda: _Doble())
    a.soltar()
    time.sleep(0.02)
    b = P.pedir(harness=_h(dueno="u2"), caps=CAPS_MULTI, clave_conversacion="c",
                fabricar=lambda: _Doble())
    b.soltar()
    c = P.pedir(harness=_h(dueno="u3"), caps=CAPS_MULTI, clave_conversacion="c",
                fabricar=lambda: _Doble())
    ok(P.eventos["desalojos_lru"] == 1, "entró el tercero y se desalojó UNO",
       str(P.eventos))
    ok(len(P.estado()["vivos"]) == 2, "el techo se respeta", str(P.estado()["vivos"]))
    c.soltar()
    # ahora los dos prestados y un tercero pidiendo: NO se desaloja, se declara lleno
    P2_ = _pool(tmp, max_vivos=1)
    x = P2_.pedir(harness=_h(dueno="v1"), caps=CAPS_MULTI, clave_conversacion="c",
                  fabricar=lambda: _Doble())
    lleno = False
    try:
        P2_.pedir(harness=_h(dueno="v2"), caps=CAPS_MULTI, clave_conversacion="c",
                  fabricar=lambda: _Doble())
    except BrokerError:
        lleno = True
    ok(lleno, "con todos PRESTADOS el pool dice que está lleno (no mata a nadie)")
    ok(x.pid in [f["pid"] for f in P2_.estado()["vivos"]],
       "y el prestado sigue vivo — un turno de otro dueño no mata el turno de nadie")
    x.soltar()
    P.apagar_todo(); P2_.apagar_todo()


def p3(tmp):
    print("\n[P3] la ociosidad cosecha; un proceso PRESTADO no envejece")
    P = _pool(tmp, ociosidad_s=0.4)
    a = P.pedir(harness=_h(dueno="w1"), caps=CAPS_MULTI, clave_conversacion="c",
                fabricar=lambda: _Doble())
    # prestado: el reloj no corre
    time.sleep(1.2)
    ok(len(P.estado()["vivos"]) == 1, "prestado → NO lo cosecha la ociosidad",
       str(P.estado()))
    a.soltar()
    fin = time.monotonic() + 5
    while time.monotonic() < fin and P.estado()["vivos"]:
        time.sleep(0.05)
    ok(not P.estado()["vivos"], "soltado → la ociosidad lo cosecha", str(P.estado()))
    ok(P.eventos["cerrados_por_ociosidad"] >= 1, "y queda contado", str(P.eventos))
    P.apagar_todo()


def p4(tmp):
    print("\n[P4] el que se murió solo NO se le presta a nadie")
    P = _pool(tmp)
    doble = _Doble()
    a = P.pedir(harness=_h(dueno="z1"), caps=CAPS_MULTI, clave_conversacion="c",
                fabricar=lambda: doble)
    a.soltar()
    doble._vivo = False                      # se murió solo, sin avisar
    nuevo = _Doble()
    b = P.pedir(harness=_h(dueno="z1"), caps=CAPS_MULTI, clave_conversacion="c",
                fabricar=lambda: nuevo)
    ok(b.pid == nuevo.proc.pid, "el pool detectó el muerto y levantó otro",
       f"presto pid={b.pid} viejo={doble.proc.pid}")
    ok(P.eventos["muertes"] >= 1, "y lo contó como muerte", str(P.eventos))
    b.soltar()
    P.apagar_todo()


def p5(tmp):
    print("\n[P5] un cruce de dueño en la Session LEVANTA, no pasa callado")
    P = _pool(tmp)
    a = P.pedir(harness=_h(dueno="ana"), caps=CAPS_MULTI, clave_conversacion="cc",
                fabricar=lambda: _Doble())
    a.soltar()
    # el mismo proceso, pero alguien pide la MISMA conversación con otro dueño. La clave
    # del pool ya lo separaría; esto es el cinturón de adentro.
    vivo = list(P._vivos.values())[0]
    salto = False
    try:
        P._sesion(vivo, _h(dueno="beto"), "cc")
    except BrokerError:
        salto = True
    ok(salto, "pedir la conversación de otro dueño levanta BrokerError")
    P.apagar_todo()


def main() -> int:
    import tempfile
    tmp = tempfile.mkdtemp(prefix="verify-pool-")
    print("=" * 74)
    print("VERIFY POOL — el ciclo de vida, con dobles")
    print("=" * 74)
    for f in (p1, p2, p3, p4, p5):
        f(tmp)
    print("\n" + "-" * 74)
    print(f"{_OK} verdes · {len(_FALLOS)} rojas")
    for f in _FALLOS:
        print(f"   ROJA: {f}")
    return 1 if _FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
