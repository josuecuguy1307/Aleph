#!/usr/bin/env python3
"""verify_descarte_no_mudo.py — cuando el guard de pureza tira una generación, ¿se entera
alguien, y el reintento sale sabiendo qué pasó?

LAS DOS MITADES DEL MISMO DEFECTO, medido en Oficina el 2026-08-26: un turno volvió con
`ok: true` y una excusa inventada, y los 46,3 s con 8 acciones que el guard había
descartado NO estaban en ninguna superficie —el paso decía `tools_declared: 18 ·
tool_calls_requested: []` y nada más— ni el reintento sabía que existían: le llegó el
MISMO prompt, byte por byte.

  1. LA CAUSA LLEGA   `evidencia.acciones` cruza el cable y el paso del espacio lo anota
  2. EL REINTENTO SABE  el próximo intento del MISMO pedido lleva la corrección, una vez

⚠️ QUÉ **NO** MIDE: si el modelo obedece la corrección, ni el archivo en el disco.
"""
import sys, os, time

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))                       # platform/assembler
_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(_AQUI)))  # raíz del repo
sys.path.insert(0, os.path.join(_RAIZ, "product", "backend"))     # product/backend

_fallos = []


def ok(cond, que, detalle=""):
    print(("  ✓ " if cond else "  ✗ ") + que + (f"   [{detalle}]" if detalle else ""))
    if not cond:
        _fallos.append(que)


print("\n1 · LA CAUSA LLEVA EL NÚMERO (base.py)")
from cli_brain.base import _causa_del_wrapper                     # noqa: E402
c = _causa_del_wrapper("Codex ejecutó acciones por su cuenta", acciones=8)
ok(isinstance(c, dict), "el guard construye una causa tipada")
ev = (c or {}).get("evidencia") or {}
ok(ev.get("guard") == "wrapper_puro", "sigue marcada como el guard del wrapper puro")
ok(ev.get("acciones") == 8, "y ahora dice CUÁNTAS acciones se tiraron", str(ev))
# Sin número no se inventa un cero: un `acciones: 0` en la evidencia se leería como
# «descartó una generación que no hizo nada», que es una frase falsa.
ok("acciones" not in ((_causa_del_wrapper("x") or {}).get("evidencia") or {}),
   "sin número no se inventa un cero")

print("\n2 · EL PASO DEL ESPACIO LO ANOTA (workspace_brain.py)")
from app.phase1 import workspace_brain as wb                      # noqa: E402


class _AsmFalso:
    def _emit_model_cost_event(self, *a, **k):
        pass


def paso_con(route):
    vistos = []
    wb._cerrar_paso(
        _AsmFalso(), {"model_route": route}, model_final="m", model_used="m",
        msg={"content": "texto", "tool_calls": []}, finish_reason="stop", usage=None,
        on_event=vistos.append, user_id="u", run_id=None, workspace="oficina", turn=4,
        tools=[{"function": {"name": "write"}}], is_byok=False,
        repliegue=None, tools_pedidas=1)
    return [e for e in vistos if e.get("type") == "workspace_step"][0]


_DESCARTE = {"model": "codex-cli", "tier": "primary", "ok": False,
             "error": "descartado", "causa": {"causa": "falla_de_aleph",
                                              "evidencia": {"guard": "wrapper_puro",
                                                            "acciones": 8}}}
p = paso_con([_DESCARTE, {"model": "codex-cli", "tier": "primary", "ok": True}])
ok("descartes_por_pureza" in p, "el paso anota el descarte")
ok(p.get("descartes_por_pureza") == [{"model": "codex-cli", "tier": "primary",
                                      "acciones": 8}],
   "con el modelo, el tier y las acciones", str(p.get("descartes_por_pureza")))
ok(p.get("tool_calls_requested") == [],
   "y NO toca lo que ya decía el paso (el turno igual no pidió tools)")

limpio = paso_con([{"model": "m", "tier": "primary", "ok": True}])
ok("descartes_por_pureza" not in limpio,
   "un paso sano no lleva el campo — un campo que está siempre es ruido en toda la casa")

otro = paso_con([{"model": "m", "tier": "primary", "ok": False,
                  "causa": {"causa": "timeout", "evidencia": {}}},
                 {"model": "m", "tier": "fallback", "ok": True}])
ok("descartes_por_pureza" not in otro,
   "un tier que cayó por OTRA causa no se cuenta como descarte de pureza")

# LA TRAMPA QUE SE EVITÓ: matchear la frase. Una fila cuyo TEXTO habla de acciones pero
# cuya causa tipada no es la del guard NO cuenta — el patrón de texto matchea más de lo
# que su autor cree.
texto = paso_con([{"model": "m", "tier": "primary", "ok": False,
                   "error": "ejecutó 8 acción(es) por su cuenta — descartado"},
                  {"model": "m", "tier": "primary", "ok": True}])
ok("descartes_por_pureza" not in texto,
   "no se infiere del texto: sin la marca TIPADA no hay descarte")

print("\n3 · EL REINTENTO SALE SABIENDO (server.py)")
from cli_brain.server import (_marcar_impureza, _preludio_de_impureza,   # noqa: E402
                              _IMPUREZA, _IMPUREZA_MAX)

_IMPUREZA.clear()
PROMPT = "HERRAMIENTAS DISPONIBLES...\n[Usuario]: armá la planilla"
ok(_preludio_de_impureza("codex_cli", PROMPT) == "",
   "un pedido virgen NO lleva corrección (fail-open)")

_marcar_impureza("codex_cli", PROMPT, 8)
pre = _preludio_de_impureza("codex_cli", PROMPT)
ok(pre != "", "después de un descarte, el mismo pedido SÍ la lleva")
ok("8 acción(es)" in pre, "y dice el número medido, no una generalidad")
ok("descartó TODA la respuesta" in pre, "dice qué se perdió")
ok("<function=NOMBRE>" in pre, "y dice qué hacer en vez de eso")
ok("no inventes" in pre.lower(), "y prohíbe la excusa inventada")

ok(_preludio_de_impureza("codex_cli", PROMPT) == "",
   "SE CONSUME: el segundo intento no arrastra la corrección del primero")

_marcar_impureza("codex_cli", PROMPT, 8)
ok(_preludio_de_impureza("codex_cli", PROMPT + " otra cosa") == "",
   "otro pedido NO hereda la marca")
ok(_preludio_de_impureza("grok_cli", PROMPT) == "",
   "otro provider tampoco")
ok(_preludio_de_impureza("codex_cli", PROMPT) != "",
   "y la marca original sigue ahí, intacta")

_IMPUREZA.clear()
_marcar_impureza("codex_cli", PROMPT, 3)
for k in _IMPUREZA:
    _IMPUREZA[k]["ts"] = time.time() - 10_000
ok(_preludio_de_impureza("codex_cli", PROMPT) == "",
   "una marca vencida no habla (TTL)")

_IMPUREZA.clear()
for i in range(_IMPUREZA_MAX + 40):
    _marcar_impureza("codex_cli", f"{PROMPT}#{i}", 1)
ok(len(_IMPUREZA) <= _IMPUREZA_MAX,
   "el mapa no crece sin techo", f"{len(_IMPUREZA)} ≤ {_IMPUREZA_MAX}")
_IMPUREZA.clear()

print("\n" + ("✅ TODO VERDE" if not _fallos else f"🔴 {len(_fallos)} ROJAS"))
for f in _fallos:
    print("   ·", f)
sys.exit(1 if _fallos else 0)
