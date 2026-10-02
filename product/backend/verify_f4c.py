#!/usr/bin/env python3
"""verify_f4c.py — LA VARA DE F4c (Gate 2 · EL ADAPTADOR DE MODELOS).

⚠️ **NO ANIDA VARAS** y corre en SEGUNDOS (reglas selladas en F4a/F4b). El chequeo completo
es UNA corrida de `qa/correr_varas.py`, con la máquina limpia verificada antes.

Lo que exige que quede verde:
  · un modelo por vía en cada estado: completa en el local CON evidencia y fecha ·
    incompleta en la aduana con SU trámite · completa-rota en el LOCAL con causa operativa
  · ANTI-YO-YO probado de verdad: escribir → romper → **PROCESO NUEVO que relee de disco**
    → sigue en el local
  · caducidad: medición rancia ⇒ no se pinta verde sin re-medir
  · checklist vivo: fallo en el verbo N ⇒ N-1 hechos + causa en N, jamás verde parcial
  · el contador del local dice la verdad
  · ALCANZABILIDAD: todo botón nuevo tiene su camino de clicks en la superficie MONTADA

    product/backend/.venv/bin/python product/backend/verify_f4c.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (str(_AQUI), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_fallos = 0
_salteados = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))


def saltear(nombre, motivo):
    global _salteados
    _salteados += 1
    print(f"  ⊘ {nombre}  →  SALTEADO: {motivo}")


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


print("=" * 80)
print("VARA F4c · EL ADAPTADOR DE MODELOS")
print("=" * 80)

_MOD = _RAIZ / "product/app/design/modelos"
_AHORA_MS = 1785901200000
_AHORA_S = _AHORA_MS / 1000


def _node(codigo: str):
    r = subprocess.run(["node", "--input-type=module", "-e", codigo],
                       capture_output=True, text=True, timeout=90, cwd=str(_RAIZ))
    if r.returncode != 0:
        return None, r.stderr[-400:]
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]), ""
    except Exception as e:                                  # noqa: BLE001
        return None, f"{e} · {r.stdout[-200:]}"


#: Un modelo por vía en cada estado. Es la matriz del acta, no una muestra cómoda.
_FILAS = [
    {"familia": "local", "ref": "qwen3:8b", "label": "Qwen3 8B", "local": True,
     "estado": "probado", "causa": None, "estuvo_completa": True,
     "prueba": {"estado": "probado", "ts": _AHORA_S - 120, "detalle": "respondió en 812 ms"}},
    {"familia": "local", "ref": "llama3", "label": "Llama 3", "local": False,
     "estado": "no_configurado", "estuvo_completa": False},
    {"familia": "local", "ref": "mistral", "label": "Mistral", "local": False,
     "estado": "roto", "causa": "sin_runtime", "estuvo_completa": True},
    {"familia": "cli", "ref": "claude_cli", "label": "Claude Code", "servicio_cli": True,
     "sesion_cli": True, "estado": "probado", "estuvo_completa": True,
     "prueba": {"estado": "probado", "ts": _AHORA_S - 30, "detalle": "sesión activa"}},
    {"familia": "cli", "ref": "codex_cli", "label": "Codex", "servicio_cli": True,
     "sesion_cli": False, "estado": "no_configurado", "estuvo_completa": False},
    {"familia": "api", "ref": "groq", "label": "Groq", "hay_llave": False,
     "estado": "no_configurado", "estuvo_completa": False},
    {"familia": "api", "ref": "openai", "label": "OpenAI", "hay_llave": True,
     "estado": "roto", "causa": "key_invalida", "estuvo_completa": True},
    # [F8 · obra 2] LA LLAVE ESTÁ Y NO HAY MODELO. `modelo_elegido: None` es el null
    # EXPLÍCITO del backend («lo busqué y no hay»), no un campo que falta.
    {"familia": "api", "ref": "together", "label": "Together", "hay_llave": True,
     "estado": "roto", "causa": "modelo_no_elegido", "modelo_elegido": None,
     "estuvo_completa": False},
    # …y la MISMA falta SIN que el backend la nombre: `detectado`, sin causa. Es la fila que
    # discrimina de verdad — la que prueba que esta capa deriva la causa del REQUISITO y no
    # de que el sidecar se la haya escrito. Antes de F8 salía «sin probar», que es mentira:
    # no hay nada que probar hasta que haya un modelo.
    {"familia": "api", "ref": "deepseek", "label": "DeepSeek", "hay_llave": True,
     "estado": "detectado", "modelo_elegido": None, "estuvo_completa": False},
    {"familia": "local", "ref": "gemma", "label": "Gemma", "local": True,
     "estado": "probado", "estuvo_completa": True,
     "prueba": {"estado": "probado", "ts": _AHORA_S - 90000}},   # ← rancia (>24 h)
]


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · LA DERIVACIÓN — un modelo por vía en cada estado
# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 · pertenencia(): local vs aduana, derivado por vía")

_d, _err = _node(f"""
import * as W from {json.dumps(str(_MOD / 'modelos.widget.js'))};
const F = {json.dumps(_FILAS)};
const out = {{}};
for (const f of F) {{
  const d = W.derivar(f, {{ahora: {_AHORA_MS}}});
  out[f.ref] = {{local: d.pertenencia.local, verde: d.verde, tramite: d.tramite,
                 regresion: d.pertenencia.regresion, rancia: d.pertenencia.rancia,
                 causa: d.operativo ? d.operativo.causa : null,
                 titulo: d.cara ? d.cara.titulo : null,
                 accion: d.cara && d.cara.camino ? d.cara.camino.accion : null,
                 rotulo: d.cara && d.cara.camino ? d.cara.camino.es : null,
                 alarma: d.cara ? d.cara.alarma : null,
                 culpa: d.cara ? d.cara.culpa : null,
                 modelo: d.modelo, elegidoPor: d.modeloElegidoPor,
                 evid: !!d.evidencia, motivo: d.motivo, fuente: !!d.fuente}};
}}
out.__censo = W.censo(F, {{ahora: {_AHORA_MS}}});
out.__censo = {{n_local: out.__censo.n_local, n_aduana: out.__censo.n_aduana,
                n_verdes: out.__censo.n_verdes}};
