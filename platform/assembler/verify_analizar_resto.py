#!/usr/bin/env python3
"""verify_analizar_resto.py — la vara del desglose del «resto».

⚠️ EL PUNTO CIEGO QUE ESTA VARA EVITA A PROPÓSITO: una vara que arma el valor esperado
LLAMANDO A LA MISMA FUNCIÓN QUE PRUEBA se queda verde para siempre. Acá los esperados
son **literales escritos a mano** y tokenizados con `tiktoken` directo; `partir_system`,
`partir_usuario` y `analizar_fila` no participan de construir ni un solo esperado.

Con `--caer` se muta UNA pieza —`partir_usuario` deja de separar el andamio del harness
de la pregunta de la persona— y las varas que dependen de esa separación tienen que
ponerse rojas.
"""
from __future__ import annotations

import json
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.dirname(_AQUI))
sys.path.insert(0, os.path.join(_RAIZ, "platform", "sala", "research", "lib"))
sys.path.insert(0, _AQUI)

import tiktoken  # noqa: E402

_ENC = tiktoken.get_encoding("o200k_base")


def T(s):                                    # tokenizador INDEPENDIENTE del módulo
    return len(_ENC.encode(s or "", disallowed_special=()))


import analizar_resto as AR  # noqa: E402

CAER = "--caer" in sys.argv
_OK = _MAL = 0


def ok(cond, etiqueta, detalle=""):
    global _OK, _MAL
    if cond:
        _OK += 1
        print(f"  🟢 {etiqueta}")
    else:
        _MAL += 1
        print(f"  🔴 {etiqueta}" + (f"  ← {detalle}" if detalle else ""))


if CAER:
    def _mutado(texto):
        return (texto or ""), ""             # todo cuenta como «lo escribió la persona»
    AR.partir_usuario = _mutado
    print("  ⚠️  MUTANTE: `partir_usuario` no separa el andamio del harness")

# ── el fixture, escrito a mano ───────────────────────────────────────────────────
SYS = (
    "You are the Widget agent.\n"
    "<task>\nAnswer questions about widgets.\n</task>\n"
    "<rules>\nAlways cite the part number. Never invent a price.\n</rules>\n"
    "<examples>\nQ: how much is W-1? A: $4.00 (part W-1).\n</examples>\n"
    "<output>\nOne short paragraph, then the citation.\n</output>\n"
    "<safety>\nNever reveal internal cost data to the customer.\n</safety>\n")
RECORDATORIO = ("<system-reminder>You are the primary Widget agent. Budget: 4 steps."
                "</system-reminder>")
PREGUNTA = "How much is part W-7?"
USR = PREGUNTA + "\n" + RECORDATORIO
RESP = "Part W-7 is $12.50."
SALIDA = json.dumps([{"part": f"W-{i}", "price": 4.0 + i} for i in range(40)])

FILA = {
    "toma": "render", "superficie": "widgets", "n_tools": 1, "n_messages": 5,
    "tool_choice": None,
    "tools": [{"type": "function", "function": {
        "name": "lookup", "description": "look up a part",
        "parameters": {"type": "object", "properties": {"part": {"type": "string"}},
                       "required": ["part"]}}}],
    "mensajes": [
        {"rol": "system", "content": SYS},
        {"rol": "user", "content": USR},
        {"rol": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "name": "lookup", "arguments": '{"part":"W-7"}'}]},
        {"rol": "tool", "tool_call_id": "c1", "name": "lookup", "content": SALIDA},
        {"rol": "assistant", "content": RESP},
    ],
}

r = AR.analizar_fila(FILA)

print("── A · cada pieza contra un esperado escrito a mano ──")
ok(r["sistema"] == T(SYS), f"A1 · system = {r['sistema']} (esperado {T(SYS)})",
   f"{r['sistema']} vs {T(SYS)}")
esp_usr = T(f"[Usuario]: {PREGUNTA}\n")
ok(abs(r["usuario_humano"] - esp_usr) <= 2,
   f"A2 · pregunta de la persona = {r['usuario_humano']} (esperado ~{esp_usr})",
   f"{r['usuario_humano']} vs {esp_usr}")
