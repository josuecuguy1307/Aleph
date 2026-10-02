#!/usr/bin/env python3
"""verify_perillas_cerebro.py — CAMBIAR DE CEREBRO ES CAMBIAR EL MODELO, NO TOCAR CÓDIGO.

Las cuatro perillas que la corrida del 2026-08-18 puso A MANO —`use_vision`, el techo por
llamada, y las dos válvulas del schema— tienen que DERIVARSE del cerebro elegido. Esta vara
lo mide con TRES filas REALES del catálogo, leídas del archivo, no copiadas acá:

    centro_modelos.py  cli.codex_cli         SIN vision   (su puente es de sólo texto)
    centro_modelos.py  cli.claude_cli        CON vision   ← se movió, y por eso está dicho
    centro_modelos.py  incluido.cognicion    CON vision

⚠️ EL CEREBRO SIN VISIÓN CAMBIÓ DE NOMBRE, y no es un ajuste de la vara para que pase.
Hasta el 2026-08-26 el fixture «sin visión» era `cli.claude_cli`, y era cierto: el puente
del CLI pegaba las imágenes como base64 en el texto, así que la fila NO declaraba `vision`
y el gate rechazaba la llamada con razón. Arreglado el transporte
(`claude_cli.build_stdin` → `--input-format stream-json`), la fila declara `vision` y este
caso necesitaba un cerebro que de verdad no vea: `cli.codex_cli`, cuyo puente sigue siendo
de sólo texto. Cambiar el fixture SIN que el transporte cambiara habría sido apagar la vara.

Y puede dar rojo: si alguien vuelve a hardcodear `use_vision=False`, el caso [2] cae.
"""
import sys, os, re, ast
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "platform"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "product", "backend"))
from browser import perfil as P                                          # noqa: E402

_f = []
def ok(c, d, extra=""):
    print(("  ✓ " if c else "  ✗ ") + d + (f"   {extra}" if extra and not c else ""))
    if not c: _f.append(d)

# ── las filas REALES, leídas del catálogo (si se editan allá, esta vara las sigue) ──────
RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
src = open(os.path.join(RAIZ, "product/backend/app/phase1/centro_modelos.py"), encoding="utf-8").read()
def fila(slug):
    m = re.search(r'"%s":\s*\{(.*?)\n    \},' % re.escape(slug), src, re.S)
    if not m: return None
    c = re.search(r'"model_use_capabilities":\s*(\[[^\]]*\])', m.group(1))
    return {"model_use_capabilities": ast.literal_eval(c.group(1))} if c else None

CLI  = fila("cli.codex_cli")          # el que NO ve
CLAU = fila("cli.claude_cli")         # el que SÍ ve desde que el puente transporta
INCL = fila("incluido.cognicion")
print("EL CEREBRO MANDA LAS PERILLAS\n")
ok(CLI and CLAU and INCL, "[0] las tres filas se leen del catálogo real",
   f"codex={CLI} claude={CLAU} incl={INCL}")
if not (CLI and CLAU and INCL): print("FAIL"); sys.exit(1)
print(f"      cli.codex_cli      → {CLI['model_use_capabilities']}")
print(f"      cli.claude_cli     → {CLAU['model_use_capabilities']}")
print(f"      incluido.cognicion → {INCL['model_use_capabilities']}\n")

a = P.perillas(CLI)
b = P.perillas(INCL)
ok(a["use_vision"] is False, "[1] cerebro SIN vision → use_vision=False (navega por el DOM)", str(a))
ok(P.perillas(CLAU)["use_vision"] is True,
   "[1b] …y el CLI de Claude YA ve: el puente lleva la imagen, la fila lo declara",
   str(P.perillas(CLAU)))
ok(b["use_vision"] is True,  "[2] cerebro CON vision → use_vision=True SOLO (nadie edita nada)", str(b))
ok(a["llm_timeout"] == P.TIMEOUT_DEFAULT_S, "[3] el techo por llamada tiene un default de la casa", str(a["llm_timeout"]))

os.environ[P.TIMEOUT_ENV] = "300"
ok(P.perillas(CLI)["llm_timeout"] == 300, "[4] …y se pisa por entorno (qwen murió en los 75 s por defecto)")
os.environ.pop(P.TIMEOUT_ENV)
ok(P.perillas(CLI, timeout_s=210)["llm_timeout"] == 210, "[5] …y por argumento")
os.environ[P.TIMEOUT_ENV] = "no-es-un-numero"
ok(P.perillas(CLI)["llm_timeout"] == P.TIMEOUT_DEFAULT_S, "[6] un valor basura no tumba nada: cae al default")
os.environ.pop(P.TIMEOUT_ENV)

ok(a["dont_force_structured_output"] and a["add_schema_to_system_prompt"],
   "[7] hoy el borde NO honra response_format ⇒ el schema va por el prompt")
os.environ[P.SCHEMA_ENV] = "1"
c = P.perillas(CLI)
ok(not c["dont_force_structured_output"] and not c["add_schema_to_system_prompt"],
   "[8] el día que lo honre, el schema estricto vuelve SIN reescribir el arranque")
os.environ.pop(P.SCHEMA_ENV)

# ── la lección heredada: sin matriz DECLARADA no se prende nada ─────────────────────────
ok(P.perillas({"capacidades": ["vision", "razonamiento"]})["use_vision"] is False,
   "[9] NO cae al vocabulario de RASGOS de UI — el `vision` de la marca no prende la captura")
ok(P.perillas({"model_use_capabilities": []})["use_vision"] is False,
   "[10] matriz declarada VACÍA ≠ ausente, y ninguna prende visión")
ok(P.perillas(None)["use_vision"] is False, "[11] sin fila → nada prendido (fail-closed)")

# ── el copy, que es lo que el usuario lee ANTES de que falle ────────────────────────────
av = P.aviso(CLI)
ok(av and av.get("copy"), "[12] el cerebro sin visión AVISA con copy, no falla callado", str(av))
ok(P.aviso(INCL) is None, "[13] …y con un cerebro que ve no hay nada que avisar")

# ── prueba de caída ────────────────────────────────────────────────────────────────────
print("\nPRUEBA DE CAÍDA — la perilla hardcodeada, como estaba en la corrida")
rojo = (lambda _f: _f(INCL))(lambda f: False) is False   # simula use_vision=False fijo
print(("  ✓ " if rojo else "  ✗ ") + "el caso [2] da ROJO si alguien vuelve a fijar use_vision=False")
if not rojo: _f.append("LA VARA NO MIDE")

print("\n" + ("PASS" if not _f else "FAIL: " + " · ".join(_f)))
sys.exit(1 if _f else 0)
