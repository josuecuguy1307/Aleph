#!/usr/bin/env python3
"""verify_f4b.py — LA VARA DE F4b (Gate 2 · LA CARA).

⚠️ **NO ANIDA VARAS.** Regla sellada por persona usuaria al cerrar F4a: durante la obra corre SÓLO la
vara propia; el chequeo completo es UNA corrida de `qa/correr_varas.py`. El motivo está
medido tres veces en F4a — y la peor fue un rojo REAL que estuvo escondido toda una fase
porque su vara moría por timeout, y un timeout se lee igual que «todavía corriendo».

Corre `node` para evaluar los módulos del front. Eso NO es anidar: node es una herramienta,
como `python` — lo que está prohibido es invocar OTRA VARA.

    product/backend/.venv/bin/python product/backend/verify_f4b.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parents[1]
for _p in (str(_AQUI), str(_RAIZ / "platform"), str(_RAIZ / "platform" / "assembler")):
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
print("VARA F4b · LA CARA")
print("=" * 80)

_SEIS = ["contexto_excedido", "politica_de_contenido", "cli_ocupado",
         "turno_detenido", "sesion_perdida", "runtime_ocupado"]


def _node(codigo: str):
    """Evalúa un módulo del front y devuelve su JSON. `None` si node no está."""
    r = subprocess.run(["node", "--input-type=module", "-e", codigo],
                       capture_output=True, text=True, timeout=90, cwd=str(_RAIZ))
    if r.returncode != 0:
        return None, r.stderr[-400:]
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]), ""
    except Exception as e:                                  # noqa: BLE001
        return None, f"{e} · stdout={r.stdout[-200:]}"


_SEM = str(_RAIZ / "product/app/design/cuarto/cuarto.semaforo.js")


# ══════════════════════════════════════════════════════════════════════════════════
# 1 · LAS SEIS CAUSAS TIENEN CARA — copy + camino, jamás el string crudo
# ══════════════════════════════════════════════════════════════════════════════════
seccion("1 · las seis causas de F1c: copy + botón, derivados del diccionario ÚNICO")

_d, _err = _node(f"""
import * as S from {json.dumps(_SEM)};
const SEIS = {json.dumps(_SEIS)};
const AHORA = new Date('2026-08-04T18:00:00').getTime();
const out = {{}};
for (const c of SEIS) {{
  const f = S.caraDeCausa({{causa:c, detalle:'DETALLE-DEL-TRADUCTOR', reintentable:false}}, AHORA);
  out[c] = {{titulo:f.titulo, texto:f.texto, alarma:f.alarma, sinBoton:f.sinBoton,
             boton:(f.camino&&!f.sinBoton)?f.camino.es:null, desconocida:f.desconocida}};
}}
// rate_limit con los segundos del proveedor → hora de pared
out.__hora = S.caraDeCausa({{causa:'rate_limit', detalle:'x', reintentable:true, retry_after_s:2700}}, AHORA).hora;
// una causa que el diccionario NO conoce: se ve que falta, no queda muda
out.__nueva = S.caraDeCausa({{causa:'sin_red', detalle:'d'}}, AHORA).desconocida;
console.log(JSON.stringify(out));
""")

if _d is None:
    ok(False, "los módulos del front cargan en node", _err)
else:
    for c in _SEIS:
        f = _d[c]
        ok(not f["desconocida"] and f["titulo"] and f["titulo"] != "Algo falló",
           f"`{c}` tiene copy propio en el diccionario (no cae en el genérico)",
           str(f["titulo"]))
        ok(f["texto"] == "DETALLE-DEL-TRADUCTOR",
           f"…y el cuerpo es el `detalle` DEL TRADUCTOR, ya redactado — jamás `str(exc)`",
           str(f["texto"]))
    # las dos del PEDIDO no ofrecen botón: lo que hay que cambiar es el texto del usuario
    for c in ("contexto_excedido", "politica_de_contenido"):
        ok(_d[c]["sinBoton"] and not _d[c]["boton"],
           f"`{c}` NO ofrece botón: un [Reintentar] devolvería la misma negativa",
           str(_d[c]["boton"]))
    # las dos de ESPERAR sí, porque el turno de adelante termina
    for c in ("cli_ocupado", "runtime_ocupado"):
        ok(bool(_d[c]["boton"]),
           f"`{c}` SÍ ofrece botón: el reintento puede salir bien en segundos",
           str(_d[c]["boton"]))
    ok(_d["turno_detenido"]["alarma"] is False,
       "`turno_detenido` NO es alarma: lo paró el usuario, no falló nada")
    ok(all(_d[c]["alarma"] for c in _SEIS if c != "turno_detenido"),
       "…y las otras cinco SÍ son alarma (sólo la que no es un fallo se exceptúa)")
    ok(_d["__hora"] == "18:45",
       "`rate_limit` con `retry_after_s` del proveedor → hora de pared («18:45»): el "
       "«esperá» sin hora es un consejo, con hora es un dato", str(_d["__hora"]))
    ok(_d["__nueva"] is False,
       "una causa vieja sigue reconocida (el diccionario no se rompió al crecer)")


# ══════════════════════════════════════════════════════════════════════════════════
# 2 · EL CABLE: la causa tipada llega desde el motor hasta la cara
# ══════════════════════════════════════════════════════════════════════════════════
seccion("2 · el cable de punta a punta: `_stream_openai` tipa, el SSE la lleva")

from app.phase1 import stream_chat as SC                    # noqa: E402
import errores_modelo as E                                  # noqa: E402

ok(SC._tr is not None, "el traductor está cableado en el camino de STREAMING (la Sala)")

_h = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
_e = SC._tipar(_h, "https://api.groq.com/openai/v1")
ok(isinstance(_e, E.ErrorDeModelo) and _e.causa.causa == E.KEY_INVALIDA,
   "un 401 por el camino del chat → `key_invalida` tipada (antes subía crudo)",
   getattr(getattr(_e, "causa", None), "causa", type(_e).__name__))
ok("Unauthorized" not in _e.causa.detalle,
   "…y el texto del proveedor NO entra en el detalle que verá la persona", _e.causa.detalle)

# EL ÍTEM HEREDADO DE F4a, cerrado acá.
_t = SC._tipar(TimeoutError("timed out"), "http://127.0.0.1:11434/v1")
ok(_t.causa.causa == E.RUNTIME_OCUPADO,
   "Ollama OCUPADO → `runtime_ocupado`, NO `sin_runtime` (el ítem que F4a dejó heredado: "
   "decía «prendé Ollama» con Ollama corriendo)", _t.causa.causa)
ok(_t.causa.causa != E.SIN_RUNTIME, "…y jamás `sin_runtime`: el runtime contestó la liveness")

# el cuerpo del `:8926` gana al status pelado (mismo candado que F4a §2.5)
_cuerpo = json.dumps({"error": {"causa": {"causa": "turno_detenido", "estado": "roto",
                                          "detalle": "Lo paraste vos.", "evidencia": {},
                                          "reintentable": False, "fuente": "cli"}}})
_c = SC._causa_cli_brain(_cuerpo)
ok(_c is not None and _c.causa == E.TURNO_DETENIDO,
   "el `error.causa` del server `:8926` gana al status pelado (un 409 saldría "
   "`error_upstream`, o sea «el proveedor rechazó el pedido» por un stop del usuario)",
   getattr(_c, "causa", None))
ok(SC._causa_cli_brain('{"error":{"causa":{"causa":"inventada","estado":"roto"}}}') is None,
   "…y una causa FUERA del vocabulario cerrado se ignora: el cuerpo de un tercero no nos "
   "dicta el diagnóstico")

# la Sala ya no adivina con un regex
_sala = (_RAIZ / "product/app/design/sala/sala.html").read_text(encoding="utf-8")
ok("Se cortó la conexión. Prueba de nuevo.'" in _sala and "caraDeCausa" in _sala,
   "la Sala deriva con `caraDeCausa` y deja el mensaje genérico SÓLO como último recurso")
# El regex viejo sigue APARECIENDO en el archivo — dentro del comentario que documenta
# qué hacía y por qué murió. Así que la aserción mira LÍNEAS EJECUTABLES: una cita en un
# comentario es memoria; una línea viva sería el bug de vuelta.
_vivas = [l for l in _sala.splitlines()
          if "429|rate|too many" in l and not l.lstrip().startswith("//")]
ok(not _vivas,
   "MURIÓ el regex que mostraba «Se cortó la conexión» ante una llave inválida, una cuenta "
   "sin saldo o un pedido demasiado largo (queda citado en el comentario, no en el código)",
   str(_vivas[:1]))
ok("erred.causa=obj.causa" in _sala.replace(" ", ""),
   "la causa del SSE viaja colgada del Error hasta el `catch`")

_router = (_RAIZ / "product/backend/app/phase1/router.py").read_text(encoding="utf-8")
ok('_err["causa"] = _c.como_dict()' in _router,
   "el canal SSE emite `causa` AL LADO de `detail` (aditivo, `detail` intacto)")


# ══════════════════════════════════════════════════════════════════════════════════
# 3 · DEGRADED VISIBLE SIEMPRE
# ══════════════════════════════════════════════════════════════════════════════════
seccion("3 · la degradación jamás queda muda")

ok("narrDegradedFallback" in _sala,
   "hay red de atrás: si el `notice` del motor no llegó, `record.degraded` la narra igual")
ok("narrDegradedFallback(ev.degraded)" in _sala,
   "…y se dispara desde el `final`, que SIEMPRE llega (el aviso es uno por run y viaja "
   "por el espinazo: un consumidor que conecta tarde lo perdía)")

_d2, _err2 = _node(f"""
import * as S from {json.dumps(_SEM)};
const f = S.caraDeCausa({{causa:'rate_limit', detalle:'Llegaste al límite (HTTP 429).'}});
console.log(JSON.stringify({{texto:f.texto}}));
""")
ok(_d2 is not None and _d2["texto"].startswith("Llegaste"),
   "la causa de la degradación se lee con el MISMO derivador que el resto (una sola cara "
   "por causa en todo el producto)", str(_d2))


# ══════════════════════════════════════════════════════════════════════════════════
# 4 · PARAR EL TURNO — el camino de clicks COMPLETO (ALCANZABILIDAD)
# ══════════════════════════════════════════════════════════════════════════════════
seccion("4 · parar el turno: la cadena entera, no sólo el componente")

_sc = (_RAIZ / "product/backend/app/phase1/stream_chat.py").read_text(encoding="utf-8")
ok('yield ("turno", str(_ax["turno_id"]))' in _sc,
   "1· `_stream_openai` LEE el `turno_id` del annex que F2d puso en el primer chunk "
   "(antes lo tiraba)")
ok('{"type": "turno", "turno_id": tok}' in _router,
   "2· el SSE lo emite como canal propio")
ok("ST.turnoId=obj.turno_id" in _sala.replace(" ", "").replace("ST.turnoId=obj.turno_id||null",
                                                               "ST.turnoId=obj.turno_id"),
   "3· la Sala lo guarda")
ok("signals.stopClicked.listener" in _sala,
   "4· el STOP del composer —que ya existía y sólo cerraba el canal visual— ahora llama")
ok("function pararTurno()" in _sala and "'/v1/turnos/detener'" in _sala,
   "5· …a `pararTurno()`, que pega al endpoint")
ok('@router.post("/turnos/detener")' in _router,
   "6· el endpoint del backend EXISTE (era el tramo que faltaba: `stop_turn` vivía sólo "
   "en `:8926` y la Sala habla con este backend)")
ok("/turnos/detener" in _router and "PUPPET_CLI_BRAIN_BASE_URL" in _router,
   "7· …y hace de puente al server `:8926`, donde vive el `stop_turn` de F2d")
ok("window.__pararTurno" in _sala,
   "8· y hay seam para que esta vara alcance el camino sin un browser")
# `no_habia_turno` NO es un error
ok('"resultado": "no_habia_turno"' in _router,
   "`no_habia_turno` se devuelve 200: es lo normal cuando alguien aprieta parar justo "
   "cuando la respuesta llegaba — un 4xx ahí convierte un final feliz en cartel rojo")


# ══════════════════════════════════════════════════════════════════════════════════
# 5 · TRANSCRIPTS — se ve, se borra, y LO AJENO SOBREVIVE (medido en disco)
# ══════════════════════════════════════════════════════════════════════════════════
seccion("5 · privacidad de transcripts: el candado, medido EN DISCO")

from app.phase1 import transcripts_cli as T                 # noqa: E402
from cli_brain import sesiones as _ses                      # noqa: E402

# La regla REAL del CLI, medida sobre el store de esta máquina y end-to-end con el binario.
ok(T._slug_real("/tmp/f4b prueba_espacio") == "-private-tmp-f4b-prueba-espacio",
   "la regla de nombrado del CLI está bien replicada: TODO lo no alfanumérico → `-` "
   "(medido con el binario real desde un cwd con espacio Y guión bajo)",
   T._slug_real("/tmp/f4b prueba_espacio"))
# ══ CAMBIO DE VEREDICTO DECLARADO · F4b → F4d ══════════════════════════════════════
# Acá decía lo CONTRARIO: `!=`, con el detalle «NO es la que usa `sesiones.slug_de` — por
# eso este módulo no puede consumirla (bug de F2e, va a F4d con su evidencia)». Era
# correcto cuando se escribió: F4b había medido la regla real y `sesiones.slug_de`
# todavía traducía sólo `/`.
#
# **F4d arregló ese bug y unificó la regla** (mergeada en `c176c21`), así que desde
# entonces las dos coinciden y la aserción medía una diferencia que ya no existe: quedó
# ROJA en main desde el merge de F4d. Medido el 2026-08-08 sobre un árbol testigo
# (main @ 1242dba, sin ningún cambio de esta fase): `1 FALLO(S)`, éste.
#
# Se invierte, que es lo que hoy hay que proteger: si alguien vuelve a bifurcar las dos
# reglas, esto se pone rojo ANTES de que `existe_sesion` deje de encontrar sesiones.
ok(_ses.slug_de("/tmp/f4b prueba_espacio") == "-private-tmp-f4b-prueba-espacio",
   "★ …y `sesiones.slug_de` da LO MISMO: F4d unificó las dos reglas en un solo lugar "
   "(antes de F4d esta aserción era la inversa, y por eso quedó roja al mergearse)",
   _ses.slug_de("/tmp/f4b prueba_espacio"))

# ── EL GUARD OBLIGATORIO: un directorio AJENO creado por la vara sobrevive intacto ──
_store = tempfile.mkdtemp(prefix="vara-f4b-store-")
try:
    _pref = T._slug_real(_ses.SESIONES.raiz)
    _nuestro = Path(_store) / (_pref + "-deadbeef")
    _nuestro.mkdir()
    (_nuestro / "sesion.jsonl").write_text('{"de":"aleph"}\n')
    # …y AL LADO, una conversación del usuario. Con contenido, para poder comprobar que
    # sigue byte-idéntica y no sólo que el directorio existe.
    _ajeno = Path(_store) / "-Users-TEST_ONLY-fixture-ajeno"
    _ajeno.mkdir()
    _contenido = '{"conversacion":"TEST_ONLY fixture ajeno"}\n'
    (_ajeno / "mia.jsonl").write_text(_contenido)

    _orig = _ses.raiz_del_store
    _ses.raiz_del_store = lambda *a, **k: _store       # noqa: E731 — sonda acotada
    try:
        _v = T.donde()
        ok(_v["de_aleph"]["carpetas"] == 1 and _v["tuyos"]["carpetas"] == 1,
           "`donde()` separa lo de Aleph de lo del usuario", str(_v["de_aleph"]))

        _dry = T.limpiar(dry_run=True)
        ok(_dry["borradas"] == 1 and _nuestro.exists(),
           "el DRY-RUN dice qué borraría y NO borra nada — es la confirmación previa",
           str(_dry))

        _r = T.limpiar()
        ok(_r["ok"] and _r["borradas"] == 1, "el borrado se lleva lo de Aleph", str(_r))
        ok(not _nuestro.exists(), "…y desapareció DEL DISCO, no de un contador")
        ok(_ajeno.exists() and (_ajeno / "mia.jsonl").read_text() == _contenido,
           "★ Y LO AJENO SOBREVIVE INTACTO, byte por byte. En el store real de esta "
           "máquina hay 1.128 conversaciones del usuario: un borrado ingenuo de "
           "`~/.claude/projects/*` habría destruido 1.579 transcripts suyos")
    finally:
        _ses.raiz_del_store = _orig
finally:
    shutil.rmtree(_store, ignore_errors=True)

# la superficie lo DICE, y con la línea que no puede faltar
_set = (_RAIZ / "product/app/design/Settings.dc.html").read_text(encoding="utf-8")
ok("Conversaciones guardadas por tu CLI" in _set, "Settings tiene la sección")
ok("txTuyas" in _set and "NO se tocan" in _set,
   "…con la línea EXPLÍCITA de que las conversaciones propias del usuario no se tocan")
ok("txConfirmar" in _set and "No se puede deshacer" in _set,
   "…y una confirmación previa que dice CUÁNTAS se van a borrar antes de borrar")
ok("confirmar=true" in _set,
   "…que el backend exige: sin `confirmar=true` devuelve el dry-run, no borra")
ok("PUPPET_CLI_SESIONES" in _set or "perilla" in _set.lower(),
   "…y la perilla queda expuesta")


# ══════════════════════════════════════════════════════════════════════════════════
# 6 · THINKING DEL CLI — el canal se llena, y apagado no cambia nada
# ══════════════════════════════════════════════════════════════════════════════════
seccion("6 · thinking del CLI (excepción autorizada sobre cli_brain/server.py)")

_srv = (_RAIZ / "platform/assembler/cli_brain/server.py").read_text(encoding="utf-8")
ok('{"reasoning": carga}' in _srv,
   "el `pensando` del CLI se EMITE como `delta.reasoning` (antes se contaba y se tiraba)")
ok('_vivo["pensados"] += 1' in _srv, "…y el contador de F2a sigue intacto")
ok("def _abrir_una_vez" in _srv,
   "la apertura del SSE es UNA sola función — si el thinking abriera por su cuenta, el "
   "primer chunk se iría SIN el `turno_id` y el botón de parar se quedaría sin nada que "
   "parar (por poco rompe F2d)")
ok('annex={"turno_id": _vivo["turno_id"]}' in _srv and _srv.count("_sse_abrir()") <= 3,
   "…y el `turno_id` sale sí o sí, venga el thinking o el texto")
# CERO TEATRO
ok("if quiere_stream and carga:" in _srv,
   "sin `thinking_delta` del CLI no entra nada: el thinking JAMÁS se fabrica")
ok("delta.reasoning" in _sc or 'get("reasoning")' in _sc,
   "y río abajo `_stream_openai` ya leía ese campo — se llenó un canal que existía, no se "
   "inventó un formato")


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