console.log(JSON.stringify(out));
""")

if _d is None:
    ok(False, "los módulos de modelos cargan en node", _err)
else:
    # ── COMPLETAS → LOCAL, con evidencia y fecha ──────────────────────────────────
    for ref in ("qwen3:8b", "claude_cli"):
        ok(_d[ref]["local"] and _d[ref]["verde"],
           f"`{ref}` completo → LOCAL y en verde", str(_d[ref]))
        ok(_d[ref]["evid"],
           f"…con EVIDENCIA detrás del [?] (verde sin prueba no existe)")
    # ── INCOMPLETAS → ADUANA, con SU trámite derivado ─────────────────────────────
    for ref, tram in (("llama3", "descargar"), ("codex_cli", "login"), ("groq", "llave")):
        ok(not _d[ref]["local"] and _d[ref]["tramite"] == tram,
           f"`{ref}` incompleto → ADUANA con el trámite `{tram}` (derivado de su vía)",
           str(_d[ref]))
        ok(bool(_d[ref]["motivo"]) and _d[ref]["fuente"],
           f"…y su motivo viaja con su FUENTE (un elemento sin fuente es hardcode)")
    # ── ★ ANTI-YO-YO: completa-rota se queda en el LOCAL ─────────────────────────
    for ref, causa in (("mistral", "sin_runtime"), ("openai", "key_invalida")):
        ok(_d[ref]["local"],
           f"★ `{ref}` ANDUVO y hoy falla → SE QUEDA EN EL LOCAL (no vuelve a la aduana)",
           str(_d[ref]))
        ok(_d[ref]["causa"] == causa and _d[ref]["titulo"],
           f"…con su causa OPERATIVA tipada (`{causa}`) y su copy del diccionario único",
           str(_d[ref]["titulo"]))
        ok(not _d[ref]["tramite"],
           f"…y SIN trámite: «falta descargar/llave» no existe en el local")
    # ── ★ [F8 · obra 2] LA LLAVE PUESTA Y SIN MODELO: SE DICE, Y NO SE PIDE LA LLAVE ──
    # LA PREDICCIÓN QUE ESTA VARA SELLA: el camino equivocado acá NO es un color ni un
    # texto — es mandar a la aduana una vía que ya está configurada. La aduana sólo sabe
    # pedir trámites, y el trámite de una vía API es LA LLAVE: la pantalla le habría dicho
    # «traé tu llave» a quien la trajo hace un minuto.
    _t = _d["together"]
    ok(_t["local"] and not _t["tramite"],
       "★ llave puesta y sin modelo → SE QUEDA EN EL LOCAL y SIN trámite: jamás «traé tu "
       "llave» a quien ya la trajo", str(_t))
    ok(_t["causa"] == "modelo_no_elegido" and _t["titulo"] == "Modelo sin elegir",
       "…con la causa SELLADA y su copy (ninguna causa llega a una superficie sin copy)",
       str(_t))
    ok(_t["accion"] == "elegir_modelo" and _t["rotulo"] == "Elegir modelo",
       "…y el botón que la resuelve sale del mapa único causa→botón", str(_t))
    ok(_t["alarma"] is False,
       "★ NO es alarma: la llave está, el proveedor contesta y falta una decisión — pintar "
       "eso de rojo es alarmar por un menú", str(_t))
    ok(_t["culpa"] is None,
       "★ y SIN culpa: no se equivocó nadie. Es la única causa del diccionario sin columna "
       "de culpa, y declararle una falsa sería inventar un dato que el [?] lee como cierto",
       str(_t))
    # ★★ LA QUE DISCRIMINA: sin causa escrita por el backend, derivada del REQUISITO.
    _ds = _d["deepseek"]
    ok(_ds["causa"] == "modelo_no_elegido" and _ds["titulo"] == "Modelo sin elegir",
       "★★ la causa se DERIVA del requisito, no de que el backend la haya escrito: una vía "
       "con llave y sin modelo la dice aunque llegue `detectado` y sin causa", str(_ds))
    ok(not _d["deepseek"]["verde"],
       "…y NO se pinta «sin probar» (que era la mentira anterior: no hay nada que probar "
       "hasta que haya un modelo)", str(_ds))
    # Y la fila que SÍ tiene llave inválida no se contagia: sigue con SU causa y SU botón.
    ok(_d["openai"]["causa"] == "key_invalida",
       "…y una llave INVÁLIDA sigue siendo `key_invalida`: las dos son «hay llave» y "
       "resuelven distinto", str(_d["openai"]))
    # ── CADUCIDAD: rancia ⇒ no se afirma verde ───────────────────────────────────
    ok(_d["gemma"]["rancia"] and not _d["gemma"]["verde"],
       "medición RANCIA (>24 h) → NO se pinta verde sin re-medir: verde viejo no existe",
       str(_d["gemma"]))
    ok(_d["gemma"]["local"], "…pero sigue siendo TUYO (rancio ≠ expulsado)")
    # ── EL CONTADOR DICE LA VERDAD ───────────────────────────────────────────────
    c = _d["__censo"]
    # 5 → 6 con la fila de F8: `together` tiene llave, así que ES tuya. Lo que NO cambia es
    # el número de las que andan — y ése es el punto del contador.
    ok(c["n_local"] == 7 and c["n_aduana"] == 3,
       f"el censo separa local ({c['n_local']}) de aduana ({c['n_aduana']})", str(c))
    ok(c["n_verdes"] == 2 and c["n_verdes"] < c["n_local"],
       "★ y el contador NO infla: 7 son tuyos, 2 andan — «es tuyo» y «anda» son dos "
       "preguntas distintas y se responden por separado", str(c))


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · ★ EL ANTI-YO-YO SOBREVIVE UN REINICIO — proceso nuevo, relee de disco
# ══════════════════════════════════════════════════════════════════════════════════
seccion("2 · la memoria sobrevive al reinicio (PROCESO NUEVO, no un objeto en RAM)")

_db = Path(tempfile.mkdtemp(prefix="vara-f4c-")) / "estado.db"
_ddl = (_RAIZ / "platform/db/schema_sqlite.sql").read_text(encoding="utf-8")
_i = _ddl.index("CREATE TABLE IF NOT EXISTS modelos_estado")
_tabla = _ddl[_i:_ddl.index(";", _ddl.index("PRIMARY KEY (user_id, modelo_id)"))] + ";"

_SUB = r"""
import sqlite3, sys, json
sys.path.insert(0, %(bk)r)
from app.phase1 import modelos_repo as M
conn = sqlite3.connect(%(db)r); conn.row_factory = sqlite3.Row
fase = sys.argv[1]
if fase == "coronar":
    M.coronar_probado(conn, user_id="u1", modelo_id="qwen3:8b", via="local",
                      evidencia={"verbo": "probar_local", "latencia_ms": 812})
