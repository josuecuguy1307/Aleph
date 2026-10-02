#!/usr/bin/env python3
"""verify_perillas_de_fabrica.py — LO QUE ALEPH ENVÍA PRENDIDO Y LO QUE ENVÍA APAGADO.

    product/backend/.venv/bin/python \\
        product/backend/app/phase1/verify_perillas_de_fabrica.py [--caer]

POR QUÉ EXISTE. Dos perillas se leían de entorno y **nadie las seteaba** —ni el árbol, ni
`build_app.sh`, ni el launcher—, así que su default vacío ganaba y ninguna instalación las
tenía. Una de las dos valía −4,1 % medido y no se estaba realizando en ningún lado.

Esta vara fija LO QUE SE ENVÍA, para que el próximo que toque un default tenga que
tumbarla a propósito:

  ECO AUXILIAR (`ALEPH_ECO_AUXILIAR_WS`)      → PRENDIDO, y sólo en Ciencia
  PLEGADO      (`ALEPH_SALIDAS_DIFERIDAS_WS`) → APAGADO en los siete

⚠️ LA ASERCIÓN QUE MÁS IMPORTA ES LA C. El plegado se puede dejar apagado **porque la vía
de recuperación del truncado de la Sala no depende de él**. Si algún día alguien la
metiera detrás de la perilla, apagarla dejaría a la Sala sin la vía y nadie se enteraría:
el turno sale igual, sólo que el modelo no sabe cómo pedir lo que le cortaron. C lo mide
de verdad —capando una salida y mirando el pie— en vez de creerle a un comentario.

`--caer` monta el MUTANTE: los dos defaults se invierten. A y B tienen que ponerse rojas.
"""
from __future__ import annotations

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(os.path.dirname(_AQUI))
_REPO = os.path.dirname(os.path.dirname(_BACKEND))
for _p in (_BACKEND, os.path.join(_REPO, "platform", "assembler")):
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


# el entorno NO decide acá: se mide el DEFAULT DE FÁBRICA, así que se saca la variable
for _v in ("ALEPH_ECO_AUXILIAR_WS", "ALEPH_SALIDAS_DIFERIDAS_WS"):
    os.environ.pop(_v, None)

from app.phase1 import llamada_repetida as ECO      # noqa: E402
from app.phase1 import salidas_diferidas as SD      # noqa: E402

if CAER:
    ECO.POR_DEFECTO = ""            # el eco vuelve a irse apagado (la deuda original)
    SD.POR_DEFECTO = "sala,ciencia"  # y el plegado se prende sin datos
    print("  ⚠️  MUTANTE: eco APAGADO y plegado PRENDIDO\n")

SIETE = ("sala", "legal", "educacion", "ciencia", "diseno", "finanzas", "oficina")

print("── A · EL ECO AUXILIAR SE ENVÍA PRENDIDO, Y SÓLO EN CIENCIA ──")
_on = ECO.workspaces_encendidos()
ok(_on == {"ciencia"}, "A1 · de fábrica queda prendido exactamente en Ciencia", f"{_on}")
ok(ECO.encendido_para("ciencia"), "A2 · Ciencia lo tiene")
_otros = [w for w in SIETE if w != "ciencia" and ECO.encendido_para(w)]
ok(not _otros, "A3 · y NINGUNO de los otros seis", f"lo tienen: {_otros}")
os.environ["ALEPH_ECO_AUXILIAR_WS"] = ""
ok(ECO.workspaces_encendidos() == set(),
   "A4 · y se puede APAGAR con la variable vacía (no queda clavado)")
os.environ.pop("ALEPH_ECO_AUXILIAR_WS")

print("\n── B · EL PLEGADO SE ENVÍA APAGADO EN LOS SIETE ──")
_onp = SD.workspaces_encendidos()
ok(_onp == set(), "B1 · de fábrica no hay ninguno", f"{_onp}")
_conp = [w for w in SIETE if SD.encendido_para(w)]
ok(not _conp, "B2 · ninguna de las siete superficies lo tiene", f"lo tienen: {_conp}")

print("\n── C · LA VÍA DE RECUPERACIÓN DE LA SALA VIVE SIN LA PERILLA ──")
# el disparador REAL: una salida más larga que el tope, capada por `_bound_tool_result`
import recipe_assembler as RA                      # noqa: E402
_larga = "x" * 12_000
_clave = "vara-perillas"
_txt = RA._bound_tool_result(_larga, clave=_clave, nombre="list_skills")
ok(len(_txt) < len(_larga), "C1 · el disparador existe: la salida se capó de verdad",
   f"{len(_larga)} → {len(_txt)}")
ok("…[truncado:" in _txt, "C2 · y el pie DICE que cortó")
ok(SD.NOMBRE_LECTOR in _txt,
   "C3 · con la perilla APAGADA el pie igual ofrece la vía (`%s`)" % SD.NOMBRE_LECTOR,
   _txt[-160:])
# y el lector contesta de verdad lo que ofreció
import re as _re                                    # noqa: E402
_m = _re.search(r'id="([^"]+)"', _txt)
ok(_m is not None, "C4 · el pie nombra un id concreto, no una promesa", _txt[-160:])
if _m:
    _resto = SD.leer(_clave, {"id": _m.group(1), "desde": 0})
    ok(_larga[:200] in _resto,
       "C5 · y ese id devuelve el crudo: la vía no es decorativa", f"{len(_resto)} chars")
else:
    ok(False, "C5 · sin id no se puede pedir el resto")

print(f"\n{_V} verdes · {_R} rojas" + ("   [MUTANTE]" if CAER else ""))
sys.exit(1 if _R else 0)
