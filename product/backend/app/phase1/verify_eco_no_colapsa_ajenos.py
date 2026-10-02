#!/usr/bin/env python3
"""verify_eco_no_colapsa_ajenos.py — EL SINGLE-FLIGHT SÓLO COLAPSA GEMELOS DE VERDAD.

    product/backend/.venv/bin/python \\
        product/backend/app/phase1/verify_eco_no_colapsa_ajenos.py [--caer]

POR QUÉ EXISTE. Antes de prender `ALEPH_ECO_AUXILIAR_WS` **por default en el código** hay
una pregunta que hay que contestar midiendo, no razonando: *¿puede el eco colapsar dos
pedidos que NO eran gemelos?* Si la respuesta fuera «sí en algún caso», la perilla tiene
que quedar en el launcher y no en el código.

La respuesta se mide acá, con hilos de verdad —el par llega CONCURRENTE, que es el caso
real: la gemela entra con la primera todavía en vuelo— y contando **llamadas al modelo**,
no salidas.

⚠️ NO SE CUENTAN RESPUESTAS, SE CUENTAN LLAMADAS. Contar salidas daría 2 en los dos casos
y no distinguiría nada: el eco devuelve dos respuestas igual. Lo que cambia es cuántas
veces se tocó el modelo, y por eso el doble incrementa un contador bajo lock.

`--caer` monta el MUTANTE: la clave deja de mirar los mensajes (una implementación
descuidada plausible). Entonces DOS PEDIDOS DISTINTOS se colapsan y B1/B2 se ponen rojas.
Si el mutante no las tumba, esta vara no mide nada.
"""
from __future__ import annotations

import os
import sys
import threading
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(os.path.dirname(_AQUI))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

CAER = "--caer" in sys.argv
_V = _R = 0


def ok(cond, etiqueta, detalle=""):
    global _V, _R
    if cond:
        _V += 1
        print(f"  🟢 {etiqueta}")
    else:
        _R += 1
        print(f"  🔴 {etiqueta}" + (f"   ← {detalle}" if detalle else ""))


from app.phase1 import llamada_repetida as LR  # noqa: E402

os.environ["ALEPH_ECO_AUXILIAR_WS"] = "ciencia"

if CAER:
    _real = LR.clave_de
    LR.clave_de = lambda ws, messages, mt, t: "clave-que-ignora-los-mensajes"
    print("  ⚠️  MUTANTE: la clave ya no mira los mensajes\n")

MSGS = [{"role": "system", "content": "You are a title generator."},
        {"role": "user", "content": "Generate a title for this conversation:"}]


class Modelo:
    """Cuenta LLAMADAS (no salidas) y tarda, para que la gemela llegue en vuelo."""

    def __init__(self, demora=0.35, revienta=False):
        self.n = 0
        self._lock = threading.Lock()
        self.demora, self.revienta = demora, revienta

    def __call__(self):
        with self._lock:
            self.n += 1
            yo = self.n
        time.sleep(self.demora)
        if self.revienta:
            raise RuntimeError("el modelo se cayó")
        return {"content": "titulo-%d" % yo, "tool_calls": [], "model": "m",
                "usage": None, "cost_events": []}


def correr(pedidos, modelo, gap=0.08):
    """Lanza los pedidos concurrentes, separados por `gap`. Devuelve las salidas."""
    LR._ECOS.clear()
    salidas = [None] * len(pedidos)

    def uno(i, kw):
        salidas[i] = LR.paso(llamar_modelo=modelo, tools=[], **kw)

    hilos = []
    for i, kw in enumerate(pedidos):
        h = threading.Thread(target=uno, args=(i, kw)); h.start(); hilos.append(h)
        time.sleep(gap)
    for h in hilos:
        h.join()
    return salidas


def ped(msgs=None, clave="ciencia:chat-1", mt=None, t=None, ws="ciencia"):
    return {"clave": clave, "workspace": ws, "messages": msgs or MSGS,
            "max_tokens": mt, "temperature": t}


print("── A · DOS GEMELOS CONCURRENTES → UNA sola llamada al modelo ──")
m = Modelo()
s = correr([ped(), ped()], m)
ok(m.n == 1, "A1 · el modelo se llamó UNA vez para dos pedidos idénticos", f"n={m.n}")
ok(all(x is not None for x in s), "A2 · y los DOS pedidos salieron con respuesta")
ok(s[0] and s[1] and s[0].get("content") == s[1].get("content"),
   "A3 · con la MISMA respuesta (la gemela se colgó de la primera)")