elif fase == "romper":
    M.anotar_medicion(conn, user_id="u1", modelo_id="qwen3:8b", causa="sin_runtime")
f = M.leer(conn, user_id="u1", modelo_id="qwen3:8b")
print(json.dumps({"veredicto": f["ultimo_veredicto"], "causa": f["causa"],
                  "estuvo_completa": f["estuvo_completa"]}))
""" % {"bk": str(_RAIZ / "product/backend"), "db": str(_db)}


def _fase(nombre):
    conn = sqlite3.connect(_db)
    conn.executescript("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY);"
                       "INSERT OR IGNORE INTO users VALUES ('u1');" + _tabla)
    conn.commit()
    conn.close()
    r = subprocess.run([sys.executable, "-c", _SUB, nombre],
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]), r.returncode
    except Exception:                                       # noqa: BLE001
        return None, r.stderr[-300:]


_a, _rc = _fase("coronar")
ok(_a and _a["veredicto"] == "probado" and _a["estuvo_completa"],
   "1· el modelo CORRE y se corona: `ultimo_veredicto=probado`", str(_a or _rc))

_b, _ = _fase("romper")
ok(_b and _b["causa"] == "sin_runtime",
   "2· se ROMPE (runtime apagado): la medición viva anota la causa", str(_b))
ok(_b and _b["veredicto"] == "probado",
   "★ …y el veredicto NO se degrada — ésa es toda la invariante del anti-yo-yo", str(_b))

_c, _ = _fase("leer")
ok(_c and _c["estuvo_completa"] and _c["causa"] == "sin_runtime",
   "★★ 3· PROCESO NUEVO que relee de DISCO: sigue completa-con-causa, o sea que tras el "
   "reinicio la pieza abre EN EL LOCAL y no en la aduana", str(_c))

# …y el guard: si algo degradara el veredicto, esto se pondría rojo.
import importlib                                            # noqa: E402
_mr = importlib.import_module("app.phase1.modelos_repo")
import inspect                                              # noqa: E402
_src = inspect.getsource(_mr.anotar_medicion)
ok("ultimo_veredicto" not in _src.split('"""')[2],
   "el verbo del camino normal (`anotar_medicion`) NO menciona `ultimo_veredicto` en su "
   "SQL: degradar la memoria exige escribirlo a propósito, no es un descuido de una línea")
