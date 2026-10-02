#!/usr/bin/env python3
"""verify_obras_del_pack.py — EL LECTOR DEL ALMACÉN DEL PACK. [Educación · cortes 3 y 4]

QUÉ CIERRA. La cosecha del borde (`artefactos_del_borde.py`, de Finanzas) exige
`json.loads` del `content` de un `role:"tool"`, y Educación no puede cumplirlo: su
harness pone ahí la PROSA que lee el modelo (`core/agentic/tool_dispatch.py:637-645`) y
lo estructurado se queda en `metadata`, que no cruza el protocolo. Barridas las 19 clases
de tool del stack, ninguna pone JSON en `ToolResult(content=…)`.

Y el segundo corte: sus entregables de verdad —ejercicio, informe, visualización, ruta,
solución— no son resultados de tool sino de CAPACIDAD, y nunca aparecen como `role:"tool"`.

EL MECANISMO YA EXISTÍA. `turn_runtime.py` persiste CADA respuesta del asistente con su
`capability`, sus `attachments_json` (los archivos generados, con url/filename/mime/size)
y su `events_json` (el stream entero, con el evento `result` de la capacidad adentro).
Faltaba el LECTOR, y eso es `obras_del_pack.py`.

QUÉ MIDE ESTA VARA, y todo corre sin levantar un server, sin llave y sin proveedor:

  A · LA FORMA DEL ALMACÉN NO ES INVENTADA. El esquema y el contenido del store de prueba
      se copian del `chat_history.db` REAL del dueño cuando está en esta máquina: mismas
      columnas, y un evento `result` con la misma forma que los 24 que ese archivo tiene.
      Si no está, la vara lo DICE y usa el esquema leído del stack — y esa mitad queda
      marcada, no verde por costumbre.
  B · LOS ARCHIVOS CRUZAN. Un PNG de verdad (bytes reales), un CSV y un `.md` puestos en
      el workspace público del pack salen clasificados y con su contenido en el sobre que
      el puente sabe abrir — y el puente los cruza de verdad: `imagen` con su data URI,
      `planilla` con `cols`+`rows`, `documento` con su texto.
  C · LAS CAPACIDADES CRUZAN. Un turno con `capability='deep_research'` y su evento
      `result` sale como informe con el texto que el usuario vio. Y `chat` NO sale: su
      respuesta ya viaja al hilo por `hilo_workspace`, y duplicarla sería el mismo texto
      en dos superficies.
  D · LAS DIRECCIONES EN LAS QUE TIENE QUE CAER: un workspace sin declaración no lee nada;
      una URL que se sale del workspace público NO se lee (guarda de path traversal); un
      archivo por encima del tope cruza como FICHA en vez de con 40 MB adentro; y el
      mismo archivo referido dos veces deja UNA obra, no dos.
  E · LA RAÍZ DEL PACK NO DIVERGIÓ de `pack.raiz_pack` — la regla está replicada y esto
      es lo que hace que la copia no se vuelva mentira en silencio.

Probala cayendo:
  ALEPH_VARA_ROMPER=sinclases    toda extensión cae al `por_defecto` → rojo en B
  ALEPH_VARA_ROMPER=sincapacidad se borra el mapa de capacidades      → rojo en C
  ALEPH_VARA_ROMPER=singuarda    la URL de traversal se deja pasar    → rojo en D

    product/backend/.venv/bin/python qa/verify_obras_del_pack.py
      0 → el lector lee y el puente cruza · 1 → no · 2 → no medible
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "platform"))
sys.path.insert(0, str(_RAIZ / "product" / "backend"))

_ROMPER = (os.environ.get("ALEPH_VARA_ROMPER") or "").strip().lower()
_FALLOS: list = []


def ok(nombre: str, cond, detalle: str = "") -> None:
    print(("  ✔ " if cond else "  ✘ ") + nombre + (("  · " + detalle) if detalle else ""))
    if not cond:
        _FALLOS.append(nombre)


def no_medible(motivo: str) -> None:
    print(f"[no medible] {motivo}")
    raise SystemExit(2)


try:
    from app.phase1 import obras_del_pack as op          # noqa: E402
    from artifacts import bridge                          # noqa: E402
except Exception as exc:                                  # noqa: BLE001
    no_medible(f"no se pudieron importar los módulos: {exc}")

# ⚠️ EL ALMACÉN DE PRUEBA VIVE EN UN `user_data_dir` PROPIO. `obras_del_pack` resuelve la
# ruta con `aleph_paths.user_data_dir()`, así que sin esto la vara leería —y el rojo
# hablaría de— el pack REAL del dueño.
_TMP = Path(tempfile.mkdtemp(prefix="vara-obras-pack-"))
os.environ["ALEPH_DATA_DIR"] = str(_TMP)
import importlib                                          # noqa: E402
import aleph_paths as _ap                                 # noqa: E402
importlib.reload(_ap)
importlib.reload(op)
if not str(op.raiz_del_pack("educacion")).startswith(str(_TMP)):
    shutil.rmtree(_TMP, ignore_errors=True)
    no_medible("no se pudo aislar el `user_data_dir`: la vara leería el pack real")


# ══ A · LA FORMA DEL ALMACÉN ═══════════════════════════════════════════════════════════
print("\nA · el esquema y la forma del evento salen del store REAL, no de una suposición")

_REAL = (Path.home() / "Library" / "Application Support" / "Aleph" / "workspaces"
         / "educacion" / "runtime" / "data" / "user" / "chat_history.db")
_ESQUEMA = None
_RESULT_REAL = None
if _REAL.is_file():
    try:
        _c = sqlite3.connect(f"file:{_REAL}?mode=ro", uri=True)
        _ESQUEMA = _c.execute(
            "select sql from sqlite_master where type='table' and name='messages'").fetchone()[0]
        for (_ev,) in _c.execute(
                "select events_json from messages where role='assistant' "
                "and events_json != '' order by id desc"):
            for _x in json.loads(_ev):
                if isinstance(_x, dict) and _x.get("type") == "result":
                    _RESULT_REAL = _x
                    break
            if _RESULT_REAL:
                break
        _c.close()
    except Exception as exc:                              # noqa: BLE001
        print(f"     (·) no se pudo leer el store real: {exc}")

if _ESQUEMA and _RESULT_REAL:
    ok("el esquema y un evento `result` salen del `chat_history.db` del dueño",
       True, f"metadata: {', '.join(sorted(_RESULT_REAL.get('metadata') or {}))}")
else:
    print("     ⚠️  [no medible] no hay `chat_history.db` real en esta máquina: el esquema "
          "sale de leer el stack, no de copiarlo. B/C siguen valiendo; esta línea no.")
    _ESQUEMA = ("create table messages (id integer primary key autoincrement, "
                "session_id text not null, role text not null, content text default '', "
                "capability text default '', events_json text default '', "
                "attachments_json text default '', metadata_json text default '{}', "
                "created_at real not null, parent_message_id integer)")
    _RESULT_REAL = {"type": "result", "source": "chat", "stage": "", "content": "",
                    "metadata": {"response": "", "completed": True}, "seq": 6}


# ── el almacén de prueba, con la forma de arriba y bytes de verdad ─────────────────────
_HOME = op.raiz_del_pack("educacion") / "runtime"
_PUBLICO = _HOME / "data" / "user"
_SALIDAS = _PUBLICO / "workspace" / "chat" / "_detached_code_execution" / "corrida"
_SALIDAS.mkdir(parents=True, exist_ok=True)

# UN PNG DE VERDAD. Son los bytes mínimos de un PNG válido (firma + IHDR + IDAT + IEND):
# se codifican en base64 acá para que la vara no dependa de tener matplotlib, pero son
# BYTES BINARIOS reales — que es lo que hace que la rama base64 del puente se ejerza.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
(_SALIDAS / "grafica.png").write_bytes(_PNG)
(_SALIDAS / "notas.csv").write_text("tema,nota\nderivadas,9\nlimites,7\n", encoding="utf-8")
(_SALIDAS / "resumen.md").write_text("# Resumen\n\nLa derivada es la pendiente.\n",
                                     encoding="utf-8")
(_SALIDAS / "entrega.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 64)

_DB = op.ruta_del_almacen("educacion")
_DB.parent.mkdir(parents=True, exist_ok=True)


def _adjunto(nombre: str, mime: str) -> dict:
    """Un registro de adjunto con la forma EXACTA que arma `artifact_attachments.py:74-83`."""
    return {"type": "image" if mime.startswith("image/") else "document",
            "filename": nombre, "mime_type": mime,
            "url": "/api/outputs/workspace/chat/_detached_code_execution/corrida/" + nombre,
            "size_bytes": (_SALIDAS / nombre).stat().st_size, "generated": True}


def _result(fuente: str, respuesta: str) -> list:
    e = json.loads(json.dumps(_RESULT_REAL))
    e["source"] = fuente
    e.setdefault("metadata", {})["response"] = respuesta
    return [{"type": "stage_start", "source": fuente}, e]


con = sqlite3.connect(_DB)
con.execute(_ESQUEMA)
con.execute(
    "insert into messages (id, session_id, role, content, capability, events_json, "
    "attachments_json, created_at) values (?,?,?,?,?,?,?,?)",
    (1, "s1", "assistant", "listo", "chat",
     json.dumps(_result("chat", "Hola 👋")),
     json.dumps([_adjunto("grafica.png", "image/png"),
                 _adjunto("notas.csv", "text/csv"),
                 _adjunto("resumen.md", "text/markdown"),
                 _adjunto("entrega.zip", "application/zip")]), 1.0))
con.execute(
    "insert into messages (id, session_id, role, content, capability, events_json, "
    "attachments_json, created_at) values (?,?,?,?,?,?,?,?)",
    (2, "s1", "assistant", "informe", "deep_research",
     json.dumps(_result("deep_research", "# Las derivadas\n\nEl informe entero.")),
     json.dumps([_adjunto("grafica.png", "image/png")]), 2.0))  # el MISMO archivo, otra vez
con.commit()
con.close()

_previo = json.loads(json.dumps(op.ALMACEN_POR_WORKSPACE))
if _ROMPER == "sinclases":
    op.ALMACEN_POR_WORKSPACE["educacion"]["clases"] = {}
if _ROMPER == "sincapacidad":
    op.ALMACEN_POR_WORKSPACE["educacion"]["capacidades"] = {}

obras = op.leer("educacion")
por_kind = {}
for o in obras:
    por_kind.setdefault(o["kind"], []).append(o)

# ══ B · LOS ARCHIVOS ═══════════════════════════════════════════════════════════════════
print("\nB · los archivos generados cruzan, y el puente los sabe abrir")
esperado = {"figura": 1, "planilla": 1, "documento": 1, "archivo": 1}
for kind, n in esperado.items():
    ok(f"{kind}: {n} obra", len(por_kind.get(kind, [])) == n,
       f"{len(por_kind.get(kind, []))} · {[o['name'] for o in por_kind.get(kind, [])]}")

cruzadas = {}
for o in obras:
    try:
        cruzadas[o["kind"]] = bridge.cross("educacion", {
            "kind": o["kind"], "name": o["name"], "data": o["data"]})
    except bridge.BridgeError as exc:
        cruzadas[o["kind"]] = {"__error": exc.code}
img = cruzadas.get("figura") or {}
# ⚠️ EL CAMPO ES `content`, Y ANTES ESTA VARA MEDÍA `data_uri` — VERDE. Es el mismo caso
# de manual que ya está escrito en `verify_oficina_puente.py:164`: el puente emitía un
# sustantivo que **no consume nadie** (el renderer lee `a.content || a.url`,
# `sala-render.js:577`), así que la vara certificaba un sobre que en la pantalla salía
# «Sin imagen.». Lo corrigió `ciencia-artefactos` para Oficina y Ciencia; ésta se escribió
# en paralelo, en otro worktree, y se quedó con el nombre viejo hasta la integración.
ok("la figura sale `imagen` con su data URI en `content`",
   img.get("type") == "imagen" and str(img.get("content", "")).startswith("data:image/png;base64,"),
   str(img.get("content") or img.get("__error") or "(nada)")[:52])
pla = cruzadas.get("planilla") or {}
ok("la planilla sale con sus filas de verdad",
   pla.get("type") == "planilla" and pla.get("cols") == ["tema", "nota"]
   and len(pla.get("rows") or []) == 2,
   f"cols={pla.get('cols')} filas={len(pla.get('rows') or [])}")
doc = cruzadas.get("documento") or {}
ok("el documento sale con su texto", doc.get("type") == "documento"
   and "pendiente" in str(doc.get("content", "")),
   str(doc.get("content", ""))[:40].replace("\n", " ⏎ "))
arc = cruzadas.get("archivo") or {}
ok("el binario sale como FICHA, no como un marco vacío",
   arc.get("type") == "informe" and "entrega.zip" in str(arc.get("content", "")),
   "ficha con nombre, formato, tamaño y ruta")

# ══ C · LAS CAPACIDADES ════════════════════════════════════════════════════════════════
print("\nC · la capacidad entrega su texto, y `chat` NO se duplica")
caps = [o for o in obras if o["fuente"] == "capacidad"]
ok("una sola obra de capacidad (deep_research)", len(caps) == 1,
   f"{[c['name'] for c in caps]}")
ok("y trae el texto que el usuario vio",
   bool(caps) and "El informe entero" in caps[0]["data"]["content"],
   (caps[0]["data"]["content"][:40] if caps else "(ninguna)"))
ok("`chat` no cruza: su respuesta ya está en el hilo de la casa",
   not any("chat" in c["name"] for c in caps))

# ══ D · LAS DIRECCIONES EN LAS QUE CAE ═════════════════════════════════════════════════
print("\nD · las direcciones en las que tiene que caer")
ok("el mismo archivo en dos mensajes deja UNA obra",
   len(por_kind.get("figura", [])) == 1 and len({o["huella"] for o in obras}) == len(obras),
   f"{len(obras)} obras, {len({o['huella'] for o in obras})} huellas")
ok("un workspace sin declaración no lee nada", op.leer("ciencia") == []
   and op.leer(None) == [] and op.leer("") == [])

publica = _PUBLICO.resolve()
fuera = op._archivo_de_url("/api/outputs/../../../../etc/hosts", publica)
if _ROMPER == "singuarda":
    fuera = Path("/etc/hosts")
ok("una URL que se sale del workspace público NO se lee", fuera is None,
   "guarda de traversal, la misma que `artifact_attachments._resolve_artifact_path`")
dentro = op._archivo_de_url(
    "/api/outputs/workspace/chat/_detached_code_execution/corrida/notas.csv", publica)
ok("y una que sí está adentro se resuelve", dentro is not None and dentro.name == "notas.csv")

_tope = op.TOPE_BYTES
try:
    op.TOPE_BYTES = 10
    chico = op._cuerpo(_SALIDAS / "notas.csv", "planilla")
finally:
    op.TOPE_BYTES = _tope
ok("un archivo por encima del tope cruza como ficha (sin bytes adentro)",
   "content" not in chico and chico.get("size") == (_SALIDAS / "notas.csv").stat().st_size,
   f"claves: {sorted(chico)}")

# ══ E · LA RAÍZ NO DIVERGIÓ ════════════════════════════════════════════════════════════
print("\nE · la regla de la raíz del pack sigue siendo la misma que la de `pack.py`")
try:
    from workspaces import pack as _pack                  # noqa: E402
    igual = str(_pack.raiz_pack("educacion")) == str(op.raiz_del_pack("educacion"))
    ok("`obras_del_pack.raiz_del_pack` == `pack.raiz_pack`", igual,
       str(op.raiz_del_pack("educacion")))
except Exception as exc:                                  # noqa: BLE001
    print(f"     ⚠️  [no medible] no se pudo importar `workspaces.pack` ({exc}): la copia "
          "de la regla queda sin contrastar en esta corrida")

op.ALMACEN_POR_WORKSPACE.clear()
op.ALMACEN_POR_WORKSPACE.update(_previo)
shutil.rmtree(_TMP, ignore_errors=True)

print()
if _FALLOS:
    print("ROJO — " + " · ".join(_FALLOS))
    raise SystemExit(1)
print("VERDE — el lector lee el almacén que el stack ya escribía, y el puente lo cruza.")
print("        Lo que NO dice: que el tutor PRODUZCA uno en un turno vivo. Eso pide la .app.")
