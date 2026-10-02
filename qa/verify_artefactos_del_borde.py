#!/usr/bin/env python3
"""verify_artefactos_del_borde.py — LA COSECHA DEL BORDE, MEDIDA. [Finanzas · artefactos]

QUÉ PRUEBA, Y QUÉ **NO**.

PRUEBA (todo esto es corrible sin levantar un server, sin llave y sin proveedor):
  A · que la cosecha reconoce los resultados de las tools declaradas, y sólo ésas;
  B · que las dos tablas están SINCRONIZADAS — cada `kind` que este módulo declara existe
      de verdad en `bridge.TABLE`. Es la guarda contra el defecto que esta obra vino a
      cerrar: un mapa que nombra un kind que el puente no conoce sería otra vez un
      mecanismo apuntando a la nada;
  C · que las salidas REALES de las dos tools de Finanzas —con la forma leída de su propio
      código— cruzan el puente y salen `planilla`;
  D · que el historial repetido NO deja copias (la huella), que es lo que hace la
      diferencia entre un artefacto y nueve;
  E · las direcciones en las que tiene que CAER: un workspace sin filas no cosecha nada, un
      workspace con plugin no le toca al borde, un `content` que no es JSON no se guarda
      como si fuera el dato, y un resultado que el puente rechaza no se guarda igual.

**NO PRUEBA** que el modelo llame a las tools —eso es la homonimia, y vive en otro lado— ni
que el artefacto se VEA en la pantalla. La vara de eso es una captura después del build, y
un verde de este archivo no autoriza a decir «Finanzas ya muestra sus planillas».
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "platform"))
sys.path.insert(0, str(_RAIZ / "product" / "backend"))

from app.phase1 import artefactos_del_borde as ab     # noqa: E402
from app.phase1 import hilo_workspace as hw           # noqa: E402
from artifacts import bridge                          # noqa: E402

_FALLOS: list = []


def ok(nombre: str, cond, detalle: str = "") -> None:
    print(("  ✔ " if cond else "  ✘ ") + nombre + (("  · " + detalle) if detalle else ""))
    if not cond:
        _FALLOS.append(nombre)


def _paso(tool: str, payload, *, call_id: str = "c1") -> list:
    """Un historial de UN paso: el assistant pidió `tool` y llegó su resultado.

    El resultado va como STRING de JSON porque es como viaja de verdad: las dos tools de
    Finanzas devuelven `json.dumps(...)` (`alpha_zoo_tool.py:47` · `market_data.py:228`).
    """
    return [
        {"role": "user", "content": "dame los datos"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": call_id, "type": "function",
                         "function": {"name": tool, "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": call_id,
         "content": json.dumps(payload, ensure_ascii=False)},
    ]


#: LA SALIDA REAL DE `get_market_data`, con la forma leída de su código:
#: `fetch_market_data` arma `results[symbol] = records` (`agent/src/market_data.py:198-204`)
#: y `fetch_market_data_json` le hace `json.dumps` (`:228`).
_OHLCV = {"BTC-USDT": [
    {"date": "2026-08-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10},
    {"date": "2026-08-02", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 12},
]}

#: LA SALIDA REAL DE `alpha_zoo`: `{"status": "ok", "result": {...}}` (`:47`), con `items`
#: adentro del `result` (`:85`).
_ALPHAS = {"status": "ok", "result": {"count": 2, "items": [
    {"id": "alpha001", "expr": "rank(x)"}, {"id": "alpha002", "expr": "delta(y)"}]}}


print("A · la cosecha reconoce lo declarado, y sólo eso")
c = ab.cosechar(_paso("get_market_data", _OHLCV), workspace="finanzas")
ok("get_market_data se cosecha como market_ohlcv",
   len(c) == 1 and c[0]["kind"] == "market_ohlcv", str([x["kind"] for x in c]))
c2 = ab.cosechar(_paso("alpha_zoo", _ALPHAS), workspace="finanzas")
ok("alpha_zoo se cosecha como alpha_zoo",
   len(c2) == 1 and c2[0]["kind"] == "alpha_zoo", str([x["kind"] for x in c2]))
ok("una tool NO declarada no se cosecha",
   ab.cosechar(_paso("bash", {"stdout": "hola"}), workspace="finanzas") == [])
ok("MAYÚSCULAS y espacios en el nombre del workspace no pierden el mapa",
   len(ab.cosechar(_paso("alpha_zoo", _ALPHAS), workspace="  Finanzas ")) == 1)

print("B · las dos tablas están sincronizadas (la guarda del mecanismo sin destino)")
for _ws, _mapa in ab.KINDS_POR_WORKSPACE.items():
    _conocidos = set(bridge.kinds(_ws))
    for _tool, _kind in _mapa.items():
        ok("%s/%s existe en bridge.TABLE" % (_ws, _kind), _kind in _conocidos,
           "tool=%s · el puente conoce %s" % (_tool, sorted(_conocidos)))

print("C · lo cosechado CRUZA el puente y sale con su tipo")
for _tool, _payload, _esperado in (("get_market_data", _OHLCV, "planilla"),
                                   ("alpha_zoo", _ALPHAS, "planilla")):
    pieza = ab.cosechar(_paso(_tool, _payload), workspace="finanzas")[0]
    obra = bridge.cross("finanzas", {"kind": pieza["kind"], "name": pieza["name"],
                                     "data": pieza["data"]})
    ok("%s cruza y sale %s" % (_tool, _esperado), obra.get("type") == _esperado,
       "salió %r" % obra.get("type"))
    # Y el DATO llegó: una planilla sin filas es exactamente el «panel en blanco» que el
    # puente existe para no entregar.
    _filas = obra.get("rows") or obra.get("filas") or []
    ok("%s llega CON filas (no un marco vacío)" % _tool, len(_filas) >= 2,
       "%d filas · claves=%s" % (len(_filas), sorted(obra)))

print("D · la huella: el historial repetido no deja copias")
ab.olvidar("chat-D")
h = ab.cosechar(_paso("alpha_zoo", _ALPHAS), workspace="finanzas")[0]["huella"]
ok("la primera vez es nueva", ab.es_nueva("chat-D", h))
ok("la segunda NO", not ab.es_nueva("chat-D", h))
# El mismo resultado repetido DENTRO de un historial (nueve pasos del mismo turno) sale
# UNA sola vez de `cosechar`, sin depender del memo por chat.
_largo = (_paso("alpha_zoo", _ALPHAS, call_id="c1")
          + _paso("alpha_zoo", _ALPHAS, call_id="c2")[1:]
          + _paso("alpha_zoo", _ALPHAS, call_id="c3")[1:])
ok("tres pasos con el MISMO resultado cosechan una sola pieza",
   len(ab.cosechar(_largo, workspace="finanzas")) == 1)
# …y dos resultados DISTINTOS de la misma tool sí son dos artefactos.
_otro = {"status": "ok", "result": {"count": 1, "items": [{"id": "alpha101"}]}}
_dos = (_paso("alpha_zoo", _ALPHAS, call_id="c1")
        + _paso("alpha_zoo", _otro, call_id="c2")[1:])
ok("dos resultados DISTINTOS son dos piezas",
   len(ab.cosechar(_dos, workspace="finanzas")) == 2)

print("E · las direcciones en las que tiene que caer")
ok("un workspace sin filas declaradas no cosecha NADA",
   ab.cosechar(_paso("get_market_data", _OHLCV), workspace="diseno") == [])
ok("workspace vacío/None tampoco",
   ab.cosechar(_paso("alpha_zoo", _ALPHAS), workspace=None) == []
   and ab.cosechar(_paso("alpha_zoo", _ALPHAS), workspace="") == [])
_no_json = [{"role": "assistant", "content": "",
             "tool_calls": [{"id": "x", "function": {"name": "alpha_zoo"}}]},
            {"role": "tool", "tool_call_id": "x", "content": "Traceback: boom"}]
ok("un content que NO es JSON no se guarda como si fuera el dato",
   ab.cosechar(_no_json, workspace="finanzas") == [])
ok("un content vacío no cosecha",
   ab.cosechar([{"role": "assistant", "content": "",
                 "tool_calls": [{"id": "x", "function": {"name": "alpha_zoo"}}]},
                {"role": "tool", "tool_call_id": "x", "content": "  "}],
               workspace="finanzas") == [])
# El puente rechazando es el puente trabajando: un `status: error` del zoo NO se convierte
# en una planilla vacía.
_error = {"status": "error", "error": "registry init failed"}
_pz = ab.cosechar(_paso("alpha_zoo", _error), workspace="finanzas")
_rechazado = False
if len(_pz) == 1:
    try:
        bridge.cross("finanzas", {"kind": _pz[0]["kind"], "name": _pz[0]["name"],
                                  "data": _pz[0]["data"]})
    except bridge.BridgeError as _be:
        _rechazado = bool(bridge.CAUSES.get(_be.code))     # y con COPY, no un string suelto
ok("un `status: error` lo RECHAZA el puente, con causa y copy (no una planilla vacía)",
   _rechazado, "piezas=%d" % len(_pz))

print("F · la guarda: al que tiene plugin no le toca el borde")
_reg = None
try:
    from app.phase1.router import _WORKSPACE_STACKS as _reg
except Exception as _e:                                  # noqa: BLE001
    print("  [no medible] no se pudo importar el registro del router: %s" % _e)
if _reg is not None:
    _con, _sin = [], []
    for _ws, _meta in _reg.items():
        (_con if _meta.get("plugin") else _sin).append(_ws)
    ok("los que tienen plugin NO pasan por el borde",
       all(not hw.le_toca_al_borde(_reg[w]) for w in _con), "con plugin: %s" % _con)
    ok("los que no tienen plugin SÍ", all(hw.le_toca_al_borde(_reg[w]) for w in _sin),
       "sin plugin: %s" % _sin)
    ok("finanzas es uno de los que le toca al borde", "finanzas" in _sin)
    # Y la otra mitad: un workspace SIN mapa declarado no cambia de conducta aunque le
    # toque el borde. Es lo que hace que esta obra sea cero-regresión para los otros dos.
    ok("los otros sin plugin siguen sin cosechar (mapa vacío)",
       all(not ab.kinds_de_workspace(w) for w in _sin if w != "finanzas"),
       "sin plugin y sin mapa: %s" % [w for w in _sin if w != "finanzas"])

print()
if _FALLOS:
    print("ROJO · %d" % len(_FALLOS))
    for f in _FALLOS:
        print("   · " + f)
    sys.exit(1)
print("VERDE · la cosecha del borde mide lo que dice medir")
