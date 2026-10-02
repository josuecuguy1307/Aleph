#!/usr/bin/env python3
"""verify_code_execution.py — la vara de code execution.

    python3 platform/assembler/verify_code_execution.py
    python3 platform/assembler/verify_code_execution.py --caer   # la prueba de caída

`--caer` MUTA la pieza a propósito (le saca el token al puente, le saca el aviso de
recorte, le saca los eventos) y exige que la vara se ponga ROJA. Una vara que no puede
dar rojo no mide nada.

CORRE CONTRA EL `_run_python` REAL de pysandbox: si el sandbox cambia, esto se entera.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RAIZ, "platform", "assembler"))
import code_execution as CE                                          # noqa: E402

_s = importlib.util.spec_from_file_location(
    "pysandbox_server", os.path.join(RAIZ, "product/belts/generalistas/pysandbox_server.py"))
_ps = importlib.util.module_from_spec(_s); _s.loader.exec_module(_ps)
CORRER = _ps._run_python

MUTAR = "--caer" in sys.argv
RES = []


def chk(nombre, cond, detalle=""):
    RES.append((nombre, bool(cond)))
    print(f"  [{'VERDE' if cond else 'ROJO '}] {nombre}" + (f"  · {detalle}" if detalle else ""))


# ── el belt de juguete ────────────────────────────────────────────────────────
TOOLS = [
    {"type": "function", "function": {"name": "get_precio", "description": "precio de un símbolo",
     "parameters": {"type": "object", "properties": {"sym": {"type": "string"}}, "required": ["sym"]}}},
    {"type": "function", "function": {"name": "get_historia", "description": "serie histórica",
     "parameters": {"type": "object", "properties": {"sym": {"type": "string"},
                    "dias": {"type": "integer"}}, "required": ["sym"]}}},
    {"type": "function", "function": {"name": "explota", "description": "siempre falla",
     "parameters": {"type": "object", "properties": {}}}},
    # un nombre que NO es identificador de Python: no puede ser función
    {"type": "function", "function": {"name": "servidor__tool-rara", "description": "nombre raro",
     "parameters": {"type": "object", "properties": {}}}},
]

VISTAS = []
def despachar(nombre, args):
    VISTAS.append((nombre, args))
    if nombre == "explota":
        raise ValueError("el proveedor dijo que no")
    if nombre == "get_precio":
        return json.dumps({"sym": args.get("sym"), "precio": 191.5})
    if nombre == "get_historia":
        return json.dumps({"sym": args.get("sym"),
                           "serie": [{"d": i, "c": 100 + i} for i in range(args.get("dias", 3))]})
    return "?"

EVENTOS = []
def on_event(ev, datos): EVENTOS.append((ev, datos))

# ── las mutaciones ────────────────────────────────────────────────────────────
if MUTAR:
    print("!! MODO --caer: la pieza va MUTADA, la vara TIENE que ponerse roja\n")
    CE._PRELUDIO_BASE = CE._PRELUDIO_BASE.replace('"X-Aleph-Codemode": _ALEPH_TOKEN', '"X-Aleph-Codemode": "x"')
    # La mutación tiene que apuntar al mecanismo QUE GOBIERNA HOY: el recorte ya no se
    # detecta por un límite propio sino por la marca de fin del preludio. Sacarle la
    # marca es lo que devuelve el verde mudo original.
    CE._PRELUDIO_BASE = CE._PRELUDIO_BASE.replace("_atexit.register", "_noop = lambda *a: None; _noop")
    _orig = CE.Puente._avisar
    CE.Puente._avisar = lambda self, e, d: None   # el turno se queda MUDO

print("── A · el camino entero: un script que encadena DOS tools ──")
r = CE.ejecutar(
    "p = get_precio(sym='AAPL')\n"
    "h = get_historia(sym='AAPL', dias=200)\n"
    "print('precio', p['precio'], 'cierres', len(h['serie']), 'ult', h['serie'][-1]['c'])\n",
    TOOLS, despachar, on_event=on_event)
chk("A1: el script corrió sin error", r["ok"], (r["stderr"] or "").strip().splitlines()[-1][:140] if r["stderr"] else "")
chk("A2: las DOS tools se ejecutaron de verdad", r["n_tools_corridas"] == 2, f"corridas={r['n_tools_corridas']} vistas={[v[0] for v in VISTAS]}")
chk("A3: sólo vuelve lo impreso, no las 200 filas", "cierres 200" in r["stdout"] and '"serie"' not in r["stdout"],
    repr(r["stdout"].strip())[:120])

print("\n── B · LAS SEÑALES NO DEJAN DE DECIRSE ──")
inicios = [d["tool"] for e, d in EVENTOS if e == "tool_started"]
finales = [d["tool"] for e, d in EVENTOS if e == "tool_finished"]
chk("B1: cada tool corrida emitió su tool_started", sorted(inicios) == ["get_historia", "get_precio"], f"{inicios}")
chk("B2: cada tool corrida emitió su tool_finished", sorted(finales) == ["get_historia", "get_precio"], f"{finales}")
_vias = [d.get("via") for e, d in EVENTOS if e == "tool_started"]
# `all([])` es True: sin esta comprobación de presencia, B3 quedaba VACUAMENTE VERDE
# cuando la mutación borraba los eventos. La ausencia de señal no es una medición.
chk("B3: el evento dice que fue por code execution",
    len(_vias) == 2 and all(v == "code_execution" for v in _vias), f"vias={_vias}")

print("\n── C · una tool que falla LLEGA CON SU MOTIVO ──")
r2 = CE.ejecutar(
    "try:\n"
    "    explota()\n"
    "except AlephToolError as e:\n"
    "    print('CAUSA:', e)\n",
    TOOLS, despachar)
chk("C1: el script pudo atajar el fallo", r2["ok"], (r2["stderr"] or "")[:120])
chk("C2: el motivo REAL viaja hasta el script", "el proveedor dijo que no" in r2["stdout"], repr(r2["stdout"].strip())[:140])

print("\n── D · el puente no atiende sin token ──")
_llam = []
with CE.Puente(lambda n, a: _llam.append(n) or "ok", {"get_precio"}) as p:
    req = urllib.request.Request(f"http://127.0.0.1:{p.puerto}/tool",
                                 data=b'{"tool":"get_precio","args":{}}', method="POST",
                                 headers={"X-Aleph-Codemode": "token-equivocado"})
    try:
        urllib.request.urlopen(req, timeout=5); codigo = 200
    except urllib.error.HTTPError as e:
        codigo = e.code
chk("D1: un golpe sin el token da 403 y NO ejecuta", codigo == 403 and not _llam, f"codigo={codigo} ejecutadas={_llam}")

print("\n── E · una tool fuera del belt no corre aunque el script la nombre ──")
r3 = CE.ejecutar("print(_aleph_llamar('borrar_todo'))", TOOLS, despachar)
chk("E1: la tool ajena se rechaza con copy", "no disponible en este run" in (r3["stdout"] + r3["stderr"]),
    (r3["stderr"] or r3["stdout"]).strip().splitlines()[-1][:120])

print("\n── F · EL RECORTE SE DECLARA ──")
r4 = CE.ejecutar("print('x'*60000)", TOOLS, despachar)
chk("F1: una salida enorme se marca como recortada", r4["recortada"] is True, f"recortada={r4['recortada']} len={len(r4['stdout'])}")
chk("F2: y lo DICE en el texto que lee el modelo", "RECORTADO" in r4["stdout"], repr(r4["stdout"][-90:]))

r5 = CE.ejecutar("print('corto')", TOOLS, despachar)
chk("F3: sin recorte, la marca NO se le muestra al modelo",
    "__ALEPH_FIN__" not in r5["stdout"] and r5["stdout"].strip() == "corto", repr(r5["stdout"]))
chk("F4: y el total impreso se DECLARA con su número", r5["total_impreso"] == 6, f"total={r5['total_impreso']}")
chk("F5: con recorte el total es None, no 0", r4["total_impreso"] is None, f"total={r4['total_impreso']!r}")

print("\n── G · el nombre que no es identificador queda afuera de LAS DOS caras ──")
utiles = CE.funciones_validas(TOOLS)
chk("G1: se descarta de las funciones", len(utiles) == 3, f"{[t['function']['name'] for t in utiles]}")
chk("G2: y NO aparece en la superficie que ve el modelo", "servidor__tool-rara" not in CE.superficie(utiles))

print("\n── I · EL GATE SIGUE MANDANDO ADENTRO DEL SCRIPT ──")
# Lo único que no se puede aflojar: si un script pudiera llamar una tool de dinero/envío
# salteándose la barrera que el camino normal aplica tool por tool, code execution sería
# un agujero, no una optimización.
sys.path.insert(0, os.path.join(RAIZ, "platform", "gates"))
import recipe_assembler as RA                                        # noqa: E402
from approval_gate import GateDecision                               # noqa: E402

class _RegistroFalso:
    def server_for(self, n): return "srv"
    def raw_for(self, n): return n
    def call(self, n, a): CORRIDAS.append(n); return despachar(n, a)

class _GateFalso:
    """Deja pasar `get_precio` y RETIENE `explota` con su copy."""
    def evaluate(self, srv, tool, args):
        if tool == "explota":
            return GateDecision(GateDecision.NEEDS_OK, "confirma-siempre",
                                {"leyenda": "esto mueve plata: confirmá vos"})
        return GateDecision(GateDecision.EXECUTE, "auto-ejecuta")

CORRIDAS = []
salida = RA._correr_codemode(
    {"code": "print(get_precio(sym='AAPL')['precio'])\n"
             "try:\n    explota()\nexcept AlephToolError as e:\n    print('RETENIDA:', e)\n"},
    CE.funciones_validas(TOOLS), _RegistroFalso(), _GateFalso(), None)
chk("I1: la tool permitida SÍ corrió", "191.5" in salida, repr(salida.strip())[:100])
chk("I2: la tool retenida por el gate NO se ejecutó", "explota" not in CORRIDAS, f"corridas={CORRIDAS}")
chk("I3: y al script le llega LA COPY del gate, no un código pelado",
    "esto mueve plata: confirmá vos" in salida, repr(salida.strip())[-120:])

print("\n── H · LA REGLA DE ACTIVACIÓN · cruces, no tamaño de catálogo ──")
# Medido en turnos reales: Ciencia entra con 25 tools (5 cruces) y la Sala queda afuera
# con 30 (2 cruces). El catálogo no los separa; las llamadas encadenadas sí.
chk("H1: turno recién empezado (0 llamadas) → NO enciende",
    CE.conviene(TOOLS * 7, llamadas_hechas=0) is False)
chk("H2: 1 llamada → todavía NO (Educación cruza 1 vez y nunca prende)",
    CE.conviene(TOOLS * 7, llamadas_hechas=1) is False)
chk("H3: 2 llamadas → NO (Oficina cruza 3 y con umbral 2 queda 43% PEOR)",
    CE.conviene(TOOLS * 7, llamadas_hechas=2) is False)
chk("H3b: 3 llamadas → SÍ enciende", CE.conviene(TOOLS * 7, llamadas_hechas=3) is True)
chk("H4: el MISMO catálogo con 0 llamadas sigue en NO — lo que decide no es el catálogo",
    CE.conviene(TOOLS * 7, llamadas_hechas=0) is False
    and CE.conviene(TOOLS * 7, llamadas_hechas=3) is True)
chk("H5: un catálogo de UNA tool no entra ni encadenando",
    CE.conviene(TOOLS[:1], llamadas_hechas=9) is False)
chk("H6: el umbral es 3 — el conservador, hasta que 1.b mida las cruces post-cambio",
    CE.UMBRAL_LLAMADAS == 3)



# ══ EL POSICIONAL NO MATA EL SCRIPT ═══════════════════════════════════════════════
# Añadido 2026-08-23 tras medirlo cayendo en Diseño: los stubs eran `def f(**kw)` y un
# `set_title("Landing")` —Python razonable, y lo que el modelo escribe si le mostrás una
# firma— tiraba `TypeError: takes 0 positional arguments` en la PRIMERA línea del script.
# Muere el script entero: `tools_corridas: []`, cero llamadas por el puente, y el turno
# «anduvo» igual por el camino de cierre. Verde mudo puro.
print("\n── POSICIONALES (el defecto medido en Diseño) ─────────────────────────")

_TOOLS_POS = [
    {"type": "function", "function": {
        "name": "set_title", "description": "pone el título",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}},
                       "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "editar", "description": "edita",
        "parameters": {"type": "object",
                       "properties": {"command": {"type": "string"},
                                      "path": {"type": "string"}},
                       "required": ["command", "path"]}}},
]

_VISTAS = []


def _despachar_pos(nombre, args):
    _VISTAS.append((nombre, args))
    return json.dumps({"ok": True, "vi": args})


_r = CE.ejecutar('set_title("Landing")\nprint("T", editar("view", "A.txt"))',
              _TOOLS_POS, _despachar_pos)
chk("P1 · un posicional se mapea al nombre que el schema declara",
    ("set_title", {"title": "Landing"}) in _VISTAS, str(_VISTAS))
chk("P2 · varios posicionales, en el orden del schema",
    ("editar", {"command": "view", "path": "A.txt"}) in _VISTAS, str(_VISTAS))
chk("P3 · y el script llega hasta el final (no muere en la línea 1)",
    bool(_r.get("ok")) and "T" in (_r.get("stdout") or ""),
    (_r.get("stderr") or "")[:120])

_VISTAS.clear()
_r2 = CE.ejecutar('editar("view", path="B.txt")\nprint("MIX")', _TOOLS_POS, _despachar_pos)
chk("P4 · posicional + keyword mezclados",
    ("editar", {"command": "view", "path": "B.txt"}) in _VISTAS, str(_VISTAS))

_VISTAS.clear()
_r3 = CE.ejecutar('try:\n    editar("view", "A", "de", "mas")\nexcept AlephToolError as e:\n'
               '    print("CAZADO", e)', _TOOLS_POS, _despachar_pos)
chk("P5 · de más NO se manda al stack: levanta AlephToolError con el motivo",
    "CAZADO" in (_r3.get("stdout") or "") and not _VISTAS,
    (_r3.get("stdout") or "")[:110])

_VISTAS.clear()
_r4 = CE.ejecutar('try:\n    editar("view", command="otro")\nexcept AlephToolError as e:\n'
               '    print("DOBLE", e)', _TOOLS_POS, _despachar_pos)
chk("P6 · el mismo parámetro dos veces se caza, no se pisa en silencio",
    "DOBLE" in (_r4.get("stdout") or "") and not _VISTAS,
    (_r4.get("stdout") or "")[:110])



# ══ LA FORMA DE ADENTRO NO SE PIERDE ══════════════════════════════════════════════
# Medido dos veces en Diseño el 2026-08-23: `set_todos` declara
# `items: array<{text, checked}>` y la superficie lo aplanaba a `items: object[]`. El
# modelo inventó `{title, status}`, el stack lo rechazó, y como sus tools están ORDENADAS
# se cayó todo lo de después: `App.jsx` nunca existió. El catálogo NO tiene el problema
# —lleva el JSON Schema entero—, así que la superficie perdía lo que el camino normal sí
# entrega. Costó 32 tokens arreglarlo, sobre una superficie que viaja UNA vez por turno.
print("\n── LA FORMA DE ADENTRO (el defecto medido en Diseño) ──────────────────")

_ANIDADO = [{"type": "function", "function": {
    "name": "set_todos", "description": "la lista",
    "parameters": {"type": "object", "required": ["items"], "properties": {
        "items": {"type": "array", "items": {
            "type": "object", "required": ["text", "checked"],
            "properties": {"text": {"type": "string"},
                           "checked": {"type": "boolean"}}}}}}}}]

_sup = CE.superficie(_ANIDADO)
chk("N1 · un array de objetos muestra la forma de sus ítems, no `object[]`",
    "items: {text: string, checked: boolean}[]" in _sup,
    [l.strip() for l in _sup.splitlines() if "set_todos" in l][:1])
chk("N2 · y ya NO dice `object[]`", "object[]" not in _sup)

_OBJ = [{"type": "function", "function": {
    "name": "cfg", "description": "config",
    "parameters": {"type": "object", "properties": {
        "opts": {"type": "object", "required": ["a"],
                 "properties": {"a": {"type": "string"}, "b": {"type": "number"}}}}}}}]
chk("N3 · un objeto suelto también, con su `?` para lo opcional",
    "opts?: {a: string, b?: number}" in CE.superficie(_OBJ),
    [l.strip() for l in CE.superficie(_OBJ).splitlines() if "cfg(" in l][:1])

_ANCHO = [{"type": "function", "function": {
    "name": "ancho", "description": "muchas claves",
    "parameters": {"type": "object", "properties": {
        "o": {"type": "object", "properties": {f"k{i}": {"type": "string"}
                                               for i in range(12)}}}}}}]
chk("N4 · un objeto muy ancho se corta con «…» — la superficie no puede crecer sin techo",
    "…}" in CE.superficie(_ANCHO) and CE.superficie(_ANCHO).count("k") <= 12,
    [l.strip() for l in CE.superficie(_ANCHO).splitlines() if "ancho(" in l][:1])

_HONDO = [{"type": "function", "function": {
    "name": "hondo", "description": "profundo",
    "parameters": {"type": "object", "properties": {
        "a": {"type": "object", "properties": {
            "b": {"type": "object", "properties": {"c": {"type": "string"}}}}}}}}}]
chk("N5 · se expande UN nivel, no el árbol entero",
    "b?: object" in CE.superficie(_HONDO),
    [l.strip() for l in CE.superficie(_HONDO).splitlines() if "hondo(" in l][:1])

print("\n" + "=" * 64)
v = sum(1 for _, o in RES if o)
print(f"VERDES {v} / {len(RES)}")
rojas = [n for n, o in RES if not o]
for n in rojas: print(f"  ROJO · {n}")
if MUTAR:
    ok = len(rojas) > 0
    print(f"\nPRUEBA DE CAÍDA: {'la vara SE PUSO ROJA con la pieza mutada — mide' if ok else 'la vara siguió VERDE con la pieza rota — NO MIDE NADA'}")
    sys.exit(0 if ok else 1)
sys.exit(0 if not rojas else 1)
