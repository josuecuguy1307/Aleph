#!/usr/bin/env python3
"""verify_vocabulario_cableado.py — LA VARA DE LA OBRA 2.3.

[Gate 4 · Fase 2 · obra 2.3 — ~/Desktop/FASE2-CONTRATO-ARTEFACTOS.md §2, deuda D2]

QUÉ MIDE. El censo §C.3 encontró CUATRO listas de tipos de artefacto que no se
hablaban entre sí (11 · 16 · 7 · 10) y un almacén que aceptaba cualquier string.
2.2 escribió EL vocabulario y le cableó dos consumidores (borde de escritura y
export), dejando `producible_by_llm` y `rich_capture` marcados ADVISORY. 2.3
cablea los cuatro que faltaban. Esta vara mide que estén cableados DE VERDAD:

  V1 · la fuente: ya no queda ningún campo advisory, y el mapa del clasificador
       no puede apuntar fuera de lo que el modelo puede producir.
  V2 · consumidor 1/4 · el clasificador (`stream_chat`): el conjunto Y el menú del
       prompt salen del vocabulario; `_coerce_type` conserva, caso por caso, lo
       que la tabla vieja hacía.
  V3 · consumidor 4/4 · el executor: qué tipos se barren del workdir sale de
       `rich_capture`; la forma sigue siendo del executor; la prioridad también.
  V4 · consumidores 2/4 y 3/4 · los dos registros de render: se IMPORTAN en node
       (sonda_vocabulario.mjs) y se les pregunta a qué despachan. Cobertura del
       canónico completa en los dos, cero llaves fuera de la unión, y los alias
       resolviendo IGUAL de los dos lados — que es justo lo que no pasaba.
  V5 · el espejo JS no driftea de su fuente (el generador, en modo --check).
  V6 · GOBIERNA, no espeja: se agrega un tipo al vocabulario en caliente y los
       cuatro consumidores lo siguen sin tocar una línea de ellos.
  V7 · anti-regresión: los literales que murieron no vuelven a aparecer.

NO mide píxeles: eso es la vara de navegador contra la `.app` instalada.

    product/backend/.venv/bin/python qa/verify_vocabulario_cableado.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent
for _p in (str(_AQUI / "lib"), str(_RAIZ / "product" / "backend"), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deps_node as DN            # noqa: E402
import veredicto as V             # noqa: E402

os.environ.setdefault("PUPPET_MOTOR_PERSISTE", "0")

from artifacts import vocabulary as vocab            # noqa: E402
from app.phase1 import stream_chat as sc             # noqa: E402
from app.phase1 import executor as ex                # noqa: E402

_fallos = 0
_salteados = 0
_criticos = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))
    return bool(cond)


def saltear(nombre, motivo, critico=False):
    global _salteados, _criticos
    _salteados += 1
    if critico:
        _criticos += 1
    print(f"  ~ SALTEADO {nombre}  —  {motivo}" + ("   [DE SU OBJETO]" if critico else ""))


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


print("=" * 80)
print("VARA · EL VOCABULARIO CABLEADO EN LOS CUATRO CONSUMIDORES (Gate 4 · 2.3)")
print("=" * 80)

# ══════════════════════════════════════════════════════════════════════════════
seccion("V1 · la fuente: nada quedó advisory, y el mapa del clasificador cierra")

ok(vocab.ADVISORY_FIELDS == (),
   "ADVISORY_FIELDS vacío — los tres campos que faltaban tienen consumidor",
   repr(vocab.ADVISORY_FIELDS))
#: El número es un TESTIGO, no una preferencia: si cambia, alguien tocó la unión y tiene
#: que decir por qué acá. Pasó de 16 a 17 con `presentacion`
#: [Convergencia · superficie 7]: Oficina clasifica `.pptx` como `presentation` y ningún
#: tipo declaraba el formato `pptx`, así que un deck no tenía sustantivo en la casa.
ok(len(vocab.CANONICAL) == 17, "17 tipos canónicos (la unión del contrato)", str(len(vocab.CANONICAL)))
ok(not (set(vocab.ALIASES) & set(vocab.CANONICAL)), "ningún alias tapa un canónico")
ok(set(vocab.ALIASES.values()) <= set(vocab.CANONICAL), "todo alias aterriza en la unión")
ok(not (set(vocab.LLM_ALIASES) & set(vocab.CANONICAL)),
   "ninguna palabra coloquial del modelo tapa un canónico")
ok(all(vocab.TYPES[v]["producible_by_llm"] for v in vocab.LLM_ALIASES.values()),
   "toda palabra coloquial apunta a un tipo que el modelo PUEDE producir")
ok(vocab.producible_by_llm()[0] == "informe",
   "el menú abre con `informe` — el desempate declarado del prompt («ante la duda»)")
ok(vocab.normalize("BANANA") is None and vocab.normalize("  DoC ") == "documento",
   "normalize: veredicto None fuera de la unión, alias resuelto adentro")

# ══════════════════════════════════════════════════════════════════════════════
seccion("V2 · consumidor 1/4 · el clasificador (stream_chat)")

ok(tuple(sc._ARTIFACT_TYPES) == tuple(vocab.producible_by_llm()),
   "_ARTIFACT_TYPES ES producible_by_llm() (misma tupla, mismo orden)",
   f"{sc._ARTIFACT_TYPES} vs {vocab.producible_by_llm()}")

_menu = [l.strip() for l in sc._ARTIFACT_ACTION_SYS.splitlines() if l.strip().startswith("·")]
_en_menu = [l.split('"')[1] for l in _menu if '"' in l]
ok(_en_menu == list(vocab.producible_by_llm()),
   "el MENÚ del prompt tiene exactamente los tipos producibles, en su orden",
   f"{_en_menu}")
ok(not (set(_en_menu) - set(vocab.CANONICAL)),
   "ningún tipo del menú está fuera de la unión canónica")

#: LA TABLA VIEJA, caso por caso (stream_chat._coerce_type antes de 2.3). Es el
#: testigo: cablear no puede cambiar lo que el clasificador decidía.
_TABLA_VIEJA = {
    "3d": "3d", "three": "3d", "threejs": "3d", "three.js": "3d", "escena": "3d",
    "modelo3d": "3d",
    "grafico": "dashboard", "gráfico": "dashboard", "graficos": "dashboard",
    "charts": "dashboard", "chart": "dashboard", "viz": "dashboard",
    "visualizacion": "dashboard", "visualización": "dashboard",
    "tabla": "planilla", "hoja": "planilla", "spreadsheet": "planilla",
    "excel": "planilla", "presupuesto": "planilla",
    "pagina": "web", "página": "web", "sitio": "web", "site": "web",
    "html": "web", "landing": "web", "webpage": "web",
    "carta": "documento", "memo": "documento", "correo": "documento",
    "email": "documento", "contrato": "documento", "doc": "documento",
    "imagen": "imagen", "image": "imagen", "ilustracion": "imagen",
    "ilustración": "imagen", "foto": "imagen",
    # y el resto: lo que no estaba en los 7 caía a informe
    "informe": "informe", "documento": "documento", "planilla": "planilla",
    "web": "web", "dashboard": "dashboard",
    "cad": "informe", "dicom": "informe", "linechart": "informe",
    "banana": "informe", "": "informe", None: "informe", "  DASHBOARD ": "dashboard",
}
_dif = {k: (v, sc._coerce_type(k)) for k, v in _TABLA_VIEJA.items() if sc._coerce_type(k) != v}
ok(not _dif, f"_coerce_type: los {len(_TABLA_VIEJA)} casos de la tabla vieja dan IGUAL",
   json.dumps(_dif, ensure_ascii=False))

_src_sc = (_RAIZ / "product/backend/app/phase1/stream_chat.py").read_text(encoding="utf-8")
ok('("informe", "documento", "planilla", "web", "dashboard", "3d", "imagen")' not in _src_sc,
   "la lista literal de 7 tipos ya no existe en el archivo")

# ══════════════════════════════════════════════════════════════════════════════
seccion("V3 · consumidor 4/4 · el executor (captura rica)")

_orden = ex._rich_scan_order()
ok(set(_orden) == set(vocab.rich_capture_types()),
   "los tipos barridos SON los de rich_capture", f"{sorted(set(_orden) ^ set(vocab.rich_capture_types()))}")
ok(len(_orden) == len(set(_orden)), "ningún tipo se barre dos veces")
ok(_orden[0] == "convergence",
   "la prioridad declarada manda: el loop entero gana al cuadro suelto")
ok(all(t in ex._RICH_VALIDATORS for t in _orden),
   "todo tipo barrido tiene validador de forma",
   str([t for t in _orden if t not in ex._RICH_VALIDATORS]))

with tempfile.TemporaryDirectory() as _d:
    _w = Path(_d)
    (_w / "sub").mkdir()
    (_w / "sub" / "bom.planilla.json").write_text(json.dumps({"type": "planilla", "rows": [[1, 2]]}))
    ok((ex._capture_rich_obra(str(_w)) or {}).get("type") == "planilla",
       "captura una planilla real escrita en una subcarpeta del workdir")
    (_w / "x.fieldplot.json").write_text(json.dumps(
        {"type": "fieldplot", "grid": {"nx": 2, "ny": 2, "values": [1, 2, 3, 4]}}))
    ok((ex._capture_rich_obra(str(_w)) or {}).get("type") == "fieldplot",
       "la prioridad se respeta (fieldplot gana a planilla)")
    (_w / "convergence.json").write_text(json.dumps({"type": "convergence", "iterations": [{"n": 1}]}))
    ok((ex._capture_rich_obra(str(_w)) or {}).get("type") == "convergence",
       "convergence.json (nombre fijo, en la raíz) gana a todo")

with tempfile.TemporaryDirectory() as _d:
    _w = Path(_d)
    (_w / "y.cad.json").write_text(json.dumps({"type": "cad", "content": "   "}))
    (_w / "z.dicom.json").write_text(json.dumps({"type": "imagen", "image": "data:x"}))
    (_w / "w.schematic.json").write_text("{roto")
    ok(ex._capture_rich_obra(str(_w)) is None,
       "fail-closed: forma vacía, `type` mentido y JSON roto no producen obra")

# ══════════════════════════════════════════════════════════════════════════════
seccion("V4 · consumidores 2/4 y 3/4 · los DOS registros de render (medidos, no leídos)")

_listo, _motivo = DN.asegurar_node_modules(_RAIZ)
_sonda = None
try:
    _r = subprocess.run(["node", str(_AQUI / "lib" / "sonda_vocabulario.mjs"), str(_RAIZ)],
                        cwd=_RAIZ, capture_output=True, text=True, timeout=60)
    if _r.returncode == 0:
        _sonda = json.loads(_r.stdout)
    else:
        saltear("V4", f"la sonda de node no corrió: {(_r.stderr or '').strip()[:300]}", critico=True)
except Exception as e:                                   # node ausente / import roto
    saltear("V4", f"node no pudo importar los registros: {e}", critico=True)

if _sonda:
    _a, _s = _sonda["aleph"], _sonda["sala"]
    ok(_a["uncovered"] == [], "AlephRender: ningún canónico sin renderer ni delegación declarada",
       str(_a["uncovered"]))
    ok(_a["outside"] == [], "AlephRender: ninguna llave fuera de la unión", str(_a["outside"]))
    ok(_s["uncovered"] == [], "SalaRender: ningún canónico sin renderer ni delegación declarada",
       str(_s["uncovered"]))
    ok(_s["outside"] == [], "SalaRender: ninguna llave fuera de la unión (murió `diagrama`)",
       str(_s["outside"]))
    ok(sorted(_sonda["vocabulary"]["canonical"]) == sorted(vocab.CANONICAL),
       "el navegador ve LA MISMA unión que el backend")
    ok(_sonda["vocabulary"]["aliases"] == dict(vocab.ALIASES),
       "…y el MISMO mapa de alias")

    # el drift que la obra vino a matar: `doc` canónico de un lado, `documento` del otro
    _d = _sonda["dispatch"]
    ok(_d["doc"]["aleph"] == "documento" and _d["doc"]["sala"] == "documento",
       "`doc` (alias) aterriza en el renderer `documento` en LOS DOS registros",
       json.dumps(_d["doc"]))
    _desacuerdos = {}
    for _t, _v in _d.items():
        _ca = vocab.normalize(_t)
        if _ca is None:
            continue
        _esp_a = _a["delegates"].get(_ca, _ca)
        if _ca in _a["notCovered"]:
            _esp_a = "informe"                            # declarado: lo dibuja la Sala
        _esp_s = _s["delegates"].get(_ca, _ca)
        if (_v["aleph"], _v["sala"]) != (_esp_a, _esp_s):
            _desacuerdos[_t] = {"medido": _v, "esperado": {"aleph": _esp_a, "sala": _esp_s}}
    ok(not _desacuerdos,
       f"los {len(_d)} nombres (canónicos + alias) despachan a lo declarado en los dos registros",
       json.dumps(_desacuerdos, ensure_ascii=False)[:400])

    ok(_sonda["vocabulary"]["rich"] == list(vocab.rich_capture_types()),
       "el navegador ve el MISMO conjunto de captura rica que el executor")

# RICH_SHAPES vive en el RENDERER (`render/sala-render.js`), al lado de los renderers que
# consumen esas formas. [Convergencia · superficie 7 · paso 2] Antes vivía adentro de
# `sala/sala.html` y esta vara tenía que parsear una página entera con un `split()` para
# auditar una tabla de 11 líneas — y la Sala v2, que usa el MISMO renderer, se quedaba sin
# validación de obra rica porque el código estaba del otro lado.
_sala_render = (_RAIZ / "product/app/design/render/sala-render.js").read_text(encoding="utf-8")
_bloque = _sala_render.split("var RICH_SHAPES = {", 1)[-1].split("};", 1)[0]
_llaves = sorted({l.split(":")[0].strip() for l in _bloque.splitlines()
                  if ":" in l and not l.strip().startswith("//")})
ok(_llaves == sorted(vocab.rich_capture_types()),
   "RICH_SHAPES tiene una forma por cada tipo de captura rica, ni una de más",
   f"{_llaves} vs {sorted(vocab.rich_capture_types())}")

# ══════════════════════════════════════════════════════════════════════════════
seccion("V5 · el espejo JS no driftea de su fuente")

_gen = subprocess.run([sys.executable, str(_RAIZ / "platform/artifacts/gen_vocabulary_js.py"), "--check"],
                      cwd=_RAIZ, capture_output=True, text=True, timeout=60)
ok(_gen.returncode == 0, "gen_vocabulary_js.py --check: el archivo generado coincide",
   (_gen.stderr or _gen.stdout).strip()[:300])

if _sonda:
    ok(_sonda["vocabulary"]["schema_version"] == vocab.SCHEMA_VERSION,
       "misma schema_version a los dos lados")
    ok(_sonda["vocabulary"]["producible"] == list(vocab.producible_by_llm()),
       "…y el mismo subconjunto producible por el modelo")

# ══════════════════════════════════════════════════════════════════════════════
seccion("V6 · GOBIERNA, no espeja: un tipo nuevo y los cuatro lo siguen solos")

_orig_types = dict(vocab.TYPES)
try:
    vocab.TYPES["pizarra"] = {"formats": ["md"], "producible_by_llm": True,
                              "rich_capture": True, "label_es": "pizarra"}
    # 1) el clasificador lo ofrece, con su label_es de respaldo (no hay glosa escrita)
    _tipos = sc._producible_types()
    _menu2 = sc._type_menu(_tipos)
    ok("pizarra" in _tipos and '· "pizarra": pizarra.' in _menu2,
       "el clasificador ofrece el tipo nuevo usando `label_es` — nada se cae por falta de prosa",
       _menu2.splitlines()[-1] if _menu2 else "")
    # 2) _coerce_type lo acepta sin tocar stream_chat
    ok(sc._coerce_type("pizarra") == "pizarra", "…y `_coerce_type` lo acepta")
    # 3) el executor lo barre (al final, tras la prioridad declarada) y avisa que no
    #    sabe validar su forma en vez de tragárselo mudo
    _o2 = ex._rich_scan_order()
    ok(_o2[-1] == "pizarra" and _o2[0] == "convergence",
       "el executor lo barre al final, sin romper la prioridad declarada", str(_o2))
    with tempfile.TemporaryDirectory() as _d:
        (Path(_d) / "a.pizarra.json").write_text(json.dumps({"type": "pizarra", "x": 1}))
        ok(ex._capture_rich_obra(str(_d)) is None,
           "…y NO lo captura: sin validador de forma no se adivina (queda dicho en stderr)")
    # 4) el espejo JS lo lleva al navegador
    sys.path.insert(0, str(_RAIZ / "platform" / "artifacts"))
    import gen_vocabulary_js as GEN                      # noqa: E402
    ok('"pizarra"' in GEN.build(), "el espejo JS regenerado lo lleva a los dos registros")
finally:
    vocab.TYPES.clear()
    vocab.TYPES.update(_orig_types)

ok(sc._coerce_type("pizarra") == "informe", "restaurado: el tipo de prueba ya no existe")

# ══════════════════════════════════════════════════════════════════════════════
seccion("V7 · anti-regresión: los literales que murieron no vuelven")

_src_ar = (_RAIZ / "product/app/design/render/render.js").read_text(encoding="utf-8")
ok("const TYPES = Object.keys(RENDERERS)" in _src_ar,
   "render.js: TYPES se deriva de los renderers, no se declara")
ok("const ALIAS = {" not in _src_ar, "render.js: la tabla local de alias no volvió")
ok('import * as VOCAB from "./vocabulary.js"' in _src_ar, "render.js importa EL vocabulario")

_src_sr = (_RAIZ / "product/app/design/render/sala-render.js").read_text(encoding="utf-8")
ok("window.AlephVocabulary" in _src_sr, "render/sala-render.js consume EL vocabulario")
ok("\n    diagrama: function" not in _src_sr, "render/sala-render.js: la llave `diagrama` no volvió")

_src_ex = (_RAIZ / "product/backend/app/phase1/executor.py").read_text(encoding="utf-8")
ok('rglob("*.fieldplot.json")' not in _src_ex,
   "executor.py: la cascada de sufijos a mano no volvió")

print("\n     [invocación única del chequeo completo]  "
      "product/backend/.venv/bin/python qa/correr_varas.py")
sys.exit(V.cerrar(_fallos, _salteados, _criticos))
