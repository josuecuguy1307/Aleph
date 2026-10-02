#!/usr/bin/env python3
"""verify_tool_choice.py — [B0-2 · CLI] el `tool_choice` que este transporte SÍ puede honrar.

Los cerebros CLI no tienen `tool_choice` nativo: no hay bandera de proveedor porque no hay
canal estructurado — Claude Code y Codex reciben un prompt PLANO por `-p` y las tools viajan
como texto. Así que la obligación sólo puede vivir en dos lugares, y esta vara mide los dos:

  1. **en el prompt** — el bloque de herramientas y la cola del paso dicen que es obligatorio;
  2. **en la salida** — el server COMPRUEBA que vino el marcador, y si no vino falla visible
     en vez de devolver el texto como si la obligación se hubiera cumplido.

Sin (2), (1) sería teatro: una instrucción se puede desobedecer, y un texto devuelto como
respuesta final es exactamente la decisión equivocada que B0-2 vino a evitar.

Correr:  python3 platform/assembler/cli_brain/verify_tool_choice.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli_brain.prompt_bridge import (  # noqa: E402
    extract_tool_calls, nombre_exigido, obliga_a_tool,
    render_prompt, render_prompt_incremental,
)

_fallos = []


def ok(cond, etiqueta):
    print(f"  {'✓' if cond else '✗'} {etiqueta}")
    if not cond:
        _fallos.append(etiqueta)


MSGS = [{"role": "user", "content": "hacelo"}]
TOOLS = [{"function": {"name": "redline", "description": "marca", "parameters": {}}},
         {"function": {"name": "compute", "description": "calcula", "parameters": {}}}]

print("\n── el predicado ─────────────────────────────────────────────────────────────")
ok(obliga_a_tool("required") is True, "`required` obliga")
ok(obliga_a_tool({"type": "function", "function": {"name": "redline"}}) is True,
   "una función nombrada obliga")
ok(obliga_a_tool("auto") is False, "`auto` no obliga")
ok(obliga_a_tool("none") is False, "`none` no obliga")
ok(obliga_a_tool(None) is False, "ausente no obliga")
ok(nombre_exigido({"type": "function", "function": {"name": "redline"}}) == "redline",
   "el nombre exigido se extrae")
ok(nombre_exigido("required") == "", "`required` no exige un nombre en particular")

print("\n── la garantía de no-regresión: sin tool_choice, el prompt es EL MISMO ──────")
base = render_prompt(MSGS, TOOLS)
ok(base == render_prompt(MSGS, TOOLS, None), "ausente ≡ None")
ok(base == render_prompt(MSGS, TOOLS, "auto"), "`auto` no cambia una coma")
ok("Para la RESPUESTA FINAL escribe texto normal" in base,
   "sin obligación sigue ofreciendo la respuesta final")
ok("<function=" in base, "el marcador sigue documentado (lo afirma verify_cli_sesiones)")
base_inc = render_prompt_incremental(MSGS, TOOLS)
ok(base_inc == render_prompt_incremental(MSGS, TOOLS, None), "incremental: ausente ≡ None")

print("\n── la obligación se DICE, y sin contradecirse dos líneas más abajo ──────────")
req = render_prompt(MSGS, TOOLS, "required")
ok("OBLIGATORIO EN ESTE PASO" in req, "el bloque de tools exige")
ok("Para la RESPUESTA FINAL escribe texto normal" not in req,
   "y deja de ofrecer la respuesta final")
ok("o la respuesta final" not in req,
   "la COLA del prompt tampoco la ofrece (si no, el prompt se contradice)")
ok("<function=" in req, "el marcador sigue documentado con obligación")

nom = render_prompt(MSGS, TOOLS, {"type": "function", "function": {"name": "redline"}})
ok("`redline`" in nom, "una función nombrada se nombra en el prompt")
ok("compute" in nom, "…y el resto del catálogo sigue visible (el modelo ve qué hay)")

inc = render_prompt_incremental(MSGS, TOOLS, "required")
ok("OBLIGATORIO EN ESTE PASO" in inc, "el incremental también exige")

print("\n── sin tools no hay obligación que decir ────────────────────────────────────")
vacio = render_prompt(MSGS, [], "required")
ok("OBLIGATORIO EN ESTE PASO" not in vacio,
   "exigir una tool sin catálogo sería pedir lo imposible")
ok("o la respuesta final" in vacio, "y la cola vuelve a la de siempre")

print("\n── el parseo no cambió: lo que no pasó, no se afirma ────────────────────────")
ok(extract_tool_calls("texto sin marcador") == [],
   "un texto sin marcador NO produce tool_calls (cero-teatro)")
ok(len(extract_tool_calls('<function=redline>{"a":1}</function>')) == 1,
   "un marcador real sí")

print("\n── EL SERVER COMPRUEBA: obligación sin marcador NO sale como texto ──────────")
# Provider de laboratorio: contesta texto plano, jamás pone el marcador. Es exactamente el
# caso que el prompt no puede garantizar — una instrucción se puede desobedecer.
import http.client   # noqa: E402
import json          # noqa: E402
import threading     # noqa: E402

from cli_brain import base as B                      # noqa: E402
from cli_brain import detect as _detect              # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider   # noqa: E402
from cli_brain.server import create_server           # noqa: E402


class _ProviderTerco(ClaudeCliProvider):
    """Le pidan lo que le pidan, contesta texto. No spawnea nada."""
    provider_id = "lab_terco"
    display_name = "Lab Terco"
    response_model_id = "lab-terco"

    def binary(self):
        return "/bin/true"

    def invoke(self, prompt, model=None, timeout=None, effort=None,
               on_evento=None, chunk_timeout=None, **_kw):
        _ProviderTerco.ultimo_prompt = prompt
        return B.BrainResult(ok=True, text="Listo, ya lo pensé.",
                             model_final="lab-modelo", model_final_source="cli-reported",
                             usage={"prompt_tokens": 1, "completion_tokens": 1})


_detect._BY_MODEL_ID["lab-terco"] = _ProviderTerco()
_srv = create_server(0)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
_puerto = _srv.server_address[1]


def _pedir(cuerpo):
    c = http.client.HTTPConnection("127.0.0.1", _puerto, timeout=30)
    c.request("POST", "/v1/chat/completions", json.dumps(cuerpo),
              {"Content-Type": "application/json", "Host": f"127.0.0.1:{_puerto}"})
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"{}")


_BASE = {"model": "lab-terco", "messages": [{"role": "user", "content": "hacelo"}],
         "tools": TOOLS}

st, cuerpo = _pedir(dict(_BASE))
ok(st == 200, f"sin obligación, el texto es una respuesta legítima (HTTP {st})")
ok(cuerpo.get("choices", [{}])[0].get("message", {}).get("content") == "Listo, ya lo pensé.",
   "…y vuelve tal cual")

st, cuerpo = _pedir(dict(_BASE, tool_choice="required"))
ok(st == 422, f"con `required` y sin marcador NO sale 200 (salió {st})")
ok(cuerpo.get("error", {}).get("type") == "tool_choice_no_honrado",
   "la causa tiene nombre propio")
ok(cuerpo.get("error", {}).get("causa", {}).get("soporte") == "prompt",
   "y DECLARA que el soporte es por prompt, no nativo — la diferencia importa")
ok(cuerpo.get("error", {}).get("causa", {}).get("texto_devuelto") == "Listo, ya lo pensé.",
   "el texto que sí vino viaja en la causa (no se tira, se reporta)")

ok("OBLIGATORIO EN ESTE PASO" in getattr(_ProviderTerco, "ultimo_prompt", ""),
   "y al CLI le llegó la obligación escrita en el prompt")

st, cuerpo = _pedir({"model": "lab-terco",
                     "messages": [{"role": "user", "content": "h"}],
                     "tool_choice": "required"})
ok(st == 200, "exigir una tool SIN catálogo no rompe el turno (no hay nada que exigir)")

_srv.shutdown()

print()
if _fallos:
    print(f"✗ {len(_fallos)} fallo(s):")
    for f in _fallos:
        print(f"   · {f}")
    raise SystemExit(1)
print("PASS tool_choice en el cerebro CLI: se dice en el prompt y se verifica en la salida")
