#!/usr/bin/env python3
"""verify_resolver_conoce_cripto.py — el resolvedor tiene que conocer los pares que el motor baja.

LA CURA (hermana de `verify_resolver_no_deja_pozo.py`, que cuida la muleta).

El pozo era que `search_symbol` consultaba dos fuentes de ACCIONES —EastMoney y Yahoo— y
ninguna conoce pares spot de exchange, aunque el motor sí baje velas de OKX. MEDIDO el
2026-08-29 contra las fuentes vivas, antes de esta obra:

    search_symbol("BTC-USDT") → 0 candidatos
    search_symbol("ETH-USDT") → 1 candidato, y AJENO: «AETHUSDT-USD» (Aave Ethereum USDT)
    search_symbol("BTC")      → BTC-USD · BTC=F · GBTC · BTCY.US · BTCS.US  (futuro y ETFs)

La muleta hacía que preguntar no te dejara peor que no preguntar. Esto hace que preguntar
SIRVA: se le dio al resolvedor la lista de instrumentos spot de OKX, que es exactamente el
universo que `src/market_data.py` sabe ir a buscar.

QUÉ CUIDA ESTA VARA
  1. Que las cuatro formas de nombrar el par lleguen al mismo símbolo canónico.
  2. Que NO se emita un par que el motor no pueda pedir (sólo cotizados contra USDT).
  3. Que la fuente nueva no le saque el lugar a las acciones.
  4. Que una fuente caída no tumbe a las otras.
  5. Que con el par resuelto la guarda de identidad quede FIJADA y deje pasar los datos.

Correr:  python3 qa/verify_resolver_conoce_cripto.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "third_party/vibetrading/agent"))

from backtest.loaders import okx  # noqa: E402
from src.agent.grounding import GroundingLedger  # noqa: E402
from src.tools import symbol_search_tool as sst  # noqa: E402

fallos: list[str] = []
no_medibles: list[str] = []


def ok(cond, que):
    print(("  ✓ " if cond else "  ✗ ") + que)
    if not cond:
        fallos.append(que)


def no_medible(que, porque):
    print(f"  · NO MEDIBLE — {que} ({porque})")
    no_medibles.append(que)


# La forma real de una fila de `/api/v5/public/instruments?instType=SPOT`, recortada a los
# campos que esta fuente lee. Congelada acá para que las reglas se midan sin red.
def fila(inst_id, base, quote, state="live"):
    return {"instId": inst_id, "baseCcy": base, "quoteCcy": quote, "state": state}


FIXTURE = [
    fila("BTC-USDT", "BTC", "USDT"),
    fila("BTC-USDC", "BTC", "USDC"),      # el motor no sabe rutear USDC
    fila("ETH-USDT", "ETH", "USDT"),
    fila("ETHFI-USDT", "ETHFI", "USDT"),  # prefijo de ETH
    fila("ETHW-USDT", "ETHW", "USDT"),    # prefijo de ETH
    fila("PEPE-USDT", "PEPE", "USDT"),
    fila("SOL-USDT", "SOL", "USDT"),
]


def simbolos(consulta):
    return [c["symbol"] for c in sst._okx_matches(consulta, FIXTURE)]


print("\n── las cuatro formas de nombrar el mismo par ──")
for consulta in ("BTC-USDT", "btc/usdt", "BTCUSDT", "btc"):
    ok(simbolos(consulta) == ["BTC-USDT"], f"«{consulta}» resuelve a BTC-USDT")

print("\n── sólo lo que el motor puede ir a buscar ──")
ok("BTC-USDC" not in simbolos("BTC"),
   "no se emite BTC-USDC: `market_data` rutea a OKX con ^[A-Z]+-USDT$ y USDC caería en tushare")
ok(simbolos("BTC-USDC") == [],
   "pedir explícitamente un par que no se puede bajar devuelve vacío, no un símbolo muerto")

print("\n── un prefijo es una apuesta, no una coincidencia ──")
ok(simbolos("eth") == ["ETH-USDT"],
   "«eth» da SÓLO el par exacto: ETHFI y ETHW no se cuelan detrás del que se pidió")
ok(simbolos("PEP") == ["PEPE-USDT"],
   "sin coincidencia exacta sí se ofrece el prefijo («PEP» → PEPE-USDT)")
ok(simbolos("PE") == [], "por debajo de 3 letras no se adivina")
ok(len(sst._okx_matches("E", FIXTURE)) == 0, "una sola letra tampoco")

print("\n── la fuente nueva no le saca el lugar a las acciones ──")
for consulta in ("apple", "AAPL", "贵州茅台", "GBTC", "Grayscale"):
    ok(simbolos(consulta) == [], f"«{consulta}» no devuelve cripto")

print("\n── una fuente caída no tumba a las otras ──")
original = okx.spot_instruments
try:
    def revienta():
        raise RuntimeError("OKX no contesta")
    okx.spot_instruments = revienta
    hits, estado = sst._search_okx("BTC-USDT")
    ok(hits == [], "con OKX caído la fuente devuelve vacío…")
    ok(estado.startswith("okx search failed"), "…y su estado dice por qué, en `sources`")
finally:
    okx.spot_instruments = original

print("\n── dos deletreos del mismo activo son un empate ──")
# `grounding._choose_candidate` llama exacto a todo candidato cuya BASE coincide con la
# consulta. Al sumar OKX, «BTC» pasó de `locked` a `ambiguous` — y `ambiguous` la muleta
# NO lo deshace: el turno moría igual, sólo que más temprano.
def plegar(filas):
    return sst._fold_unfetchable_spellings(filas)

par = {"symbol": "BTC-USDT", "market": "crypto", "source": "okx"}
usd = {"symbol": "BTC-USD", "name": "Bitcoin USD", "market": "global", "source": "yahoo"}
etf = {"symbol": "GBTC", "name": "Grayscale Bitcoin Trust", "market": "global", "source": "yahoo"}

plegado = plegar([par, usd, etf])
ok([c["symbol"] for c in plegado] == ["BTC-USDT", "GBTC"],
   "el deletreo que el motor NO puede bajar sale de la lista")
ok(plegado[0].get("aliases") == ["BTC-USD"],
   "…pero no se esconde: queda anotado en `aliases` del que sí se puede bajar")
ok(plegar([usd, etf]) == [usd, etf],
   "sin par de OKX para esa base no se pliega nada")
# El criterio es la BASE + si se puede bajar, no una lista de monedas: BTC-USDC es el mismo
# activo y tampoco se puede bajar, así que también empata y también se pliega.
ok([c["symbol"] for c in plegar([par, {"symbol": "BTC-USDC", "source": "yahoo"}])]
   == ["BTC-USDT"],
   "cualquier deletreo no bajable de la MISMA base se pliega, no sólo el de USD")
ok([c["symbol"] for c in plegar([par, {"symbol": "ETH-USD", "source": "yahoo"}])]
   == ["BTC-USDT", "ETH-USD"],
   "y jamás se pliega otra base: ETH-USD no es un deletreo de BTC")

ok(sst._es_bajable_como_cripto("BTC-USDT") is True,
   "el criterio no se adivina: se le pregunta al ruteo del motor (BTC-USDT → okx)")
ok(sst._es_bajable_como_cripto("BTC-USD") is False,
   "…y BTC-USD cae en `tushare`, que no está en la cadena de respaldo de cripto")

print("\n── un `limit` chico no puede dejar afuera al par ──")
muchos = [par, usd, etf, {"symbol": "BTC=F", "source": "yahoo"},
          {"symbol": "BTCY.US", "source": "yahoo"}, {"symbol": "BTCS.US", "source": "yahoo"}]
ok(plegar(muchos)[0]["symbol"] == "BTC-USDT",
   "el par queda primero: con limit=5 el resto empujaba a BTC-USDT fuera del corte")

print("\n── el pozo, cerrado: con el par resuelto la identidad queda FIJADA ──")
sobre = {
    "ok": True,
    "market": "multi",
    "source": "symbol_search",
    "data": {
        "query": "BTC-USDT",
        "count": 1,
        "candidates": sst._okx_matches("BTC-USDT", FIXTURE),
        "sources": {"eastmoney": "ok", "okx": "ok", "yahoo": "ok"},
    },
}
g = GroundingLedger(run_dir=Path(tempfile.mkdtemp()),
                    user_message="Analyze a portfolio of BTC and ETH")
g.authorize_tool_call("search_symbol", {"query": "BTC-USDT"},
                      batch_authorized_symbols=(), call_id="c1")
g.ingest_tool_result(tool_name="search_symbol", arguments={"query": "BTC-USDT"},
                     result=json.dumps(sobre), call_id="c1", success=True)
ok(g.identity_status == "locked",
   f"la identidad queda `locked` (quedó: {g.identity_status!r})")
# El lote SIGUIENTE, como lo arma `loop.py:1232`: le pregunta al ledger qué tiene fijado.
# Dentro del mismo lote la muralla no consume su propio resultado, y eso está bien.
permiso = g.authorize_tool_call("get_market_data", {"codes": ["BTC-USDT"]},
                                batch_authorized_symbols=set(g.authorized_symbols),
                                batch_identity_status=g.identity_status, call_id="c2")
ok(permiso.allowed,
   f"y en el lote siguiente el pedido de datos PASA (quedó: {permiso.error_code!r})")
mismo_lote = g.authorize_tool_call("get_market_data", {"codes": ["BTC-USDT"]},
                                   batch_authorized_symbols=(), call_id="c3")
ok(not mismo_lote.allowed,
   "…y sigue sin consumirse DENTRO del mismo lote: la muralla no se aflojó de más")

print("\n── en vivo, contra OKX ──")
try:
    filas = okx.spot_instruments()
except Exception as exc:  # noqa: BLE001
    no_medible("el par vivo", f"OKX no contesta: {exc}")
else:
    if not filas:
        no_medible("el par vivo", "OKX contestó una lista vacía")
    else:
        ok(any(f.get("instId") == "BTC-USDT" for f in filas),
           f"la lista viva trae BTC-USDT ({len(filas)} instrumentos spot)")
        vivos, estado = sst._search_okx("BTC-USDT")
        ok(estado == "ok" and [c["symbol"] for c in vivos] == ["BTC-USDT"],
           "y la fuente lo resuelve contra la lista real, no sólo contra el fixture")

resumen = f"{len(fallos)} roja(s)" if fallos else "todo verde"
if no_medibles:
    resumen += f" · {len(no_medibles)} NO MEDIBLE(S)"
print("\n" + ("PASS " if not fallos else "FAIL ") + resumen)
sys.exit(1 if fallos else 0)
