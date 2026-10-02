#!/usr/bin/env python3
"""verify_timeout_en_segundos.py — UN `timeout` EN SEGUNDOS NO PUEDE MATAR LA OBRA.

    python3 qa/verify_timeout_en_segundos.py

QUÉ MIDE, y de dónde salió. Medido en Oficina el 2026-08-28 contra la `.app` instalada
`1a5b6aef`, con `ALEPH_GRABAR_PROMPT`: el modelo pidió

    bash{"command":"python3 -c '…openpyxl…'", "timeout":120, "workdir":"…"}

pensando en SEGUNDOS. El schema que el stack declara es `"Optional timeout in
milliseconds"` con `exclusiveMinimum: 0`, así que **120 es contract-válido** y nadie lo
atrapó: `third_party/dochaus/packages/opencode/src/tool/shell.ts:629` valida sólo `< 0`.
El comando murió a los 120 ms, volvió `(no output)` + `<shell_metadata>`, la pantalla
pintó «Aborted» sin causa y el turno produjo CERO obra en 28,7 s.

El arreglo es de ALEPH y vive en el único punto por donde pasan las dos vías
(`workspace_brain._cerrar_paso`). El stack no se toca.

LO QUE ESTA VARA AFIRMA (y lo hace CAYENDO primero, con `--romper`):
  1. un `timeout` por debajo del piso se reinterpreta como segundos y se multiplica;
  2. un `timeout` plausible en ms NO se toca (no se rompe a quien ya venía bien);
  3. la corrección se DECLARA — nunca es muda;
  4. la decisión se toma contra el schema que declara CADA tool, no contra el nombre del
     campo: una tool que declare segundos queda intacta.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "product" / "backend"))
sys.path.insert(0, str(_RAIZ / "platform"))

ROMPER = os.environ.get("ROMPER", "")
_ROJAS = 0


def ok(cond, titulo, detalle=""):
    global _ROJAS
    if not cond:
        _ROJAS += 1
    print(f"  {'✅' if cond else '❌'} {titulo}" + (f"   [{detalle}]" if detalle else ""))


from app.phase1 import workspace_brain as WB   # noqa: E402

#: El schema REAL que Oficina declara, copiado del tap (`ALEPH_GRABAR_PROMPT`), no
#: inventado: es la forma contra la que se decide.
TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to execute"},
                "timeout": {"type": "integer", "exclusiveMinimum": 0,
                            "description": "Optional timeout in milliseconds"},
                "workdir": {"type": "string", "description": "The working directory"},
            },
            "required": ["command"],
        },
    },
}]

#: Una tool que declara SEGUNDOS. Es el control que impide que el arreglo se vuelva una
#: convención de la casa aplicada a ciegas.
TOOLS_EN_SEGUNDOS = [{
    "type": "function",
    "function": {
        "name": "esperar",
        "parameters": {"type": "object", "properties": {
            "timeout": {"type": "integer", "description": "Timeout in seconds"}}},
    },
}]


def llamada(nombre, args):
    return [{"id": "call_1", "name": nombre, "arguments": json.dumps(args)}]


print("\n── el timeout en segundos ──────────────────────────────────────────────")

# 1 · el caso medido
calls = llamada("bash", {"command": "python3 -c 'print(1)'", "timeout": 120})
if ROMPER == "no_corrige":
    corr = []                                   # el mundo de antes del arreglo
else:
    corr = WB._normalizar_timeouts(calls, TOOLS)
args = json.loads(calls[0]["arguments"])
ok(args.get("timeout") == 120000,
   "timeout:120 (segundos) → 120000 ms",
   f"quedó en {args.get('timeout')}")
ok(args.get("command") == "python3 -c 'print(1)'",
   "el resto de los argumentos queda intacto")

# 2 · no se rompe a quien ya venía bien
calls2 = llamada("bash", {"command": "ls", "timeout": 5000})
corr2 = WB._normalizar_timeouts(calls2, TOOLS)
ok(json.loads(calls2[0]["arguments"])["timeout"] == 5000,
   "un timeout plausible en ms (5000) NO se toca")
ok(corr2 == [], "y no se declara corrección donde no la hubo")

# 3 · la corrección se declara
if ROMPER == "muda":
    corr = []
ok(len(corr) == 1 and corr[0].get("pedido") == 120 and corr[0].get("aplicado") == 120000,
   "la corrección se DECLARA con lo pedido y lo aplicado",
   json.dumps(corr, ensure_ascii=False))

# 4 · una tool que declara segundos queda intacta
calls3 = llamada("esperar", {"timeout": 30})
corr3 = WB._normalizar_timeouts(calls3, TOOLS_EN_SEGUNDOS)
ok(json.loads(calls3[0]["arguments"])["timeout"] == 30,
   "una tool que declara SEGUNDOS no se toca",
   f"quedó en {json.loads(calls3[0]['arguments'])['timeout']}")
ok(corr3 == [], "y tampoco se declara corrección sobre ella")

# 5 · lo que no es nuestro no se toca
calls4 = [{"id": "c", "name": "bash", "arguments": "no soy json"}]
WB._normalizar_timeouts(calls4, TOOLS)
ok(calls4[0]["arguments"] == "no soy json", "arguments que no es JSON queda igual")
calls5 = llamada("bash", {"command": "ls", "timeout": True})
WB._normalizar_timeouts(calls5, TOOLS)
ok(json.loads(calls5[0]["arguments"])["timeout"] is True,
   "un booleano no se confunde con un timeout chico")


print("\n── la causa enterrada llega a la superficie ────────────────────────────")

#: El `role:"tool"` REAL del turno de Oficina, copiado del tap. No es una maqueta.
TOOL_MUERTA = {
    "role": "tool", "name": "bash", "tool_call_id": "call_1",
    "content": ("(no output)\n\n<shell_metadata>\nshell tool terminated command after "
                "exceeding timeout 120 ms. If this command is expected to take longer and "
                "is not waiting for interactive input, retry with a larger timeout value "
                "in milliseconds.\n</shell_metadata>"),
}

causas = [] if ROMPER == "causa_muda" else WB._causas_de_tools_fallidas([TOOL_MUERTA])
ok(len(causas) == 1, "una tool muerta produce UNA causa", f"{len(causas)}")
c = causas[0] if causas else {}
ok(c.get("tipo") == "timeout_de_tool", "la causa está TIPADA, no es texto suelto",
   str(c.get("tipo")))
ok(c.get("timeout_ms") == 120, "y trae el número que la explica", str(c.get("timeout_ms")))
ok(bool(c.get("copy")), "y trae COPY — ninguna causa llega pelada a una superficie",
   str(c.get("copy"))[:60])
ok("120" in str(c.get("copy")), "el copy dice el número, no una generalidad")

# el control: una tool que SÍ produjo salida no es un fallo
VIVA = {"role": "tool", "name": "bash",
        "content": "gastos.xlsx\n\n<shell_metadata>\nexit code 0\n</shell_metadata>"}
ok(WB._causas_de_tools_fallidas([VIVA]) == [],
   "una tool que produjo salida NO se reporta como fallo")

# una causa que no conocemos sale igual, marcada — nunca muda
RARA = {"role": "tool", "name": "bash",
        "content": "(no output)\n\n<shell_metadata>\nkilled by signal 9\n</shell_metadata>"}
r = WB._causas_de_tools_fallidas([RARA])
ok(len(r) == 1 and r[0].get("provisional") is True,
   "una causa NUEVA sale igual y marcada `provisional`")
ok(bool(r[0].get("copy")) and "signal 9" in r[0].get("detalle", ""),
   "con copy y con el detalle crudo del stack")

print(f"\n{'ROJAS: %d' % _ROJAS if _ROJAS else 'TODO VERDE'}\n")
sys.exit(1 if _ROJAS else 0)