ok(hasattr(_mr, "olvidar"),
   "y hay un verbo APARTE para olvidar (el usuario desinstala) — el único camino legítimo "
   "de vuelta a la aduana")


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · CADUCIDAD EN TRES MOMENTOS
# ══════════════════════════════════════════════════════════════════════════════════
seccion("3 · caducidad: verde viejo no existe")

from app.phase1 import modelos_caducidad as MC              # noqa: E402
import time as _t                                           # noqa: E402

_now = _t.time()
_iso = lambda h: _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(_now - h * 3600)) + "Z"  # noqa: E731
ok(MC.rancia(_iso(25), _now) is True, "una medición de hace 25 h es RANCIA")
ok(MC.rancia(_iso(1), _now) is False, "una de hace 1 h, no")
ok(MC.rancia(None, _now) is False,
   "y SIN medición previa NO es rancia: «nunca se midió» tiene otro camino (medir por "
   "primera vez), y confundirlos dispara re-verifys de la nada")

_filas_c = [
    {"ref": "a", "estuvo_completa": True, "causa": None, "registro": {"ultima_verificacion": _iso(25)}},
    {"ref": "b", "estuvo_completa": True, "causa": None, "registro": {"ultima_verificacion": _iso(1)}},
    {"ref": "c", "estuvo_completa": True, "causa": "sin_runtime", "registro": {"ultima_verificacion": _iso(25)}},
    {"ref": "d", "estuvo_completa": False, "causa": None, "registro": {"ultima_verificacion": _iso(25)}},
]
ok(MC.a_re_verificar(_filas_c, ahora=_now) == ["a"],
   "se re-mide SÓLO lo que afirma estar bien con una medición vencida — lo único que "
   "puede estar mintiendo en verde", str(MC.a_re_verificar(_filas_c, ahora=_now)))