print("\n── B · LA PREGUNTA QUE DECIDE: dos pedidos DISTINTOS no se colapsan ──")
otros = [{"role": "system", "content": "You are a title generator."},
         {"role": "user", "content": "Generate a title for this conversation!"}]  # 1 char
m = Modelo()
s = correr([ped(), ped(otros)], m)
ok(m.n == 2, "B1 · un solo carácter distinto ⇒ DOS llamadas al modelo", f"n={m.n}")
ok(s[0] and s[1] and s[0].get("content") != s[1].get("content"),
   "B2 · y cada uno se lleva SU respuesta, no la del otro")

m = Modelo()
s = correr([ped(mt=100), ped(mt=200)], m)
ok(m.n == 2, "B3 · mismos mensajes pero otro `max_tokens` ⇒ DOS llamadas", f"n={m.n}")

m = Modelo()
s = correr([ped(clave="ciencia:chat-1"), ped(clave="ciencia:chat-2")], m)
ok(m.n == 2, "B4 · el mismo prompt en OTRO chat no se colapsa", f"n={m.n}")

m = Modelo()
s = correr([ped(ws="ciencia"), ped(ws="ciencia")], m)
_ecos_ws = len(LR.workspaces_encendidos())
ok(_ecos_ws == 1, "B5 · la perilla es por stack, no global", f"{LR.workspaces_encendidos()}")

print("\n── C · una TERCERA idéntica vuelve al modelo (MAX_ECOS = 1) ──")
m = Modelo()
s = correr([ped(), ped(), ped()], m)
ok(m.n == 2, "C1 · tres idénticas ⇒ DOS llamadas: el eco cuesta una vuelta, no la capacidad",
   f"n={m.n}")

print("\n── D · con tools NO hay eco (regla 1: sólo transformaciones de texto) ──")
m = Modelo()
LR._ECOS.clear()
r1 = LR.paso(llamar_modelo=m, tools=[{"type": "function"}], **ped())
r2 = LR.paso(llamar_modelo=m, tools=[{"type": "function"}], **ped())
ok(r1 is None and r2 is None, "D1 · con tools devuelve None: el camino de siempre")
ok(m.n == 0, "D2 · y no llamó al modelo por su cuenta", f"n={m.n}")

print("\n── E · si la PRIMERA se cae, la gemela no se cuelga ni se traga el error ──")
m = Modelo(demora=0.2, revienta=True)
LR._ECOS.clear()
_t0 = time.time()
_errs = []


def _uno():
    try:
        LR.paso(llamar_modelo=m, tools=[], **ped())
    except Exception as e:                                  # noqa: BLE001
        _errs.append(e)


h1 = threading.Thread(target=_uno); h1.start(); time.sleep(0.05)
h2 = threading.Thread(target=_uno); h2.start()
h1.join(timeout=20); h2.join(timeout=20)
_dt = time.time() - _t0
ok(not h1.is_alive() and not h2.is_alive(), "E1 · ninguna quedó colgada", f"{_dt:.1f}s")
ok(_dt < 15, "E2 · y no esperó el ESPERA_S entero", f"{_dt:.1f}s")
ok(len(_errs) == 2, "E3 · el error llega a las DOS, no se traga", f"{len(_errs)} errores")

print("\n── F · fuera de la ventana no hay eco ──")
m = Modelo(demora=0.0)
LR._ECOS.clear()
LR.paso(llamar_modelo=m, tools=[], **ped())
for v in LR._ECOS.values():
    v["ts"] = time.time() - (LR.VENTANA_S + 5)
LR.paso(llamar_modelo=m, tools=[], **ped())
ok(m.n == 2, "F1 · pasada la ventana vuelve al modelo", f"n={m.n}")

print("\n── G · sin la perilla, la pieza no hace absolutamente nada ──")
os.environ["ALEPH_ECO_AUXILIAR_WS"] = ""
m = Modelo(demora=0.0)
LR._ECOS.clear()
ok(LR.paso(llamar_modelo=m, tools=[], **ped()) is None,
   "G1 · apagada devuelve None y no toca el modelo")
ok(m.n == 0, "G2 · cero llamadas", f"n={m.n}")
os.environ["ALEPH_ECO_AUXILIAR_WS"] = "ciencia"

print(f"\n{_V} verdes · {_R} rojas" + ("   [MUTANTE]" if CAER else ""))
sys.exit(1 if _R else 0)
