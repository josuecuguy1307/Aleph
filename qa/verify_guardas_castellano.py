#!/usr/bin/env python3
"""verify_guardas_castellano.py — las murallas se arman cuando la casa escribe en su idioma.

HERMANA DE `verify_guardas_por_idioma.py`, y cubre lo que aquélla NO puede: aquélla lee los
patrones y avisa cuál no nombra el castellano —análisis estático—. Ésta los EJECUTA con
frases reales y comprueba que la guarda se levanta. Leer un regex mide intenciones; correrlo
mide hechos.

CADA CASO DE ACÁ ES UNA FRASE QUE UN USUARIO ESCRIBE. Si una se pone roja, la muralla
correspondiente está dormida para el idioma en que corre Aleph — y estas guardas fallan del
lado peligroso: cuando no se arman, un número sin evidencia llega a la pantalla.

Correr:  python3 qa/verify_guardas_castellano.py
"""
from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "third_party/vibetrading/agent"))

from src.agent import grounding as g  # noqa: E402

fallos: list[str] = []


def arma(guarda, frases, nombre, debe=True):
    for f in frases:
        ok = bool(guarda.search(f)) is debe
        print(("  ✓ " if ok else "  ✗ ") + f"{nombre:24} «{f}»")
        if not ok:
            fallos.append(f"{nombre}: «{f}»")


print("\n── pedido accionable de mercado (ARMA la resolución de identidad) ──")
arma(g._ACTIONABLE_MARKET_RE,
     ["¿a cuánto está el precio de Apple?", "comprá 10 acciones de Tesla", "vendé todo",
      "cuál es la cotización de Nvidia", "cuánto vale Microsoft hoy"],
     "_ACTIONABLE_MARKET_RE")
arma(g._ACTIONABLE_MARKET_RE,
     ["no entiendo tu comprensión del tema", "le puse un vendaje", "contame un chiste"],
     "_ACTIONABLE_MARKET_RE", debe=False)

print("\n── afirmar que algo no cotiza ──")
arma(g._PRIVATE_ASSERTION_RE,
     ["OpenAI es una empresa privada", "esa firma no cotiza en bolsa", "no está listada"],
     "_PRIVATE_ASSERTION_RE")

print("\n── «este número lo derivé» ──")
arma(g._DERIVATION_RE, ["valor derivado de los cierres", "calculado con la fórmula de arriba"],
     "_DERIVATION_RE")

print("\n── puntajes con etiqueta ──")
arma(g._LABELLED_SCORE_RE, ["confianza 0.82", "probabilidad: 65", "tasa de acierto 55"],
     "_LABELLED_SCORE_RE")

print("\n── montos agregados ──")
arma(g._AGGREGATE_AMOUNT_RE, ["costo 1200", "monto: 45.000", "capitalización 3200"],
     "_AGGREGATE_AMOUNT_RE")

print("\n── cantidades con unidad ──")
arma(g._QUANTITY_WITH_UNIT_RE, ["120 acciones", "3 contratos", "18 meses"],
     "_QUANTITY_WITH_UNIT_RE")

print("\n── niveles prospectivos ──")
arma(g._PROSPECTIVE_LEVEL_RE, ["precio objetivo 210", "stop 185", "resistencia 240"],
     "_PROSPECTIVE_LEVEL_RE")

print("\n── el validador reconoce una tabla escrita en castellano ──")
for cab in ("apertura", "máximo", "mínimo", "cierre"):
    ok = cab in g._TABLE_FIELD_ALIASES
    print(("  ✓ " if ok else "  ✗ ") + f"encabezado «{cab}»")
    if not ok:
        fallos.append(f"_TABLE_FIELD_ALIASES: falta «{cab}»")

print("\n── y los otros dos idiomas siguen intactos ──")
arma(g._ACTIONABLE_MARKET_RE, ["buy AAPL now", "current price of TSLA", "买入 腾讯", "现价"],
     "inglés/chino")

# ── LA PRUEBA DE PUNTA A PUNTA ────────────────────────────────────────────────────────
# Las de arriba miden regex. Ésta mide la CONSECUENCIA: con el ledger construido a partir del
# mensaje del usuario, ¿se valida la respuesta contra la evidencia? Es lo que de verdad
# separa «una guarda dormida» de «un número inventado en la pantalla».
print("\n── consecuencia: ¿se valida la respuesta? ──")
try:
    import tempfile
    from pathlib import Path
    from src.agent.grounding import GroundingLedger

    _d = Path(tempfile.mkdtemp())
    for _msg, _debe, _et in [
        ("¿a cuánto está el precio de Apple?", True, "castellano"),
        ("comprá 10 acciones de Tesla", True, "voseo"),
        ("what is the current price of Apple?", True, "inglés"),
        ("contame un chiste", False, "sin mercado"),
    ]:
        _v = GroundingLedger(run_dir=_d, user_message=_msg)._identity_required
        _ok = _v is _debe
        print(("  ✓ " if _ok else "  ✗ ") + f"{_et:12} valida={_v}  «{_msg}»")
        if not _ok:
            fallos.append(f"validación de respuesta: «{_msg}»")
except Exception as _exc:  # el ledger pide un run_dir real; si cambia su firma se ve acá
    print("  ✗ no se pudo construir el ledger:", _exc)
    fallos.append(f"ledger: {_exc}")

print("\n" + ("PASS las guardas se arman en castellano"
              if not fallos else f"FAIL {len(fallos)} guarda(s) dormida(s)"))
for f in fallos:
    print("   ·", f)
sys.exit(1 if fallos else 0)
