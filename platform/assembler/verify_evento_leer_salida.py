#!/usr/bin/env python3
"""verify_evento_leer_salida.py — EL EVENTO DE LA VÍA DE RECUPERACIÓN LLEGA AL DISCO.

    product/backend/.venv/bin/python platform/assembler/verify_evento_leer_salida.py
    …                                                                        --caer

POR QUÉ EXISTE. El truncado de la Sala funciona —el modelo pide el resto y entrega— pero
su evento se descartaba entero:

    space_emitter: evento DESCARTADO type='aleph_leer_salida' — no llegó al disco y la
                   superficie no lo va a ver

NO era el guard de `EVENT_TYPES`: el tipo está declarado. Era que el emisor fijaba **`id`**,
y `events_replay._RESERVED = ("id",)` — ese campo lo asigna la lib y el caller lo tiene
prohibido. `EventLog.append` levantaba `EventValidationError` y el `try/except` del emisor
se lo comía. Resultado: la vía andaba para el modelo y era INAUDITABLE, justo lo contrario
de lo que promete el comentario que la declara.

QUÉ MIDE, y por qué así:
  A · el evento REAL —el que arma `recipe_assembler`— se persiste y se puede releer
  B · el `sid` de la salida sobrevive el viaje y se lee de vuelta
  C · la lib SIGUE rechazando un `id` fijado por el caller (no se ablandó la regla:
      lo que cambió es el emisor, no el contrato)
  D · el emisor de verdad (`router._make_space_emitter`) no se traga nada

⚠️ EL EVENTO NO SE ESCRIBE A MANO ACÁ: se extrae del fuente de `recipe_assembler` con AST,
así que si alguien vuelve a poner `"id"` la vara se pone roja sola. Una vara que copia el
dict a mano mide su propia copia, no el código.

`--caer` monta el MUTANTE: el evento vuelve a llevar `id`. A y B tienen que ponerse ROJAS.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_AQUI))
for _p in (os.path.join(_REPO, "platform", "flywheel"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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


import events_replay as ER  # noqa: E402

# ── EL EVENTO, SACADO DEL FUENTE ─────────────────────────────────────────────────
# Se busca el literal que se le pasa a `on_event` con type == "aleph_leer_salida" y se
# leen SUS CLAVES. No se reconstruye a mano: el punto es que la vara vea lo que el código
# manda de verdad.
_FUENTE = os.path.join(_AQUI, "recipe_assembler.py")


def claves_del_evento():
    arbol = ast.parse(open(_FUENTE, encoding="utf-8").read())
    for n in ast.walk(arbol):
        if not isinstance(n, ast.Dict):
            continue
        for k, v in zip(n.keys, n.values):
            if (isinstance(k, ast.Constant) and k.value == "type"
                    and isinstance(v, ast.Constant) and v.value == "aleph_leer_salida"):
                return [kk.value for kk in n.keys if isinstance(kk, ast.Constant)]
    return None


CLAVES = claves_del_evento()
if CLAVES is None:
    print("  🔴 no encontré el evento en recipe_assembler.py — ¿se movió?")
    sys.exit(1)
print(f"  · claves que el código manda: {CLAVES}")

if CAER:
    CLAVES = ["id" if c == "sid" else c for c in CLAVES]
    print(f"  ⚠️  MUTANTE: el evento vuelve a llevar `id` → {CLAVES}\n")

SID = "t7"


def evento():
    """El evento con las claves REALES del código y valores del caso medido."""
    e = {"type": "aleph_leer_salida", "kind": "aleph", "chars": 1234, "turn": 2}
    for c in CLAVES:
        if c in ("sid", "id"):
            e[c] = SID
    return e


print("\n── A · el evento se PERSISTE (antes se descartaba entero) ──")
_d = tempfile.mkdtemp(prefix="aleph-leer-salida-")
_p = os.path.join(_d, "events.jsonl")
log = ER.EventLog(_p)
_err = None
try:
    log.append(dict(evento(), space_id="space-x"))
except Exception as e:                                     # noqa: BLE001
    _err = e
ok(_err is None, "A1 · `EventLog.append` lo acepta", f"{type(_err).__name__}: {_err}")

_filas = [json.loads(l) for l in open(_p).read().splitlines() if l.strip()] if _err is None else []
ok(len(_filas) == 1, "A2 · y queda UNA fila en el disco", f"{len(_filas)} filas")

print("\n── B · el `sid` de la salida sobrevive el viaje ──")
_f = _filas[0] if _filas else {}
ok(_f.get("sid") == SID, "B1 · se relee el id de la salida que el modelo pidió",
   f"sid={_f.get('sid')!r} (fila: {sorted(_f)})")
ok(isinstance(_f.get("id"), int) and _f["id"] >= 1,
   "B2 · y el `id` es el que asignó la LIB, monotónico", f"id={_f.get('id')!r}")

print("\n── C · el contrato NO se ablandó: un `id` del caller se sigue rechazando ──")
_err2 = None
try:
    ER.EventLog(os.path.join(_d, "otro.jsonl")).append(
        {"type": "aleph_leer_salida", "space_id": "space-x", "id": "t9"})
except Exception as e:                                     # noqa: BLE001
    _err2 = e
ok(_err2 is not None and "reservado" in str(_err2).lower(),
   "C1 · fijar `id` sigue siendo EventValidationError", f"{_err2!r}")

print("\n── D · el emisor de verdad no se traga el rechazo en silencio ──")
_router = os.path.join(_REPO, "product", "backend", "app", "phase1", "router.py")
_src = open(_router, encoding="utf-8").read()
ok("evento DESCARTADO" in _src,
   "D1 · `_make_space_emitter` LOGUEA lo que descarta (antes era `pass` mudo)")

print(f"\n{_V} verdes · {_R} rojas" + ("   [MUTANTE]" if CAER else ""))
sys.exit(1 if _R else 0)