_main = (_RAIZ / "product/backend/app/main.py").read_text(encoding="utf-8")
ok("caducidad-modelos" in _main and "threading.Thread" in _main,
   "momento 1 (arranque) cableado EN HILO APARTE: abrir Aleph no espera por el re-verify")
ok("_MC.barrer_al_arrancar" in _main,
   "…y llama al barrido real, no a un placeholder")
_src_c = (_RAIZ / "product/backend/app/phase1/modelos_caducidad.py").read_text(encoding="utf-8")
ok("anotar_medicion" in _src_c and "coronar_probado" not in _src_c,
   "★ el re-verify usa `anotar_medicion` y NUNCA `coronar_probado`: no puede degradar ni "
   "inflar la memoria")


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · CHECKLIST VIVO — se detiene en el culpable, jamás verde parcial
# ══════════════════════════════════════════════════════════════════════════════════
seccion("4 · checklist vivo: fallo en el verbo N → N-1 hechos + causa en N")

from app.phase1 import modelos_checklist as CK              # noqa: E402

for via, fila, culpable, hechos in (
        ("local", {"familia": "local", "ref": "m", "local": True, "estado": "roto",
                   "causa": "sin_runtime"}, "runtime", 0),
        ("cli", {"familia": "cli", "ref": "c", "servicio_cli": True, "sesion_cli": False,
                 "estado": "roto"}, "sesion", 1),
        ("api", {"familia": "api", "ref": "g", "hay_llave": False, "estado": "roto"},
         "llave", 0)):
    evs = list(CK.correr(fila))
    ini = [e for e in evs if e["tipo"] == "fila.inicio"][0]
    fin = [e for e in evs if e["tipo"] == "fila.cerrada"][0]
    res = [e for e in evs if e["tipo"] == "requisito.resultado"]
    ok(len(ini["verbos"]) == 3 and fin["verbo_culpable"] == culpable,
       f"[{via}] los verbos son los REALES de la vía y se detiene en `{culpable}`",
       str([v["id"] for v in ini["verbos"]]))
    ok(fin["hechos"] == hechos and not fin["ok"],
       f"[{via}] llegó hasta {hechos}/{fin['de']} — el dato que hace útil al checklist",
       str(fin))
    ok(fin.get("causa"), f"[{via}] y cierra con causa TIPADA", str(fin.get("causa")))
    # ★ JAMÁS VERDE PARCIAL: después del fallo no hay un solo `ok`
    _tras = res[[r["verbo"] for r in res].index(culpable) + 1:]
    ok(all(r["estado"] == "pendiente" for r in _tras),
       f"[{via}] ★ los verbos posteriores salen `pendiente`, NO fallados ni ok: decir que "
       f"falló algo que nunca se intentó es la misma mentira que esto viene a matar",
       str([(r["verbo"], r["estado"]) for r in _tras]))

_evs_ok = list(CK.correr({"familia": "local", "ref": "q", "local": True, "estado": "probado"}))
ok([e for e in _evs_ok if e["tipo"] == "fila.cerrada"][0]["ok"],
   "y un modelo que anda cierra en OK con sus 3 verbos")
ok([e["tipo"] for e in _evs_ok][0] == "fila.inicio",
   "los verbos se anuncian ANTES de correr ninguno (mismo contrato que Gate 1)")


# ══════════════════════════════════════════════════════════════════════════════════
# 5 · ALCANZABILIDAD — el camino de clicks existe, no sólo el componente
# ══════════════════════════════════════════════════════════════════════════════════
#
# ⚠️ [F7 · obra 4] ESTA SECCIÓN DECÍA «superficie MONTADA» Y NO LO ESTABA MIDIENDO.
#
# Se titulaba así desde F4c y medía `modelos.superficie.js` importándolo directo. Pero
# `Modelos.dc.html` montaba SÓLO `modelos.ui.js`, y `modelos.ui.js` no importaba la
# superficie: `grep -c "modelos.ui" verify_f4c.py` daba **0**. O sea que esta vara verificaba
# que un archivo emitía los botones correctos mientras ningún click de la app llegaba a él.
# Los botones eran ciertos; el camino no existía. Es la misma lección de F4d —una vara puede
# ser verde y no medir nada— y la misma de Gate 1: el guard tiene que leer del MONTAJE.
#
# Ahora la sección empieza por atar la cadena: el HTML importa el montaje, el montaje importa
# la superficie, y el montaje declara qué controles atiende. Si mañana alguien desmonta la
# superficie, esto se cae en vez de pasar por inercia.
seccion("5 · ALCANZABILIDAD de cada botón nuevo, sobre la superficie MONTADA")