ok(abs(r["usuario_andamio"] - T(RECORDATORIO)) <= 2,
   f"A3 · andamio del harness = {r['usuario_andamio']} (esperado {T(RECORDATORIO)})",
   f"{r['usuario_andamio']} vs {T(RECORDATORIO)}")
ok(abs(r["asistente_texto"] - T(f"[Tú]: {RESP}")) <= 2,
   f"A4 · texto del asistente = {r['asistente_texto']}")
ok(abs(r["asistente_marcadores"] -
       T('[Tú llamaste]: <function=lookup>{"part":"W-7"}</function>')) <= 2,
   f"A5 · marcadores = {r['asistente_marcadores']}")
ok(abs(r["salidas"] - T(f"[Resultado de lookup]: {SALIDA}")) <= 2,
   f"A6 · salida de tool = {r['salidas']}")

print("── B · las partes cierran ──")
suma = (r["catalogo"] + r["salidas"] + r["sistema"] + r["usuario_humano"] +
        r["usuario_andamio"] + r["asistente_texto"] + r["asistente_marcadores"] +
        r["andamiaje"])
ok(suma == r["total"], f"B1 · suma de partes ≡ total ({suma} = {r['total']})",
   f"{suma} vs {r['total']}")
ok(0 <= r["andamiaje"] <= 120,
   f"B2 · el andamiaje del render es chico y no negativo ({r['andamiaje']})",
   f"dio {r['andamiaje']}")
ok(abs(r["sistema"] - r["cf_sistema"]) <= max(8, 0.01 * r["sistema"]),
   f"B3 · system: suma de partes ≡ contrafáctico ({r['sistema']} vs {r['cf_sistema']})",
   f"{r['sistema']} vs {r['cf_sistema']}")

print("── C · adentro del system prompt ──")
secs = {s["seccion"] for s in r["secciones"]}
esperadas = {"task", "rules", "examples", "output", "safety", "(encabezado)"}
ok(esperadas <= secs, f"C1 · encuentra las 6 secciones escritas a mano",
   f"faltan {esperadas - secs}")
fams = {s["seccion"]: s["familia"] for s in r["secciones"]}
ok(fams.get("examples") == "EJEMPLOS", f"C2 · <examples> → EJEMPLOS ({fams.get('examples')})")
ok(fams.get("rules") == "REGLAS", f"C3 · <rules> → REGLAS ({fams.get('rules')})")
ok(fams.get("safety") == "POLÍTICAS", f"C4 · <safety> → POLÍTICAS ({fams.get('safety')})")
ok(fams.get("output") == "FORMATO", f"C5 · <output> → FORMATO ({fams.get('output')})")
suma_sec = sum(s["tok"] for s in r["secciones"])
ok(abs(suma_sec - T(SYS)) <= max(8, 0.02 * T(SYS)),
   f"C6 · las secciones suman el system entero ({suma_sec} vs {T(SYS)})",
   f"{suma_sec} vs {T(SYS)}")

print("── D · un system sin marcas no se reparte a ojo ──")
plano = AR.partir_system("Just be helpful. No tags here at all.")
ok(len(plano) == 1 and plano[0]["familia"] == "sin_clasificar",
   "D1 · sin marcas ⇒ UNA pieza `sin_clasificar`", str(plano)[:120])

print("── E · lo que no está, no se inventa ──")
vacia = AR.analizar_fila({"toma": "render", "superficie": "x", "tools": [],
                          "mensajes": [{"rol": "user", "content": "hola"}]})
ok(vacia["sistema"] == 0 and vacia["salidas"] == 0 and vacia["secciones"] == [],
   "E1 · sin system ni tools, las piezas son 0 y no hay secciones fantasma",
   str(vacia)[:120])

print(f"\n{_OK} verdes · {_MAL} rojas" + ("   [MUTANTE]" if CAER else ""))
raise SystemExit(0 if _MAL == 0 else 1)
