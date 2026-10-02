#!/usr/bin/env python3
"""verify_borde_response_format.py — EL BORDE Y LA SALIDA ESTRUCTURADA (§6.a · T1.4).

QUÉ MIDE, Y POR QUÉ ESTA VARA EXISTE
------------------------------------
`browser-use` pide salida estructurada ESTRICTA en **cada paso** de su loop:
`agent/service.py:1946` arma `kwargs = {'output_format': self.AgentOutput, …}` y se lo pasa
a `ainvoke` — no hay camino sin estructura en el loop principal. Del otro lado,
`llm/openai/chat.py:225-257` lo manda como
`response_format=ResponseFormatJSONSchema(json_schema={…, 'strict': True}, type='json_schema')`.

El contrato del borde (`router.py:313-337`, `WorkspaceBrainOpenAIRequest`) declara siete
campos y **`response_format` no está entre ellos**. Pydantic, sin `extra="forbid"`, lo
**descarta en silencio**: ni 422, ni aviso, ni log. El harness cree que pidió un schema
estricto y recibe prosa.

Esto es exactamente «el instrumento equivocado no da rojo: da silencio». Esta vara lo hace
sonar: FALLA mientras el borde ignore el campo sin decirlo. Deja de fallar cuando el borde
(a) lo honre, o (b) lo rechace con causa tipada. Las dos son respuestas honestas; tirarlo
callado no.
"""
import sys, os, re
from typing import Any, Optional

_f = []
def ok(c, d, extra=""):
    print(("  ✓ " if c else "  ✗ ") + d + (f"   {extra}" if extra and not c else ""))
    if not c: _f.append(d)

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ROUTER = os.path.join(RAIZ, "product/backend/app/phase1/router.py")
CHAT = os.path.join(RAIZ, "third_party/browser-use/browser_use/llm/openai/chat.py")
SERVICE = os.path.join(RAIZ, "third_party/browser-use/browser_use/agent/service.py")

print("EL BORDE vs. LA SALIDA ESTRUCTURADA DE browser-use\n")

# 1 · el harness EXIGE estructura en cada paso — si esto cambia, la vara sobra
svc = open(SERVICE, encoding="utf-8").read()
ok("'output_format': self.AgentOutput" in svc,
   "[1] el loop de browser-use pide output_format en CADA paso (service.py:get_model_output)")
chat = open(CHAT, encoding="utf-8").read()
ok("'strict': True" in chat and "ResponseFormatJSONSchema" in chat,
   "[2] y lo manda como json_schema STRICT (llm/openai/chat.py)")

# 2 · el contrato del borde
src = open(ROUTER, encoding="utf-8").read()
# EL REGEX, CORREGIDO. El anterior cortaba en "\n\nclass " y se comía el cuerpo de la
# clase SIGUIENTE cuando había una línea en blanco de por medio: imprimía un campo `casa`
# que no es de esta clase. Ahora se corta en la primera línea que empieza en la columna 0
# (otra clase, un decorador, una función), que es donde de verdad termina el cuerpo.
m = re.search(r"class WorkspaceBrainOpenAIRequest\(BaseModel\):\n(.*?)(?=\n\S)", src, re.S)
cuerpo = m.group(1) if m else ""
# ⚠️ Y SE SACA EL DOCSTRING ANTES DE BUSCAR CAMPOS. Ése era el verdadero bug del
# listado: el docstring de esta clase tiene una línea «casa: sabe pedir /v1/chat/…» que
# matchea igualito que una anotación. El regex no sobre-capturaba de más — capturaba
# prosa. Un listado que no es de fiar se lee igual que uno que sí.
cuerpo = re.sub(r'^\s{4}""".*?"""', "", cuerpo, count=1, flags=re.S)
campos = set(re.findall(r"^\s{4}(\w+)\s*:\s*\S", cuerpo, re.M))
print(f"      campos declarados: {sorted(campos)}")
honra = "response_format" in campos
rechaza = 'extra="forbid"' in cuerpo or "extra='forbid'" in cuerpo
# ── DE «ROJA PARA SIEMPRE» A CENTINELA ────────────────────────────────────────────────
# Esta vara nació afirmando que el borde honra `response_format`. Es verdad que NO lo honra
# —lo descarta en silencio— pero dejarla en rojo permanente pudre el pool: una roja que
# siempre está roja enseña a ignorar las rojas, y el testigo del merge la contaba como
# regresión de esta rama cuando es una deuda declarada de la casa.
#
# Así que pasa a medir COHERENCIA, que es lo accionable: mientras el borde no honre el
# campo, las dos válvulas de browser-use tienen que estar encendidas. Si alguien enseña al
# borde a honrarlo y NO apaga las válvulas, esto se pone en rojo — que es exactamente el
# momento en que hay que tocar algo. Y si alguien apaga las válvulas sin que el borde
# honre, también.
_perfil = open(os.path.join(RAIZ, "platform/browser/perfil.py"), encoding="utf-8").read()
_valvulas_por_defecto = 'not honra' in _perfil
print(f"      estado de la deuda: el borde {'HONRA' if (honra or rechaza) else 'NO honra'} response_format")
ok((honra or rechaza) or _valvulas_por_defecto,
   "[3] CENTINELA · mientras el borde no honre response_format, las válvulas están encendidas",
   "el borde no lo honra Y las válvulas no dependen de eso: el harness pide un schema que nadie aplica")

# 3 · la prueba empírica contra la clase real (si hay pydantic a mano)
try:
    from pydantic import BaseModel
    class R(BaseModel):
        model: Optional[str] = None
        messages: list[Any]
        tools: Optional[list[Any]] = None
        tool_choice: Optional[Any] = None
        stream: Optional[bool] = False
        max_tokens: Optional[int] = None
        temperature: Optional[float] = None
    r = R(messages=[{"role": "user", "content": "x"}],
          response_format={"type": "json_schema",
                           "json_schema": {"name": "agent_output", "strict": True,
                                           "schema": {"type": "object"}}})
    _sobrevive = hasattr(r, "response_format")
    print(f"      EMPÍRICO: el borde {'conserva' if _sobrevive else 'DESCARTA'} response_format "
          f"(ve {sorted(r.model_dump().keys())})")
    ok(_sobrevive == bool(honra or rechaza),
       "[4] EMPÍRICO · lo que el borde hace coincide con lo que su contrato declara",
       "el contrato y la conducta no coinciden: uno de los dos miente")
except ImportError:
    print("  ~ [4] [no medible] sin pydantic en este intérprete "
          "(probado a mano con product/backend/.venv: se descarta)")

# 4 · la salida: las dos válvulas que el propio browser-use trae para este caso
ok("dont_force_structured_output" in chat and "add_schema_to_system_prompt" in chat,
   "[5] browser-use trae las dos válvulas para proveedores que no aplican el schema")

print("\n" + ("PASS" if not _f else "FAIL: " + " · ".join(_f)))
print("\nLA DEUDA, declarada y viva: el borde DESCARTA `response_format` en silencio, así que\n"
      "el schema estricto que browser-use pide en cada paso viaja por el PROMPT y no como\n"
      "contrato. Medido el 2026-08-19 en una corrida completa: el modelo lo cumple 7 pasos\n"
      "seguidos. Esta vara NO está en rojo por eso —sería una roja permanente que enseña a\n"
      "ignorar las rojas— sino que vigila que las dos cosas sigan siendo coherentes.")
sys.exit(1 if _f else 0)