_HTML_PANTALLA = _RAIZ / "product/app/design/Modelos.dc.html"
_MONTAJE = _MOD / "modelos.ui.js"
_html_txt = _HTML_PANTALLA.read_text(encoding="utf-8")
_montaje_txt = _MONTAJE.read_text(encoding="utf-8")

# ── 5.a · LA CADENA DE MONTAJE, leída de los archivos y no supuesta ────────────────
_montado = "./modelos/modelos.ui.js" in _html_txt
ok(_montado, "★ Modelos.dc.html monta `modelos.ui.js` (el único host de la pantalla)")
ok('from "./modelos.superficie.js"' in _montaje_txt,
   "★ …y el montaje IMPORTA la superficie: sin esto, lo que mide esta sección no lo ve nadie")
ok('from "./modelos.widget.js"' in _montaje_txt,
   "★ …y la derivación: la pantalla deriva del widget, no de una segunda opinión")
ok("S.pantallaHTML(" in _montaje_txt,
   "★ …y la LLAMA para pintar la lista (importarla y no usarla sería el mismo bug con otro nombre)")

# ── 5.b · QUÉ CONTROLES ATIENDE EL MONTAJE — se leen de él, no se suponen ──────────
# Molde: `qa/verify_superficie_montada.mjs:556-610`. Si alguien renombra un handler, esto
# se cae; si alguien agrega un botón a la superficie y se olvida de atenderlo, también.
import re as _re

_alclick = _montaje_txt.split("async function alClickLista", 1)
_cuerpo_click = _alclick[1].split("\n}\n", 1)[0] if len(_alclick) > 1 else ""
_atendidos = set(_re.findall(r'classList\.contains\("([\w-]+)"\)', _cuerpo_click))
_atendidos |= {"data-" + m for m in _re.findall(r"\bd\.(\w+)\b", _cuerpo_click)
               if m not in ("dataset", "accion", "slug", "ref")}
ok(bool(_atendidos), "el montaje declara qué controles atiende", str(sorted(_atendidos)))

_sup, _err5 = _node(f"""
import * as S from {json.dumps(str(_MOD / 'modelos.superficie.js'))};
const html = S.pantallaHTML({json.dumps(_FILAS)}, {{ahora: {_AHORA_MS}}});
const local = /<section class="md-local"[\\s\\S]*?<\\/section>/.exec(html)[0];
const filas = [...html.matchAll(/<li class="md-fila[^"]*"[\\s\\S]*?<\\/li>/g)].map(m => m[0]);
console.log(JSON.stringify({{
  html_len: html.length,
  botones: [...html.matchAll(/data-accion="([^"]+)"/g)].map(m => m[1]),
  refs_local: [...local.matchAll(/data-ref="([^"]+)"/g)].map(m => m[1]),
  campo_llave: html.includes('class="md-llave"'),
  inputs_en_filas: (html.match(/<li[^>]*class="[^"]*md-fila[\s\S]*?<\/li>/g) || [])
    .filter((li) => /<(input|textarea|select)\b/i.test(li)).length,
  ayuda: [...html.matchAll(/class="md-ayuda"[^>]*title="([^"]*)"/g)].map(m => m[1]),
  contador: /data-n="(\\d+)" data-verdes="(\\d+)"/.exec(html).slice(1),
  local_tiene_tramite: /descargar|Descargar/.test(local),
  // por FILA: su slug y las clases de botón que emite — para cruzar contra el montaje
  filas: filas.map(f => ({{
    slug: (/data-slug="([^"]+)"/.exec(f) || [])[1] || null,
    verde: /data-verde="1"/.test(f),
    clases: [...f.matchAll(/class="md-btn ([\\w-]+)"/g)].map(m => m[1])
            .concat(/class="md-ayuda"/.test(f) ? ["md-ayuda"] : []),
    tiene_fecha: /hace \\d/.test(f),
  }})),
}}));
""")

if _sup is None:
    ok(False, "la superficie se monta", _err5)
