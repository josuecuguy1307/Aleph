#!/usr/bin/env python3
"""verify_homonimia.py — ¿el puente AVISA cuando las tools del harness se llaman igual
que las del CLI, y se calla cuando no?

⚠️ QUÉ MIDE Y QUÉ **NO**. Mide el PROMPT: que el aviso aparezca con homonimia, que no
aparezca sin ella, que nombre los nombres reales y que diga la consecuencia. **No mide si
el modelo obedece** —eso son turnos contra un CLI vivo— ni el archivo en el disco, que es
la vara de verdad del caso de Oficina. Decirlo acá es parte de la vara: un verde de este
archivo NO autoriza a decir «Oficina ya produce su .xlsx».

El defecto que cubre: Oficina declara 18 tools y 9 se llaman igual que las del cerebro
(`bash`, `write`, `edit`, `read`, `grep`, `glob`, `task`, `webfetch`, `todowrite`). El
modelo usaba LAS SUYAS, el guard de pureza descartaba la generación entera, y el reintento
salía pidiendo permisos que nadie le negó (`@oai/artifact-tool`, «acceso de escritura»).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli_brain.prompt_bridge import homonimas, render_prompt   # noqa: E402

_fallos = []


def ok(cond, que, detalle=""):
    print(("  ✓ " if cond else "  ✗ ") + que + (f"   [{detalle}]" if detalle else ""))
    if not cond:
        _fallos.append(que)


def tools(*nombres):
    return [{"type": "function",
             "function": {"name": n, "description": f"desc de {n}",
                          "parameters": {"type": "object", "properties": {}}}}
            for n in nombres]


MSG = [{"role": "user", "content": "armá la planilla"}]

print("\n1 · LA DETECCIÓN — nombres reales, no parecidos")
# El catálogo REAL de Oficina, medido contra el motor vivo el 2026-08-27
# (`GET /opencode/experimental/tool`): 18 tools, 9 homónimas.
OFICINA = ("invalid", "question", "bash", "read", "glob", "grep", "edit", "write",
           "task", "webfetch", "todowrite", "skill", "browser_version", "browser_list",
           "browser_navigate", "browser_snapshot", "browser_click", "browser_fill",
           "browser_eval", "browser_screenshot")
h = homonimas(tools(*OFICINA))
ok(h == ["bash", "read", "glob", "grep", "edit", "write", "task", "webfetch", "todowrite"],
   "el catálogo de Oficina da las 9 homónimas, en el orden en que las declaró el stack",
   str(h))
ok(homonimas(tools("render_component", "apply_theme", "export_png")) == [],
   "un catálogo de dominio (Diseño) no dispara nada")
# LA REGLA QUE SE ELIGIÓ: hechos, no familia semántica. Un sinónimo plausible que el CLI
# NO tiene no es una homonimia; avisar de él le saca crédito al aviso que sí importa.
ok(homonimas(tools("search", "find", "list", "create", "run", "delegate")) == [],
   "los sinónimos plausibles NO cuentan: sólo nombres que el CLI tiene de verdad")
ok(homonimas(tools("Todo_Write", "WRITE", "applyPatch")) ==
   ["Todo_Write", "WRITE", "applyPatch"],
   "el estilo del stack no importa (mayúsculas y separadores) y vuelve el nombre TAL CUAL")
ok(homonimas([]) == [] and homonimas(None) == [],
   "sin tools no hay homonimia y no revienta")

print("\n2 · EL AVISO EN EL PROMPT")
p_of = render_prompt(MSG, tools(*OFICINA), None)
p_dis = render_prompt(MSG, tools("render_component", "apply_theme"), None)
p_sin = render_prompt(MSG, [], None)
ok("ATENCIÓN" in p_of, "con homonimia, el aviso está")
ok("ATENCIÓN" not in p_dis, "sin homonimia, el aviso NO está (no se cobran tokens de más)")
ok("ATENCIÓN" not in p_sin, "sin tools, no hay bloque de tools ni aviso")
for n in ("`bash`", "`write`", "`edit`"):
    ok(n in p_of, f"el aviso nombra {n}")
ok("`skill`" not in p_of.split("ATENCIÓN")[1],
   "el aviso NO nombra las que no chocan")
ok("DESCARTA" in p_of and "ENTERA" in p_of,
   "el aviso dice la CONSECUENCIA — «no lo hagas» sin costo pierde contra el prompt "
   "de sistema del CLI")
ok("No inventes herramientas ni permisos" in p_of,
   "el aviso prohíbe explícitamente la excusa inventada (`@oai/artifact-tool`)")
ok(p_of.index("ATENCIÓN") > p_of.index("Reglas:"),
   "el aviso va ÚLTIMO del bloque: es lo último que lee antes de la conversación")

print("\n3 · NO ROMPE LO QUE YA ANDABA")
ok(p_of.index("ATENCIÓN") < p_of.index("=== CONVERSACIÓN ==="),
   "el aviso queda dentro del bloque de tools, no pisa la conversación")
ok("<function=NOMBRE>" in p_of, "el ejemplo del marcador sigue en su lugar")
ok(len(p_dis) == len(render_prompt(MSG, tools("render_component", "apply_theme"), None)),
   "el render es determinista")

print("\n" + ("✅ TODO VERDE" if not _fallos else f"🔴 {len(_fallos)} ROJAS"))
for f in _fallos:
    print("   ·", f)
sys.exit(1 if _fallos else 0)
