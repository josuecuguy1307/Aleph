#!/usr/bin/env python3
"""verify_resolver_no_deja_pozo.py — portarse bien no puede dejarte peor que no preguntar.

EL POZO, medido el 2026-08-29 con una cartera de BTC y ETH en Finanzas:

  1. El modelo hace LO CORRECTO: antes de pedir datos, llama a `search_symbol` para fijar
     la identidad, que es exactamente lo que el prompt del stack le pide.
  2. Ese llamado ARMA la guarda de identidad (`grounding.py`, rama `_RESOLVER_TOOL`).
  3. El resolvedor consulta DOS fuentes —EastMoney y Yahoo— y ninguna conoce pares spot de
     exchange, aunque el motor sí baje datos de `okx`, `binance` y `ccxt`. «BTC-USDT» da
     CERO candidatos.
  4. Con la guarda armada y sin identidad fijada, todo lo que sigue queda bloqueado.

Resultado: el turno muere **por haber preguntado**. Sin llamar al resolvedor, el mismo pedido
funcionaba — se midió esa misma mañana, con el par explícito y las velas de OKX en pantalla.

QUÉ CUIDA ESTA VARA. Que la mitigación siga siendo QUIRÚRGICA. Deshacer de más sería peor
que el pozo: esta muralla existe para que un número sin evidencia no llegue a la pantalla.

Correr:  python3 qa/verify_resolver_no_deja_pozo.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "third_party/vibetrading/agent"))

from src.agent.grounding import GroundingLedger  # noqa: E402

fallos: list[str] = []


def ledger(mensaje: str) -> GroundingLedger:
    return GroundingLedger(run_dir=Path(tempfile.mkdtemp()), user_message=mensaje)


def busqueda_vacia(g: GroundingLedger, consulta: str, fuentes: dict) -> None:
    """El resolvedor se llama y vuelve sin un solo candidato."""
    g.authorize_tool_call(consulta and "search_symbol", {"query": consulta},
                          batch_authorized_symbols=(), call_id="c1")
    g.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": consulta},
        result=json.dumps({"ok": True, "data": {
            "query": consulta, "count": 0, "candidates": [], "sources": fuentes}}),
        call_id="c1",
        success=True,
    )


def ok(cond, que):
    print(("  ✓ " if cond else "  ✗ ") + que)
    if not cond:
        fallos.append(que)


print("\n── el pozo, cerrado ──")
g = ledger("Analyze a portfolio of BTC and ETH")
antes = g._identity_required
busqueda_vacia(g, "BTC-USDT", {"eastmoney": "ok", "yahoo": "ok"})
ok(antes is False, "la prosa del usuario no armaba la guarda")
ok(g.identity_status == "not_found", "la búsqueda limpia deja estado `not_found`")
ok(g._identity_required is False,
   "y la guarda vuelve a como estaba: preguntar no deja peor que no preguntar")

print("\n── y NO se afloja donde la señal es real ──")
g2 = ledger("Analyze a portfolio")
busqueda_vacia(g2, "XYZ", {"eastmoney": "boom", "yahoo": "ok"})
ok(g2.identity_status == "invalidated", "una fuente caída deja `invalidated`, no `not_found`")
ok(g2._identity_required is True,
   "`invalidated` NO es «no está» sino «algo anda mal»: la guarda se queda armada")

g3 = ledger("what is the current price of Apple?")
busqueda_vacia(g3, "AAPL", {"eastmoney": "ok", "yahoo": "ok"})
ok(g3._identity_required is True,
   "si la guarda la armó el usuario con su pedido, el resolvedor no la puede desarmar")

g4 = ledger("¿a cuánto está el precio de Apple?")
busqueda_vacia(g4, "AAPL", {"eastmoney": "ok", "yahoo": "ok"})
ok(g4._identity_required is True, "…y lo mismo en castellano, que es como escribe esta casa")

print("\n" + ("PASS el pozo está cerrado y la muralla sigue en pie"
              if not fallos else f"FAIL {len(fallos)} punto(s)"))
sys.exit(1 if fallos else 0)