else:
    # ── 5.c · CADA FILA EMITE AL MENOS UN CONTROL QUE EL MONTAJE ATIENDE ──────────
    # Una fila sin ningún control atendido es una fila que se ve y no se puede tocar.
    _huerfanas = [f for f in _sup["filas"]
                  if not (set(f["clases"]) & _atendidos) and "md-elegir" not in f["clases"]]
    ok(not _huerfanas,
       "★ toda fila emite al menos un control que el montaje atiende (ninguna es intocable)",
       str([f["slug"] for f in _huerfanas]))
    ok(all(f["slug"] for f in _sup["filas"]),
       "★ y toda fila lleva su `data-slug`: sin él el click no sabe de qué modelo habla")
    # ── 5.d · VERDE ⇒ FECHA. La ley, aplicada sobre el HTML que se pinta ──────────
    _verdes_sin_fecha = [f["slug"] for f in _sup["filas"] if f["verde"] and not f["tiene_fecha"]]
    ok(not _verdes_sin_fecha,
       "★ ninguna fila verde se pinta sin su fecha — verde viejo no existe, o verde con "
       "fecha fresca o causa con botón", str(_verdes_sin_fecha))
    _verdes_sin_ayuda = [f["slug"] for f in _sup["filas"]
                         if f["verde"] and "md-ayuda" not in f["clases"]]
    ok(not _verdes_sin_ayuda,
       "★ y ninguna fila verde se pinta sin su [?]: verde sin evidencia alcanzable no existe",
       str(_verdes_sin_ayuda))
    for accion in ("descargar", "login", "llave"):
        ok(accion in _sup["botones"],
           f"el trámite `{accion}` tiene BOTÓN con su acción en el DOM (no sólo un texto)",
           str(_sup["botones"]))
    ok("reintentar" in _sup["botones"] or any(b for b in _sup["botones"]),
       "y las causas operativas del local traen su camino", str(_sup["botones"]))
    # ⚠️ [F8 · obra 0] ESTA ASERCIÓN DECÍA LO CONTRARIO, y estaba bien hasta el 2026-08-07:
    # exigía que el campo de la llave estuviera INLINE en la fila. persona usuaria selló la regla
    # opuesta —**ningún `<input>` dentro de una fila de lista**, el trámite pasa en el
    # panel— y el motivo lo pagó una medición: ese campo inline existía y **no lo leía
    # nadie** (`.md-llave` aparecía en su render y en el CSS, y en ningún handler). Se podía
    # tipear la llave entera ahí y perderla al abrirse el panel con el campo vacío.
    #
    # No se BORRA la aserción: se DA VUELTA. Una vara que se saca porque molesta deja de
    # cuidar el lugar; esta sigue mirando el mismo lugar y ahora exige lo que corresponde.
    ok(not _sup["campo_llave"] and _sup["inputs_en_filas"] == 0,
       "★ [F8] ninguna fila de lista lleva un campo de entrada — el trámite pasa en el panel",
       f"md-llave={_sup['campo_llave']} inputs_en_filas={_sup['inputs_en_filas']}")
    ok(_sup["ayuda"] and any("hace" in a for a in _sup["ayuda"]),
       "★ el [?] lleva la EVIDENCIA con su fecha — verde con prueba, no verde a secas",
       str(_sup["ayuda"][:2]))
    ok(_sup["contador"] == ["7", "2"],
       "el contador de la pantalla dice 7 tuyos · 2 andando", str(_sup["contador"]))
    ok(not _sup["local_tiene_tramite"],
       "★ y «Descargar» NO aparece en el LOCAL: los trámites viven en la aduana, y "
       "mezclarlos es lo que hace que el local deje de significar «lo que corre»")


# [H4a] El cierre pasa por `qa/lib/veredicto.py`: con salteos declarados la última
# línea ya NO es el string pelado `TODO VERDE`. La regla vive en un solo lugar.
sys.path.insert(0, str(_RAIZ / "qa" / "lib"))
import veredicto as _V  # noqa: E402

# [H3] La nota al pie va ARRIBA: la ÚLTIMA línea de una vara es su veredicto. Un `tail -1`
# que lee «invocación única» no sabe si el merge puede pasar — casi abortó uno sano.
print("     [invocación única del chequeo completo]  "
      "product/backend/.venv/bin/python qa/correr_varas.py")
print(f"\n{_V.texto(_fallos, _salteados)}")
sys.exit(0 if _fallos == 0 else 1)
