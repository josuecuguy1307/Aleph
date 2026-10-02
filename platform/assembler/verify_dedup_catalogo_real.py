#!/usr/bin/env python3
"""VARA DE AUDITORÍA — el colapso contra los 94 schemas REALES de Finanzas.

No usa un fixture: usa el `messages` + `tools` capturados en un turno real desde la
pantalla (tap read-only sobre `prompt_bridge.render_prompt`, arm dedup=OFF).
Cada mutante tiene que dejar el inventario INTACTO. Un mutante que colapse = ROJO.
"""
import copy, json, os, sys, pathlib

if not os.environ.get("ALEPH_DEDUP_FIXTURE_ROOT"):
    raise SystemExit("BLOCKED: set ALEPH_DEDUP_FIXTURE_ROOT to authorized fixture root")
SP = pathlib.Path(os.environ["ALEPH_DEDUP_FIXTURE_ROOT"]).resolve()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cli_brain.tool_inventory_dedup import colapsar_inventario_textual  # noqa: E402

_IFR = None
RAW = json.load(open(SP / "tap-A" / "cruce_0000_full.raw.json"))
MSGS, TOOLS = RAW["messages"], RAW["tools"]
_IFR = [t.get("function", t)["name"] for t in TOOLS].index("financial_rigor")
print(f"financial_rigor está en la posición {_IFR} del orden de registro")

fallos = []
def check(ok, etiqueta, extra=""):
    print(("OK  " if ok else "ROJO ") + etiqueta + (f"   [{extra}]" if extra else ""))
    if not ok:
        fallos.append(etiqueta)

# ── 0 · el caso base: sobre el dato real, colapsa ────────────────────────────────
out, changed, removed = colapsar_inventario_textual(MSGS, TOOLS)
check(changed and removed == 74265, f"BASE colapsa sobre el turno real (retira {removed} chars)")
check(len(TOOLS) == 94, "BASE los 94 schemas siguen enteros", str(len(TOOLS)))
sys_a = [m for m in MSGS if m.get("role") == "system"][0]["content"]
sys_b = [m for m in out if m.get("role") == "system"][0]["content"]
check("### financial_rigor" in sys_a and "### financial_rigor" not in sys_b,
      "BASE el inventario textual se va y el estructurado queda")
check(MSGS == RAW["messages"], "BASE la entrada NO se muta")

# ── MUTANTES: cada uno tiene que dejar TODO intacto ──────────────────────────────
def mutar(etiqueta, fn):
    ts = copy.deepcopy(TOOLS)
    fn(ts)
    o, c, r = colapsar_inventario_textual(MSGS, ts)
    check((not c) and r == 0 and o == MSGS
          and all(x is y for x, y in zip(o, MSGS)), f"fail-closed · {etiqueta}",
          "COLAPSÓ IGUAL" if c else "")

mutar("nombre de una tool cambiado",
      lambda ts: ts[_IFR]["function"].__setitem__("name", "financial_rigour"))
mutar("descripción cambiada en UN carácter",
      lambda ts: ts[0]["function"].__setitem__(
          "description", ts[0]["function"]["description"] + "."))
mutar("`required` cambiado",
      lambda ts: ts[_IFR]["function"]["parameters"].__setitem__("required", []))
mutar("orden de las tools invertido", lambda ts: ts.reverse())
mutar("dos tools intercambiadas (misma longitud total)",
      lambda ts: ts.__setitem__(slice(3, 5), [ts[4], ts[3]]))
mutar("una tool MENOS", lambda ts: ts.pop(50))
mutar("una tool MÁS (duplicada)", lambda ts: ts.insert(50, copy.deepcopy(ts[50])))

def _desc_param(ts):
    p = ts[_IFR]["function"]["parameters"]["properties"]["command"]
    p["description"] = p["description"] + " "
mutar("descripción DE UN PARÁMETRO cambiada", _desc_param)

def _orden_props(ts):
    fn = ts[_IFR]["function"]["parameters"]
    props = fn["properties"]
    fn["properties"] = dict(reversed(list(props.items())))
mutar("orden de los PARÁMETROS invertido", _orden_props)

mutar("un parámetro nuevo",
      lambda ts: ts[_IFR]["function"]["parameters"]["properties"].__setitem__(
          "zz_extra", {"type": "string", "description": "x"}))
mutar("parameters vaciado (→ `(no params)`)",
      lambda ts: ts[_IFR]["function"].__setitem__("parameters", {}))
mutar("description que no es str",
      lambda ts: ts[_IFR]["function"].__setitem__("description", None))

# ── MUTANTES DEL MENSAJE ─────────────────────────────────────────────────────────
def mutar_msgs(etiqueta, fn):
    ms = copy.deepcopy(MSGS)
    fn(ms)
    o, c, r = colapsar_inventario_textual(ms, TOOLS)
    check((not c) and r == 0 and o == ms
          and all(x is y for x, y in zip(o, ms)), f"fail-closed · {etiqueta}",
          "COLAPSÓ IGUAL" if c else "")

def _amb(ms):
    ms[0]["content"] += "\n## Tools\n\notro inventario"
mutar_msgs("delimitador de apertura DUPLICADO", _amb)

def _amb2(ms):
    ms[0]["content"] += "\n\n## Skills (use load_skill to read full docs)"
mutar_msgs("delimitador de cierre DUPLICADO", _amb2)

def _sin_cierre(ms):
    ms[0]["content"] = ms[0]["content"].replace(
        "\n\n## Skills (use load_skill to read full docs)", "\n\n## Skills", 1)
mutar_msgs("delimitador de cierre AUSENTE", _sin_cierre)

def _un_char(ms):
    c = ms[0]["content"]
    i = c.index("### financial_rigor")
    ms[0]["content"] = c[:i] + "###  financial_rigor" + c[i+19:]
mutar_msgs("UN espacio de más dentro del inventario", _un_char)

def _no_system(ms):
    ms[0]["role"] = "user"
mutar_msgs("el bloque viaja en un mensaje que NO es system", _no_system)

# ── SIN DUPLICACIÓN: un stack que no repite (el caso de los otros 6) ─────────────
sin_dup = [{"role": "system", "content": "Sos un asistente. Sin inventario textual."},
           {"role": "user", "content": "hola"}]
o, c, r = colapsar_inventario_textual(sin_dup, TOOLS)
# igualdad de contenido Y identidad de cada mensaje: prueba que no reescribió ninguno
check((not c) and r == 0 and o == sin_dup
      and all(x is y for x, y in zip(o, sin_dup)),
      "stack SIN duplicación → el borde no toca nada")

o, c, r = colapsar_inventario_textual([], TOOLS)
check((not c) and r == 0, "sin mensajes → no toca nada")
o, c, r = colapsar_inventario_textual(MSGS, [])
check((not c) and r == 0 and o is MSGS, "sin schemas → no toca nada")

print()
if fallos:
    print(f"ROJO — {len(fallos)} vara(s) caídas: {fallos}")
    sys.exit(1)
print("PASS — sobre los 94 schemas reales, sólo la identidad byte a byte colapsa")
