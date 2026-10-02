#!/usr/bin/env python3
"""verify_marcador_ilegible.py — el código crudo no se sirve de respuesta.

EL DEFECTO QUE CIERRA. `extract_tool_calls` devuelve `[]` en dos situaciones que no son la
misma: el modelo escribió una respuesta final, o el modelo escribió un marcador
`<function=…>` cuyo JSON no cerraba. Río arriba las dos terminaban idénticas —
`content: res.text` con `finish_reason: "stop"`— así que la segunda **llegaba a la pantalla
del usuario como si fuera la respuesta**: `<function=redline>{"documen…`. No es un problema
de renderizado; es una llamada a herramienta fallida servida como prosa.

Es la hermana del caso que `verify_tool_choice.py` ya cubre. Allá: «no llamó y debía».
Acá: «quiso llamar y no se entendió». En los dos, devolver el texto como si nada convierte
un fallo en una respuesta.

LO QUE ESTA VARA MIDE, Y LO QUE NO. Mide el DISCRIMINANTE y el camino del server hasta el
código HTTP y la causa. **No mide** que el modelo escriba mejor el marcador la próxima vez
—eso depende del modelo— ni que la cascada reintente bien: eso es de la cascada y tiene su
propia vara.

Correr:  python3 platform/assembler/cli_brain/verify_marcador_ilegible.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli_brain.prompt_bridge import extract_tool_calls, marcador_ilegible  # noqa: E402

_fallos = []


def ok(cond, etiqueta):
    print(f"  {'✓' if cond else '✗'} {etiqueta}")
    if not cond:
        _fallos.append(etiqueta)


TOOLS = [{"function": {"name": "redline", "description": "marca", "parameters": {}}},
         {"function": {"name": "draft-document", "description": "redacta", "parameters": {}}}]

# El caso real: JSON sin cerrar. `_balanced_json` no encuentra un objeto balanceado, así
# que el extractor cae a texto — y ese texto es el marcador crudo.
ROTO = '<function=redline>{"document": "NDA.docx", "clause": "El plazo'

print("\n── el extractor sigue igual: lo que no pasó, no se afirma ───────────────────")
ok(extract_tool_calls(ROTO) == [], "un marcador con JSON sin cerrar NO produce tool_calls")
ok(len(extract_tool_calls('<function=redline>{"a":1}</function>')) == 1,
   "…y uno bien escrito sí (no se rompió nada)")

print("\n── el discriminante: intento roto ≠ respuesta final ─────────────────────────")
ok(marcador_ilegible(ROTO, TOOLS) == "redline",
   "un marcador roto de una tool DECLARADA se reconoce, y se dice cuál")
ok(marcador_ilegible("El plazo del NDA es de cinco años.", TOOLS) is None,
   "una respuesta final normal no acusa a nadie")
ok(marcador_ilegible("", TOOLS) is None, "el texto vacío tampoco")

print("\n── los falsos positivos que el discriminante tiene que evitar ───────────────")
# LAS DOS CONDICIONES SON NECESARIAS, y cada una tiene su caso.
ok(marcador_ilegible('<function=cualquier_cosa>{"a":', TOOLS) is None,
   "un marcador de una tool que este paso NO declaró no acusa (sería inventar un intento)")
ok(marcador_ilegible(ROTO, []) is None,
   "sin catálogo no hay intento posible: nadie pudo llamar a nada")
ok(marcador_ilegible(ROTO, None) is None, "ni con el catálogo ausente")
ok(marcador_ilegible("El contrato menciona la palabra redline tres veces.", TOOLS) is None,
   "nombrar una tool en prosa, SIN la sintaxis del marcador, no es un intento")
# Éste es el residuo aceptado y declarado: un texto que cita la sintaxis exacta Y nombra
# una tool declarada sí cae. Queda escrito acá para que se vea que es una decisión.
ok(marcador_ilegible("escribí <function=redline> para llamarla", TOOLS) == "redline",
   "RESIDUO DECLARADO: citar el marcador de una tool declarada sí cuenta como intento")

print("\n── robustez dura: ante la sorpresa, no acusa ────────────────────────────────")
ok(marcador_ilegible(ROTO, [{"function": None}, "basura", 7]) is None,
   "un catálogo con basura adentro no produce una acusación")
ok(marcador_ilegible(ROTO, [{"name": "redline"}]) == "redline",
   "…y una tool declarada plana (sin envoltorio `function`) se lee igual")

print("\n── EL SERVER: el marcador roto sale 422 con causa, no 200 con código crudo ──")
import http.client   # noqa: E402
import json          # noqa: E402
import threading     # noqa: E402

from cli_brain import base as B                      # noqa: E402
from cli_brain import detect as _detect              # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider   # noqa: E402
from cli_brain.server import create_server           # noqa: E402


class _ProviderRoto(ClaudeCliProvider):
    """Contesta SIEMPRE lo que le digan por `texto_a_devolver`. No spawnea nada."""
    provider_id = "lab_roto"
    display_name = "Lab Roto"
    response_model_id = "lab-roto"
    texto_a_devolver = ROTO

    def binary(self):
        return "/bin/true"

    def invoke(self, prompt, model=None, timeout=None, effort=None,
               on_evento=None, chunk_timeout=None, **_kw):
        return B.BrainResult(ok=True, text=_ProviderRoto.texto_a_devolver,
                             model_final="lab-modelo", model_final_source="cli-reported",
                             usage={"prompt_tokens": 1, "completion_tokens": 1})


_detect._BY_MODEL_ID["lab-roto"] = _ProviderRoto()
_srv = create_server(0)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
_puerto = _srv.server_address[1]


def _pedir(cuerpo):
    c = http.client.HTTPConnection("127.0.0.1", _puerto, timeout=30)
    c.request("POST", "/v1/chat/completions", json.dumps(cuerpo),
              {"Content-Type": "application/json", "Host": f"127.0.0.1:{_puerto}"})
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"{}")


_BASE = {"model": "lab-roto", "messages": [{"role": "user", "content": "redlineá el plazo"}],
         "tools": TOOLS}

_ProviderRoto.texto_a_devolver = ROTO
st, cuerpo = _pedir(dict(_BASE))
ok(st == 422, f"el marcador roto NO sale 200 (salió {st})")
ok(cuerpo.get("error", {}).get("type") == "marcador_ilegible", "la causa tiene nombre propio")
ok(cuerpo.get("error", {}).get("causa", {}).get("tool") == "redline",
   "y dice QUÉ herramienta se intentó llamar")
ok(ROTO in (cuerpo.get("error", {}).get("causa", {}).get("texto_devuelto") or ""),
   "el texto crudo viaja en la causa (no se tira: se reporta donde se lo puede leer)")
ok(str(cuerpo.get("error", {}).get("message", "")).strip() != "",
   "la causa llega con copy (regla sellada)")

# LA MITAD QUE IMPORTA TANTO COMO LA OTRA: esto NO puede romper los turnos sanos.
_ProviderRoto.texto_a_devolver = "El plazo del NDA es de cinco (5) años."
st, cuerpo = _pedir(dict(_BASE))
ok(st == 200, f"una respuesta final normal CON catálogo sigue saliendo 200 (salió {st})")
ok(cuerpo["choices"][0]["message"]["content"] == "El plazo del NDA es de cinco (5) años.",
   "…y vuelve tal cual")

_ProviderRoto.texto_a_devolver = '<function=redline>{"document":"NDA.docx"}</function>'
st, cuerpo = _pedir(dict(_BASE))
ok(st == 200, "un marcador BIEN escrito sigue saliendo 200")
ok(cuerpo["choices"][0].get("finish_reason") == "tool_calls",
   "…y como tool_call, no como texto")

# Sin catálogo no hay intento posible: el texto es del usuario y no se lo puede acusar.
_ProviderRoto.texto_a_devolver = ROTO
st, cuerpo = _pedir({"model": "lab-roto", "messages": [{"role": "user", "content": "h"}]})
ok(st == 200, "sin `tools` declaradas, el mismo texto NO se bloquea")

_srv.shutdown()

print()
if _fallos:
    print(f"✗ {len(_fallos)} fallo(s):")
    for f in _fallos:
        print(f"   · {f}")
    raise SystemExit(1)
print("PASS el marcador ilegible falla visible con causa, y el turno sano no se toca")
