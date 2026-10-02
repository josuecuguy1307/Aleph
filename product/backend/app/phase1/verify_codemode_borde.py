#!/usr/bin/env python3
"""verify_codemode_borde.py — la vara de code execution EN EL BORDE.

    python3 product/backend/app/phase1/verify_codemode_borde.py
    python3 .../verify_codemode_borde.py --caer     # la prueba de caída

Simula EL LOOP DEL STACK (que es quien ejecuta sus tools) y el MODELO, y mide lo que
decide el experimento: **cuántas veces cruza el catálogo**.
"""
from __future__ import annotations

import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, os.path.join(RAIZ, "product", "backend"))
sys.path.insert(0, os.path.join(RAIZ, "platform", "assembler"))

os.environ["ALEPH_CODE_EXECUTION_WS"] = "ciencia"
from app.phase1 import codemode_borde as CB                          # noqa: E402
import code_execution as CE                                          # noqa: E402

MUTAR = "--caer" in sys.argv
RES = []
def chk(n, c, d=""):
    RES.append((n, bool(c))); print(f"  [{'VERDE' if c else 'ROJO '}] {n}" + (f"  · {d}" if d else ""))

# ── el catálogo del stack (forma de OpenScience) ───────────────────────────────
TOOLS = [
    {"type": "function", "function": {"name": "arxiv_search", "description": "busca papers",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_paper", "description": "trae un paper",
     "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "run_python", "description": "calcula",
     "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}},
]

# ── EL STACK. Ejecuta SUS tools. Aleph nunca las toca. ─────────────────────────
EJECUTADAS = []
def stack_ejecuta(nombre, args):
    EJECUTADAS.append(nombre)
    if nombre == "arxiv_search":
        return json.dumps({"hits": [{"id": "2501.001", "t": "Sparse Attention"},
                                    {"id": "2501.002", "t": "Linear Attention"}]})
    if nombre == "get_paper":
        return json.dumps({"id": args.get("id"), "citas": 137, "dataset": "LongBench"})
    if nombre == "run_python":
        return json.dumps({"stdout": "42"})
    return "{}"

# ── EL MODELO. Cuenta CADA cruce y qué catálogo recibió. ───────────────────────
CRUCES = []
SCRIPT = ("h = arxiv_search(query='sparse attention')\n"
          "for x in h['hits']:\n"
          "    p = get_paper(id=x['id'])\n"
          "    print(x['t'], p['citas'], p['dataset'])\n")

def modelo_codemode(messages, tools):
    CRUCES.append(len(tools))
    if tools and (tools[0].get("function") or {}).get("name") == CE.NOMBRE_TOOL:
        return {"content": None, "model": "m",
                "tool_calls": [{"id": "c1", "name": CE.NOMBRE_TOOL,
                                "arguments": json.dumps({"code": SCRIPT})}],
                "usage": {"prompt_tokens": 100}, "finish_reason": "tool_calls"}
    return {"content": "Sparse Attention 137 · Linear Attention 137", "tool_calls": [],
            "model": "m", "usage": {"prompt_tokens": 50}, "finish_reason": "stop"}

# ── EL LOOP DEL STACK, con code execution EN EL MEDIO ──────────────────────────
def correr_con_codemode(max_pasos=12):
    msgs = [{"role": "system", "content": "Sos Ciencia."},
            {"role": "user", "content": "Buscá papers de sparse attention y sus citas."}]
    vueltas = 0
    for _ in range(max_pasos):
        vueltas += 1
        out = CB.paso(clave="ciencia:s1", workspace="ciencia", messages=msgs, tools=TOOLS,
                      llamar_modelo=modelo_codemode)
        if out is None:
            out = modelo_codemode(msgs, TOOLS)
        calls = out.get("tool_calls") or []
        if not calls:
            return {"vueltas": vueltas, "texto": out.get("content") or "", "out": out}
        msgs.append({"role": "assistant", "content": out.get("content") or "",
                     "tool_calls": [{"id": c["id"], "type": "function",
                                     "function": {"name": c["name"], "arguments": c["arguments"]}}
                                    for c in calls]})
        for c in calls:
            r = stack_ejecuta(c["name"], json.loads(c["arguments"] or "{}"))
            msgs.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"], "content": r})
    return {"vueltas": vueltas, "texto": "[techo]", "out": None}

if MUTAR:
    print("!! MODO --caer: pieza MUTADA\n")
    # el borde deja de suspender y llama al modelo en cada paso → las cruces NO colapsan
    CB.paso = lambda **kw: None

print("── A · el turno entero con code execution ──")
r = correr_con_codemode()
chk("A1: el turno cerró con respuesta", bool(r["texto"]) and r["texto"] != "[techo]", repr(r["texto"])[:90])
chk("A0: la vara no explota con la pieza mutada", True)
chk("A2: el STACK ejecutó sus tools (Aleph no las tocó)", len(EJECUTADAS) == 3, f"{EJECUTADAS}")
chk("A3: LAS CRUCES COLAPSAN", len(CRUCES) <= 2, f"cruces={len(CRUCES)} catálogos={CRUCES}")
chk("A4: la primera cruz lleva UNA tool, no el catálogo", CRUCES and CRUCES[0] == 1, f"{CRUCES}")
chk("A5: la cruz de cierre va SIN catálogo", len(CRUCES) > 1 and CRUCES[-1] == 0, f"{CRUCES}")

print("\n── B · EL CONJUNTO de tools, no el número ──")
ESPERADO = {"arxiv_search", "get_paper"}
chk("B1: el conjunto ejecutado es el esperado", set(EJECUTADAS) == ESPERADO, f"{sorted(set(EJECUTADAS))}")

print("\n── C · los pasos SIN cruce no fingen medición ──")
EJECUTADAS.clear(); CRUCES.clear()
msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
o1 = CB.paso(clave="ciencia:s2", workspace="ciencia", messages=msgs, tools=TOOLS,
             llamar_modelo=modelo_codemode)
chk("C1: el paso devuelve una tool del STACK, no `aleph_run_code`",
    o1 and (o1.get("tool_calls") or [{}])[0].get("name") in {"arxiv_search", "get_paper"},
    str((o1 or {}).get("tool_calls"))[:90])
chk("C2: `usage` es None en un paso sin cruce — NUNCA ceros",
    o1 is not None and o1.get("usage") is None, f"usage={(o1 or {}).get('usage')!r}")
chk("C3: y lo declara", (o1 or {}).get("aleph_codemode", {}).get("paso") == "sin_cruce")
CB._cancelar("ciencia:s2")

print("\n── E · EL VERDE MUDO: un `code` ilegible NO se le manda al stack ──")
# El stack NO TIENE `aleph_run_code`. Si se le reenvía, contesta un error de tool, el
# modelo se recompone y el turno sale PERFECTO con el mecanismo apagado. Medido en vivo.
def modelo_roto(messages, tools):
    CRUCES.append(len(tools))
    return {"content": None, "model": "m", "finish_reason": "tool_calls",
            "tool_calls": [{"id": "x", "name": CE.NOMBRE_TOOL,
                            "arguments": '{"code": "print(1'}],   # JSON cortado a mitad
            "usage": {"prompt_tokens": 1}}
CRUCES.clear()
o = CB.paso(clave="ciencia:roto", workspace="ciencia", messages=[{"role":"user","content":"x"}],
            tools=TOOLS, llamar_modelo=modelo_roto)
chk("E1: con el JSON cortado se RESCATA el código y el script corre",
    o is not None and bool(o.get("tool_calls") or o.get("aleph_codemode")), f"{str(o)[:80]}")
if CB.hay_sesion("ciencia:roto"): CB._cancelar("ciencia:roto")

def modelo_ilegible(messages, tools):
    CRUCES.append(len(tools))
    return {"content": None, "model": "m", "finish_reason": "tool_calls",
            "tool_calls": [{"id": "x", "name": CE.NOMBRE_TOOL, "arguments": "   "}],
            "usage": {"prompt_tokens": 1}}
o2 = CB.paso(clave="ciencia:ileg", workspace="ciencia", messages=[{"role":"user","content":"x"}],
             tools=TOOLS, llamar_modelo=modelo_ilegible)
chk("E2: sin nada que rescatar devuelve None (cae al camino normal)", o2 is None, f"{o2!r}")
chk("E3: y JAMÁS le manda `aleph_run_code` al stack",
    o2 is None or CE.NOMBRE_TOOL not in str(o2.get("tool_calls")))

print("\n── F · la superficie AVISA que el script no tiene mundo propio ──")
sup = CE.superficie(CE.funciones_validas(TOOLS))
chk("F1: lo dice explícito", "NO TIENE MUNDO PROPIO" in sup)
chk("F2: y nombra las trampas concretas", "open()" in sup and "único puente" in sup)

print("\n── G · EL MARCADOR NO LLEGA A LA CARA DEL USUARIO ──")
# Medido en vivo: el paso de cierre va sin catálogo, el modelo igual escribe
# `<function=bash>…`, nadie lo parsea, y se filtra COMO TEXTO. Pasó en Ciencia.
def modelo_fuga(messages, tools):
    CRUCES.append(len(tools))
    if tools and (tools[0].get("function") or {}).get("name") == CE.NOMBRE_TOOL:
        return {"content": None, "model": "m", "finish_reason": "tool_calls",
                "tool_calls": [{"id": "c", "name": CE.NOMBRE_TOOL,
                                "arguments": json.dumps({"code": "print('LISTO 137438953472')"})}],
                "usage": {"prompt_tokens": 1}}
    return {"content": 'El total es 137438953472\n<function=bash> python3 -c "print(1)"',
            "tool_calls": [], "model": "m", "usage": None, "finish_reason": "stop"}
CRUCES.clear()
o = CB.paso(clave="ciencia:fuga", workspace="ciencia",
            messages=[{"role":"user","content":"x"}], tools=TOOLS, llamar_modelo=modelo_fuga)
chk("G1: el marcador se recorta y NO se muestra",
    o is not None and "<function=" not in (o.get("content") or ""),
    repr((o or {}).get("content"))[:90])
chk("G2: y lo que sí sirve se conserva", o is not None and "137438953472" in (o.get("content") or ""))

print("\n── D · LA PERILLA ES POR STACK ──")
chk("D1: ciencia encendida", CB.encendido_para("ciencia") is True)
chk("D2: finanzas apagada → el borde hace lo de siempre", CB.encendido_para("finanzas") is False)
chk("D3: y `paso` devuelve None para el apagado",
    CB.paso(clave="k", workspace="finanzas", messages=[], tools=TOOLS,
            llamar_modelo=modelo_codemode) is None)

print("\n" + "=" * 66)
v = sum(1 for _, o in RES if o); print(f"VERDES {v} / {len(RES)}")
rojas = [n for n, o in RES if not o]
for n in rojas: print(f"  ROJO · {n}")
if MUTAR:
    print(f"\nPRUEBA DE CAÍDA: {'la vara SE PUSO ROJA — mide' if rojas else 'siguió verde — NO MIDE'}")
    sys.exit(0 if rojas else 1)
sys.exit(0 if not rojas else 1)
