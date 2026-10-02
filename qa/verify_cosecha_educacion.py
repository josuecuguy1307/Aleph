#!/usr/bin/env python3
"""verify_cosecha_educacion.py — LA COSECHA DEL BORDE NO ALCANZA A EDUCACIÓN, Y SE MIDE.

[Educación · los artefactos]

`artefactos_del_borde.cosechar()` llegó a main con Finanzas y es el mecanismo correcto
para los tres stacks SIN plugin — Educación es uno de ellos. Pero no le sirve, y la razón
no es que le falte una fila: es que **los dos stacks hablan formas distintas**.

    Finanzas   `market_data.py:228` hace `json.dumps(...)` → el `role:"tool"` lleva JSON
    Educación  `tool_dispatch.py:637-645` arma el mensaje con `"content": result_text`,
               que es `ToolResult.content` — PROSA. Lo estructurado queda adentro del
               proceso, en `metadata` / `tool_metadata_by_id`, y **no cruza el protocolo
               OpenAI**: un mensaje `role:"tool"` sólo lleva `content`.

Y no es una tool: barridas las **19** clases de `deeptutor/tools/builtin/__init__.py`,
**ninguna** pone `json.dumps` adentro de `ToolResult(content=…)`. `cosechar` exige
`json.loads` (y hace bien: «un `content` que no es JSON no se guarda como si fuera el
dato»), así que el gate excluye 19 de 19 — hoy y para cualquier fila que se agregue.

ESTA VARA ES UN PAR FALSABLE, y las dos mitades corren el módulo de verdad:
  A · con la forma de Finanzas (JSON) la cosecha SÍ trae → el arnés no está roto.
  B · con la forma de Educación (prosa) la cosecha trae CERO → la diferencia es la forma.
  C · la guarda a futuro: si alguien le declara filas a `educacion` en
      `KINDS_POR_WORKSPACE`, esta vara EXIGE que una salida real suya se coseche. Sin
      esa exigencia, declarar la fila daría un verde sobre un mecanismo mudo — que es
      exactamente el defecto que esta familia de obras viene cerrando.

⚠️ B AFIRMA UN CONTRATO, NO UNA CONDENA. Lo que exige es la regla que el propio módulo
declara —«un `content` que no es JSON no se guarda como si fuera el dato»— aplicada al
caso de Educación. El día que ese contrato gane una forma TEXTO **declarada** (no
olfateada), esta vara la gana EN EL MISMO COMMIT: la que se toca es la expectativa, no la
regla. Una vara que se pone roja cuando alguien arregla algo, sin decir por qué, es una
trampa; ésta dice exactamente qué habría cambiado.

LO QUE NO DICE: que Educación deba usar esta puerta. Sus entregables de verdad —el
ejercicio, el informe, la visualización, la ruta de estudio— los producen CAPACIDADES,
que no son tools y cuyo resultado nunca aparece como `role:"tool"`.

➜ **Y POR ESO EDUCACIÓN ENTRA POR OTRA PUERTA, QUE YA ESTÁ HECHA**:
`app/phase1/obras_del_pack.py` lee el almacén que el stack YA escribe (`chat_history.db`:
`attachments_json` con los archivos generados, y el evento `result` con el `response` de
cada capacidad). Su vara es `qa/verify_obras_del_pack.py`. Esta de acá sigue existiendo
para que **el gate de JSON de la cosecha del borde no se afloje**: el día que alguien lo
relaje para «hacer entrar a Educación», esta vara se pone roja y le señala la puerta
correcta.

    product/backend/.venv/bin/python qa/verify_cosecha_educacion.py
      0 → medido · 1 → algo no da lo que dice · 2 → no medible
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "platform"))
sys.path.insert(0, str(_RAIZ / "product" / "backend"))

try:
    from app.phase1 import artefactos_del_borde as ab     # noqa: E402
except Exception as exc:                                  # noqa: BLE001
    print(f"[no medible] no se pudo importar artefactos_del_borde: {exc}")
    raise SystemExit(2)

_FALLOS: list = []


def ok(nombre: str, cond, detalle: str = "") -> None:
    print(("  ✔ " if cond else "  ✘ ") + nombre + (("  · " + detalle) if detalle else ""))
    if not cond:
        _FALLOS.append(nombre)


def _historial(tool: str, contenido: str, *, call_id: str = "c1") -> list:
    """Un turno de un paso: el assistant pidió `tool` y volvió su resultado.

    La forma del mensaje `tool` es la que arma el harness de Educación
    (`core/agentic/tool_dispatch.py:637-645`): `role` · `tool_call_id` · `name` ·
    `content`, y nada más. No hay `metadata` que cruzar porque el protocolo no la lleva.
    """
    return [
        {"role": "user", "content": "buscame papers sobre derivadas"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": call_id, "type": "function",
                         "function": {"name": tool, "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": call_id, "name": tool, "content": contenido},
    ]


#: La salida REAL de `paper_search`, con la forma leída de su propio código
#: (`tools/builtin/__init__.py`, `PaperSearchToolWrapper.execute`): `content` son las
#: líneas de texto que arma el `for paper in papers`, y los `papers` estructurados van a
#: `metadata`, que se queda del otro lado.
_PAPER_SEARCH_CONTENT = (
    "**Deep Learning for Symbolic Differentiation** (2025)\n"
    "Authors: A. Rivas, B. Okonkwo\n"
    "arXiv: 2501.01234\n"
    "URL: http://arxiv.org/abs/2501.01234\n"
    "Abstract: We study symbolic differentiation with neural guidance.\n"
)

#: Y la salida REAL de una tool de Finanzas, para el contraste: `json.dumps` de
#: `{símbolo: [barras]}` (`agent/src/market_data.py:198-204` + `:228`).
_OHLCV = json.dumps({"BTC-USDT": [
    {"date": "2026-08-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10},
]}, ensure_ascii=False)


print("\nA · el arnés no está roto: con la forma de Finanzas, la cosecha SÍ trae")
ab.olvidar("chat-A")
cos_fin = ab.cosechar(_historial("get_market_data", _OHLCV), workspace="finanzas")
ok("finanzas · get_market_data cruza", len(cos_fin) == 1,
   f"{len(cos_fin)} cosechado/s · kind={cos_fin[0]['kind'] if cos_fin else '—'}")

print("\nB · con la forma de Educación (prosa), la cosecha trae CERO")
declaradas = ab.kinds_de_workspace("educacion")
cos_edu = ab.cosechar(_historial("paper_search", _PAPER_SEARCH_CONTENT), workspace="educacion")
ok("educacion · paper_search NO cruza", len(cos_edu) == 0,
   f"mapa declarado={dict(declaradas) or '{} (vacío)'} · cosechado={len(cos_edu)}")

# Y se aísla la causa: aunque el mapa TUVIERA la fila, el gate de JSON la deja muda.
# Se mide sobre el módulo real, poniéndole la fila a mano y sacándola después — no se
# afirma «pasaría»: se hace pasar.
_previo = dict(ab.KINDS_POR_WORKSPACE)
try:
    ab.KINDS_POR_WORKSPACE["educacion"] = {"paper_search": "report"}
    ab.olvidar("chat-B")
    con_fila = ab.cosechar(_historial("paper_search", _PAPER_SEARCH_CONTENT, call_id="c2"),
                           workspace="educacion")
finally:
    ab.KINDS_POR_WORKSPACE.clear()
    ab.KINDS_POR_WORKSPACE.update(_previo)
ok("y con la fila puesta TAMPOCO cruza — la causa es la forma, no el mapa",
   len(con_fila) == 0,
   "`cosechar` exige `json.loads` del `content`; el de Educación es prosa "
   "(`tool_dispatch.py:643`)")

print("\nC · la guarda a futuro: si mañana `educacion` declara filas, tienen que cosechar")
if not declaradas:
    print("     · hoy el mapa está vacío: no hay nada que exigir. Cuando alguien le "
          "declare una fila, esta sección deja de ser un salteo y empieza a exigir.")
else:
    # Una fila declarada que no cosecha su propia salida es un mecanismo mudo con cara
    # de cableado. Se exige que ALGUNA de las declaradas traiga algo con una salida de
    # su stack; si el gate de JSON sigue en pie, esto se pone rojo y con motivo.
    ok("alguna fila declarada de educacion cosecha de verdad",
       len(cos_edu) > 0 or len(con_fila) > 0,
       f"filas={sorted(declaradas)} — si esto es rojo, se declaró la fila y no la forma")

print()
if _FALLOS:
    print("ROJO — " + " · ".join(_FALLOS))
    raise SystemExit(1)
print("VERDE — el mecanismo funciona, y no alcanza a Educación por la FORMA del resultado.")
print("        Sus entregables de verdad son de CAPACIDAD, no de tool: no pasan por acá.")
