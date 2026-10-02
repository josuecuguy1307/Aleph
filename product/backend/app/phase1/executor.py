"""
executor.py — RUN-EXECUTOR: corre un puppet END-TO-END por el path de PROD.

Esta es la PIEZA QUE FALTABA del executor (Fase 2 · Integración). No reinventa
nada: GLUEa las piezas ya construidas en Fundación en el orden mandado por la misión:

    receta (anidada, validada por recipe_validator)
      → assembler resuelve belt_ref → .mcp.json (belt_resolver)
      → build_enforced_gate(recipe) EN EL PATH (enforcer obligatorio, §3.5)
      → modelo OSS opera el belt en una tarea real del nicho
      → persistir el run + instrumentation_logs (los 5 campos ligados por run_id)
        en Postgres
      → observable/servido en :8080 (vía el endpoint del router phase1).

Cómo encajan las piezas heredadas:
  - platform/assembler/recipe_assembler.assemble_and_run  → corre el loop OSS-first
    con el ENFORCER YA cableado en el path (gate.evaluate antes de cada tool-call;
    money/send forzados a needs_ok). Devuelve un RUN RECORD estructurado (evidencia,
    no un ✓ pelado): model_route, tools_cabled, tool_calls, gate_decisions, etc.
  - app.phase1.repo  → crea el run (runs) y lo cierra (finish_run) en Postgres.
  - app.phase1.instrumentation  → escribe LA fila del moat (instrumentation_logs)
    ligando por run_id los 5 campos: intent · belt · trayectoria · señal · costo.

FUENTE de la trayectoria (campo 3): el RUN RECORD del assembler, que YA es la
secuencia estructurada de model_calls (model_route) + tool_calls (con gate_decision).
No re-instrumentamos el loop ni inventamos latencias: lo que el assembler reportó es
lo que se persiste. Si un dato no está (p.ej. latencia por turno hoy no se emite),
queda None — honesto, no inventado.

BYOK por referencia: el resolver de keys.<p>.byok_ref se inyecta (mismo contrato que
el assembler). El cleartext nunca se loguea ni se persiste.

API:
  build_trajectory_from_record(record) -> list[dict]   # run record → campo (3)
  run_puppet_e2e(...) -> dict                           # el run E2E completo + persistencia
"""

from __future__ import annotations

import importlib.util
import json
import mimetypes
import os
import shutil
import sys
import threading
import time
import uuid as _uuid
from pathlib import Path
from typing import Any, Callable, Optional

from app.phase1 import repo as phase1_repo
from app.phase1 import instrumentation as instr
from app.phase1 import knowledge_store   # STEP 2·C1 (PIVOT) · storage abstraction del corpus RAG
from app.phase1.memory_recall import (select_relevant_memories, EPISODIC_TOPK,  # ORDEN 3 · recall relevante
                                      apply_inheritance)                        # ORDEN 4 · herencia
from app.phase1.explicit_memory import (   # PIEZA 1/2 · captura + olvido/corrección explícitos
    detect_capture as _detect_capture,
    detect_forget as _detect_forget,
    detect_correction as _detect_correction,
)

try:
    import aleph_paths as _ap
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

# Recursos inmutables viajan bajo resource_root(); outputs mutables viven en data_root().
_RESOURCE_ROOT = _ap.resource_root()
_ASSEMBLER_DIR = _RESOURCE_ROOT / "platform" / "assembler"
_tool_result_mod = _ap.load_module_by_path(
    "puppet_tool_result", _ASSEMBLER_DIR / "tool_result.py")
es_error_de_tool = _tool_result_mod.es_error_de_tool

def _cargar_turnos_obra():
    """[Gate 4 · F5 · 5.2] EL REGISTRO DE OBRAS EN VUELO, **UNO SOLO**.

    ⚠️ SE BUSCA PRIMERO EN `sys.modules`, y no es prolijidad — es la condición de que esta
    obra funcione. El registro TIENE ESTADO (la tabla de obras vivas, la marca de las
    detenidas, el handle del hilo) y `load_module_by_path` **crea un módulo NUEVO cada vez
    que se lo llama**: cargarlo por ruta cuando el assembler ya hizo su `import
    turnos_obra` daría DOS registros, el executor marcaría el corte en uno y el motor
    preguntaría en el otro. `fue_detenido()` contestaría que no PARA SIEMPRE y el botón de
    parar volvería a ser decorativo — el bug exacto que esta obra vino a cerrar, pero esta
    vez invisible y con la vara en verde.

    Es el mismo fallo que `recipe_assembler._dueno()` documenta para el dueño de procesos
    (dos tablas, cada una creyendo que las conexiones de la otra no existen). Acá se cierra
    igual: gana el que ya esté vivo, y si lo cargamos nosotros lo dejamos en `sys.modules`
    para que el `import turnos_obra` del assembler encuentre ÉSTE.
    """
    m = sys.modules.get("turnos_obra")
    if m is not None:
        return m
    m = _ap.load_module_by_path("turnos_obra", _ASSEMBLER_DIR / "turnos_obra.py")
    sys.modules["turnos_obra"] = m
    return m


_turnos_obra = _cargar_turnos_obra()

# PUPPET_BELTS = <root>/product/belts — BELTS-ROOT ÚNICO para TODOS los belts (decisión T7).
# Tanto programación como cowork viven AHORA bajo este root, y cada belt referencia su server
# relativo a él:  programación → ${PUPPET_BELTS}/gaps/script_runner_mcp.py ·
#                 cowork       → ${PUPPET_BELTS}/cowork/gmail_draft_server.py.
# (El server cowork se movió a product/belts/cowork/ para unificar la base.) Sin esto, el
# assembler defaultea PUPPET_BELTS=repo_root y el sandbox de programación NO bootea por HTTP.
# setdefault: un export explícito del operador SIEMPRE gana.
os.environ.setdefault("PUPPET_BELTS", str(_RESOURCE_ROOT / "product" / "belts"))

# OUTPUT DIR ESTABLE POR RUN: la obra en archivos vive acá, ligada al run_id, para que
# persista (no en un tempdir efímero del SO) y el endpoint de descarga la pueda servir.
# El download endpoint del router SOLO sirve archivos bajo esta raíz (guard anti-traversal).
_RUN_OUTPUTS_ROOT = _ap.data_root() / "run_outputs"

# MIME por extensión para la obra (lo que Biblioteca muestra / el browser baja). mimetypes
# no conoce los OOXML modernos en todas las plataformas, así que los fijamos explícitos.
_EXT_MIME = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".json": "application/json",
    ".txt": "text/plain",
}


def _guess_mime(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in _EXT_MIME:
        return _EXT_MIME[ext]
    guessed, _ = mimetypes.guess_type(str(p))
    return guessed or "application/octet-stream"


#: [T2.5c] La subcarpeta del workdir donde se copian los ADJUNTOS del usuario. Se declara
#: acá porque la usan las dos mitades —quien copia y quien captura— y dos literales iguales
#: en dos archivos es cómo empieza una divergencia que nadie ve.
ADJUNTOS_DIR = "adjuntos"


#: EL CANDADO DEL HILO. Uno por conversación, creado al vuelo y sostenido en memoria del
#: proceso — el mismo alcance que el dueño de los MCP, que es quien lo necesita.
_CANDADOS_HILO: dict = {}
_CANDADOS_LOCK = threading.Lock()

#: Cuánto espera un turno a que termine el anterior DE SU MISMO HILO. No es un timeout de
#: modelo: es cuánto vale la pena esperar para poder COMPARTIR el workdir. Pasado esto, el
#: turno no se cae ni se rechaza — corre con carpeta propia (ver `_carpeta_del_turno`), que
#: es exactamente el comportamiento que este producto tuvo siempre.
_ESPERA_HILO_S = float(os.environ.get("ALEPH_ESPERA_HILO_S", "90") or "90")


def _candado_del_hilo(chat_id: Optional[str]):
    """El candado de ESTA conversación, o `None` si el turno no pertenece a ninguna."""
    cid = str(chat_id or "").strip()
    if not cid:
        return None
    with _CANDADOS_LOCK:
        c = _CANDADOS_HILO.get(cid)
        if c is None:
            c = _CANDADOS_HILO[cid] = threading.Lock()
        return c


def _carpeta_del_turno(chat_id: Optional[str], space_id: Optional[str], run_id: str) -> str:
    """La carpeta de trabajo del turno: DEL ESPACIO cuando hay espacio, del run si no.

    POR QUÉ COMPARTIDA (decisión del dueño). Los cuatro servers que dependen de este dir
    —`filesystem` (allow-list), `sqlite` (`--db-path`), `pysandbox`, `officecli`— entran a
    la huella del dueño con la ruta YA EXPANDIDA. Con un `mkdtemp` por run la huella
    cambiaba en cada turno, así que el dueño no podía reusar NINGUNO: medido, 4 de 8 piezas
    se re-spawneaban y el restore quedaba en 3.248-4.046 ms porque el restore es paralelo y
    el reloj lo pone la más lenta. Con la ruta estable la huella se estabiliza y el reuso
    empieza a existir.

    EL AISLAMIENTO QUE SE CONSERVA ES ENTRE ESPACIOS, no entre turnos: adentro de un
    espacio, que el turno 5 vea lo que escribió el turno 3 es lo esperado — es la misma
    conversación. Entre espacios y entre workspaces la carpeta sigue siendo distinta.

    ⚠️ EL NOMBRE SE SANEA, y no es prolijidad: este string arma una RUTA. Un `space_id`
    con `/` o `..` escribiría fuera de `run_outputs` — y de paso le abriría al server
    `filesystem` una allow-list en cualquier lado del disco. Mismo criterio que
    `centro_modelos._slug_de_owner`: lo que no tiene forma de id no arma ruta, y ante la
    duda se cae al `run_id`, que es un UUID nuestro y siempre es seguro.
    """
    # PRENDIDO POR DEFAULT desde que existe el candado del hilo. La razón por la que estuvo
    # apagado —dos turnos del mismo hilo podían solaparse y re-cosechar el mismo archivo—
    # la cierra `_candado_del_hilo`: quien no consigue el candado NO comparte carpeta, así
    # que el caso peligroso ya no puede darse. `ALEPH_WORKDIR_ESPACIO=off` lo apaga.
    if (os.environ.get("ALEPH_WORKDIR_ESPACIO") or "on").strip().lower() not in ("on", "1", "true"):
        # ⚠️ APAGADO POR DEFAULT, Y LA RAZÓN NO ES TIMIDEZ. Compartir el dir sólo es seguro
        # si dos turnos del MISMO espacio no se solapan, y HOY SÍ PUEDEN: la ley del
        # composer está escrita en `router.py` («NADA de esto bloquea el envío»,
        # FIX-P10 §1b) y `turnos_obra.abrir()` es un registro para PARAR turnos —un
        # `setdefault`—, no un mutex. Con dir por run eso no molesta a nadie; con dir
        # compartido, un archivo que el turno A escribe mientras B corre entra en la
        # cosecha de los DOS y aparece duplicado y mal atribuido en la Biblioteca.
        # El lado MCP sí está cubierto (`_Conexion.lock_llamada` serializa por conexión).
        # Prender esto es una decisión del dueño sobre la concurrencia, no del código.
        return str(run_id)
    #: ⚠️ EL CHAT PRIMERO, Y ESTO COSTÓ UN BUILD. La primera versión usó `space_id` —lo que
    #: decía el encargo— y las carpetas salieron `espacio-space-mtcc76zj-1`,
    #: `…-mtcc7so7-3`, `…-mtcc8kts-5`: UNA POR TURNO. Medido contra la DB: los tres runs
    #: tenían `space_id` distinto y el MISMO `chat_id` (`fbfd8d59…`). El espacio identifica
    #: el TURNO; la conversación es el chat. Con la identidad equivocada la huella seguía
    #: cambiando y el reuso no existía — la carpeta era estable para nadie.
    sid = str(chat_id or space_id or "").strip()
    if (sid and len(sid) <= 120
            and all(c.isalnum() or c in "._-" for c in sid)
            and any(c.isalnum() for c in sid)
            and sid not in (".", "..")):
        return "hilo-" + sid
    return str(run_id)


def _capture_workdir_outputs(conn, run_id: str, workdir: str,
                             *, desde: Optional[float] = None) -> list[dict]:
    """Escanea el output dir del run y captura cada archivo PRODUCIDO como output
    kind=file (uri=ruta absoluta, mime, bytes). Esto es la 'obra' descargable de
    Biblioteca. EL BUG QUE ARREGLA: antes el .xlsx quedaba en disco pero NUNCA se
    capturaba (solo se persistía la respuesta de texto), así que Biblioteca no tenía
    el archivo ni había de dónde descargarlo.

    Salta ocultos (.DS_Store, locks) y archivos de 0 bytes. Un fallo persistiendo un
    archivo no tumba los demás ni el run. Devuelve la lista de lo capturado (evidencia)."""
    captured: list[dict] = []
    root = Path(workdir)
    if not root.exists():
        return captured
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        # [T2.5c] LO QUE EL USUARIO SUBIÓ NO ES UNA OBRA DEL AGENTE. Sin esta línea, el PDF
        # que alguien adjuntó para preguntar por él aparecería en su Biblioteca como si el
        # turno lo hubiera producido — y encima duplicado en cada turno que lo relea.
        try:
            if p.relative_to(root).parts[:1] == (ADJUNTOS_DIR,):
                continue
        except ValueError:
            pass
        try:
            st = p.stat()
            size = st.st_size
        except OSError:
            continue
        if size == 0:
            continue
        # [workdir por espacio] SOLO LO QUE ESTE TURNO TOCÓ. El dir lo comparten todos los
        # turnos del espacio, así que sin esto el .xlsx del turno 3 volvería a capturarse
        # como obra del turno 5 — el mismo archivo, una vez por turno, en la Biblioteca.
        # `desde=None` conserva el barrido completo de siempre (el camino sin espacio).
        if desde is not None and st.st_mtime < desde:
            continue
        mime = _guess_mime(p)
        try:
            row = phase1_repo.create_output(
                conn, run_id=run_id, kind="file", mime=mime,
                uri=str(p.resolve()), bytes_=size,
            )
            captured.append({
                "output_id": (row or {}).get("id"),
                "name": p.name, "bytes": size, "mime": mime,
            })
        except Exception:
            continue
    return captured


# ── EL VOCABULARIO ÚNICO · consumidor 4/4 [Gate 4 · Fase 2 · obra 2.3] ────────
# Acá vivía la 4ª lista del censo §C.3: diez sufijos de archivo escritos a mano, en
# cascada. QUÉ tipos se capturan lo dice ahora `rich_capture` del vocabulario (que
# desde 2.3 GOBIERNA); lo que queda de este lado es lo que SÍ es del executor: la
# FORMA que cada contenido debe tener y en qué ORDEN se busca.

#: La forma exigida por tipo (fail-closed: shape inválida = ese archivo no cuenta).
#: Espejo del contrato que leen los renderers y que la Sala valida en RICH_SHAPES.
_RICH_VALIDATORS: dict = {
    "convergence": lambda o: isinstance(o.get("iterations"), list) and bool(o["iterations"]),
    "fieldplot":   lambda o: isinstance(o.get("grid"), dict),
    "linechart":   lambda o: (isinstance(o.get("labels"), list) and bool(o["labels"])
                              and isinstance(o.get("series"), list) and bool(o["series"])),
    "planilla":    lambda o: isinstance(o.get("rows"), list) and bool(o["rows"]),
    "cad":         lambda o: isinstance(o.get("content"), str) and bool(o["content"].strip()),
    "volume3d":    lambda o: (isinstance(o.get("vertices_b64"), str)
                              and isinstance(o.get("faces_b64"), str)),
    "imagen":      lambda o: isinstance(o.get("content"), str) and bool(o["content"]),
    "galeria":     lambda o: (isinstance(o.get("images"), list) and bool(o["images"])
                              and all(isinstance(im, dict) and (im.get("content") or im.get("url"))
                                      for im in o["images"])),
    "dicom":       lambda o: bool(
        (isinstance(o.get("image"), str) and o["image"].strip())
        or (isinstance(o.get("url"), str) and o["url"].strip())
        or (isinstance(o.get("pixels"), dict) and o["pixels"].get("data")
            and o["pixels"].get("width") and o["pixels"].get("height"))),
    "schematic":   lambda o: bool(
        (isinstance(o.get("content"), str) and o["content"].strip())
        or (isinstance(o.get("url"), str) and o["url"].strip())),
}

#: PRIORIDAD de barrido — decisión del executor, no del vocabulario: el loop entero
#: (convergence) gana a cualquier cuadro suelto. Un tipo que el vocabulario marque
#: `rich_capture` y esta tupla no nombre se barre AL FINAL, en orden de declaración:
#: nunca se cae del barrido en silencio.
_RICH_PRIORITY = ("convergence", "fieldplot", "linechart", "planilla", "cad",
                  "volume3d", "imagen", "galeria", "dicom", "schematic")

#: Dónde vive el archivo de cada tipo. Default: `*.<tipo>.json` recursivo. La
#: excepción es convergence, que el productor escribe con nombre fijo en la raíz.
_RICH_FIXED_FILE = {"convergence": "convergence.json"}

_rich_warned: set = set()


def _rich_scan_order() -> list:
    """Los tipos de captura rica, en orden de barrido. Del vocabulario; si no está
    alcanzable, la prioridad declarada acá con log VISIBLE (jamás mudo)."""
    try:
        from artifacts import vocabulary            # platform/ ya está en sys.path
        rich = list(vocabulary.rich_capture_types())
    except Exception:                               # pragma: no cover
        if "vocab" not in _rich_warned:
            _rich_warned.add("vocab")
            print("[executor] EL vocabulario (platform/artifacts) no está disponible: "
                  "la captura rica cae a su prioridad declarada.", file=sys.stderr)
        return list(_RICH_PRIORITY)
    ordered = [t for t in _RICH_PRIORITY if t in rich]
    ordered += [t for t in rich if t not in _RICH_PRIORITY]
    return ordered


def _capture_rich_obra(workdir: str, *, desde: Optional[float] = None) -> Optional[dict]:
    """OBRA RICA: si el run escribió un artifact estructurado en su workdir, lo devuelve
    para surfacearlo como out["obra"] y que La Sala lo rinda con su renderer (no una
    descarga cruda). Los tipos y el orden salen de `_rich_scan_order()`; el archivo,
    de `_RICH_FIXED_FILE` o del patrón `*.<tipo>.json`; la forma, de `_RICH_VALIDATORS`.
    ADITIVO + fail-closed: solo dispara si el archivo existe, parsea, DECLARA su propio
    tipo y cumple la forma; jamás toca runs que no lo producen. None si no hay obra rica."""
    root = Path(workdir)
    try:
        for t in _rich_scan_order():
            check = _RICH_VALIDATORS.get(t)
            if check is None:
                # El vocabulario declara un tipo rico que este productor no sabe
                # validar. No se adivina la forma: se dice y se sigue (una vez).
                if t not in _rich_warned:
                    _rich_warned.add(t)
                    print("[executor] captura rica: el vocabulario declara '%s' y no hay "
                          "validador de forma para ese tipo — no se captura." % t,
                          file=sys.stderr)
                continue
            fixed = _RICH_FIXED_FILE.get(t)
            paths = [root / fixed] if fixed else sorted(root.rglob("*.%s.json" % t))
            for p in paths:
                if fixed and not p.exists():
                    continue
                # [workdir por espacio] SOLO LA OBRA DE ESTE TURNO. El dir es del espacio:
                # sin esto, la obra rica que escribió el turno 3 se volvería a surfacear en
                # el turno 5 como si la acabara de producir. `desde=None` = como siempre.
                if desde is not None:
                    try:
                        if p.stat().st_mtime < desde:
                            continue
                    except OSError:
                        continue
                o = json.loads(p.read_text())
                if isinstance(o, dict) and o.get("type") == t and check(o):
                    return o
    except Exception:
        return None
    return None


# ── GUARD DE TAMAÑO de la obra rica embebida inline (ticket B3/IN4) ──────────────
# _capture_rich_obra embebe el JSON parseado en out["obra"] para que La Sala lo rinda inline.
# Un artefacto grande (p.ej. un fieldplot 512×1682 ≈ 7.9 MB) NO debe TUMBAR el run ni inflar la
# respuesta/SSE/DB. Cap server-side: si excede, downsampleamos las grillas o devolvemos un
# placeholder liviano — la obra COMPLETA queda igual descargable en Biblioteca (kind=file, que NO
# embebe contenido). Env-configurable; default ~4 MB.
_MAX_OBRA_BYTES = int(os.environ.get("PUPPET_MAX_OBRA_BYTES", "") or 0) or 4_000_000


def _downsample_fieldplot(o: dict) -> Optional[dict]:
    """Subsamplea una grilla fieldplot (values flat row-major, len nx*ny) por stride para que
    entre en el cap, preservando forma (min/max/unit). None si no reconoce el shape (→ placeholder)."""
    try:
        import math
        g = o.get("grid") or {}
        nx, ny, vals = int(g.get("nx") or 0), int(g.get("ny") or 0), g.get("values")
        if not (isinstance(vals, list) and nx > 0 and ny > 0 and len(vals) == nx * ny):
            return None
        target = 20000  # puntos objetivo — sobra para el render de La Sala, entra holgado en el cap
        if nx * ny <= target:
            return None  # no es la grilla la que infla; que caiga al placeholder
        stride = max(2, int(math.ceil(math.sqrt((nx * ny) / target))))
        new_vals: list = []
        for yy in range(0, ny, stride):
            row = vals[yy * nx:yy * nx + nx]
            new_vals.extend(row[::stride])
        nnx = len(range(0, nx, stride))
        nny = len(range(0, ny, stride))
        ng = dict(g); ng["nx"], ng["ny"], ng["values"] = nnx, nny, new_vals
        no = dict(o); no["grid"] = ng
        no["_downsampled"] = {"from": [nx, ny], "to": [nnx, nny], "stride": stride}
        return no
    except Exception:
        return None


def _cap_obra(o):
    """Aplica el cap de tamaño a la obra rica. Devuelve o (si entra), una versión downsampleada
    (grillas), o un placeholder liviano honesto. ADITIVO + fail-safe: ante cualquier error, deja
    pasar `o` tal cual (nunca peor que el comportamiento previo)."""
    if not isinstance(o, dict):
        return o
    try:
        raw = json.dumps(o, ensure_ascii=False).encode("utf-8")
    except Exception:
        return o
    if len(raw) <= _MAX_OBRA_BYTES:
        return o
    if o.get("type") == "fieldplot":
        ds = _downsample_fieldplot(o)
        if ds is not None:
            try:
                if len(json.dumps(ds, ensure_ascii=False).encode("utf-8")) <= _MAX_OBRA_BYTES:
                    return ds
            except Exception:
                pass
    return {"type": o.get("type", "obra"), "oversized": True, "bytes": len(raw),
            "note": ("La obra quedó demasiado grande para mostrarse aquí; está guardada y "
                     "descargable en tu Biblioteca.")}


def _load_recipe_assembler():
    """Carga platform/assembler/recipe_assembler.py por ruta (el backend no asume
    que platform sea un paquete; mismo patrón que repo.py usa para db.py).

    recipe_assembler importa belt_resolver y carga assembler.py por ruta relativa al
    propio _ASSEMBLER_DIR, así que añadimos ese dir a sys.path para que sus imports
    de hermanos resuelvan."""
    if str(_ASSEMBLER_DIR) not in sys.path:
        sys.path.insert(0, str(_ASSEMBLER_DIR))
    return _ap.load_module_by_path(
        "puppet_recipe_assembler", _ASSEMBLER_DIR / "recipe_assembler.py")


# Carga perezosa única (importa el assembler — y por transitividad belt_resolver y
# recipe_enforcer — solo cuando se corre un run, no al importar el módulo).
_assembler = None


def _asm():
    global _assembler
    if _assembler is None:
        _assembler = _load_recipe_assembler()
    return _assembler


# ── PIEZA MÉTODO · el ARNÉS (workflows) ────────────────────────────────────────

def _method_harness_mod():
    """Carga platform/assembler/method_harness.py (import normal por sys.path —
    el mismo dir que ya usa el assembler para sus hermanos)."""
    if str(_ASSEMBLER_DIR) not in sys.path:
        sys.path.insert(0, str(_ASSEMBLER_DIR))
    import method_harness as _mhm  # noqa: PLC0415
    return _mhm


def _build_method_harness(conn, *, spec: dict, method_id: Optional[str], run_id: str,
                          user_id: Optional[str], puppet_id: Optional[str],
                          space_id: Optional[str], recipe: dict, lang: str,
                          adjust: Optional[str], seed_state: Optional[dict] = None):
    """Construye el arnés YA CARGADO: fila durable en method_runs (estado externo,
    filosofía §1: el modelo NUNCA es dueño del estado) + control-plane/checkpoint
    cableados con CONEXIONES CORTAS propias — jamás la conn del run: un error en
    un closure no puede envenenar la txn (clase de bug HIGH del run zombie), y el
    poll lee lo que los endpoints commitearon desde otro request."""
    from app.phase1 import methods_repo as _mrepo
    _mhm = _method_harness_mod()

    def _control_pop() -> dict:
        """Lee+limpia el control-plane atómico (cierra la carrera read→clear)."""
        c = phase1_repo.get_conn()
        try:
            return _mrepo.pop_control(c, run_id)
        finally:
            c.close()

    def _persist(state: dict, status: str) -> None:
        c = phase1_repo.get_conn()
        try:
            _mrepo.update_method_run(c, run_id, state=state, status=status)
        finally:
            c.close()

    def _checkpoint_open(step: dict) -> Optional[str]:
        """La held SENTINELA del checkpoint (server='metodo'): reusa la card B4 y
        el approve-by-HTTP tal cual; approve_held_action la decide SIN ejecutar."""
        c = phase1_repo.get_conn()
        try:
            row = phase1_repo.create_held_action(
                c, run_id=run_id, user_id=user_id, recipe=recipe,
                server="metodo", tool="checkpoint",
                args={"step_id": step.get("id"), "step_text": step.get("text")},
                level="checkpoint",
                turn_text=(step.get("text") or "")[:400],
            )
            return str(row["id"])
        finally:
            c.close()

    def _checkpoint_poll(approval_id: str) -> Optional[str]:
        c = phase1_repo.get_conn()
        try:
            ha = phase1_repo.get_held_action(c, approval_id)
        finally:
            c.close()
        st = (ha or {}).get("status")
        if not ha or st == "held":
            return None
        return "rejected" if st == "rejected" else "approved"

    harness = _mhm.MethodHarness(
        spec, method_id=method_id, lang=lang, adjust=adjust,
        control_pop=_control_pop,
        persist=_persist, checkpoint_open=_checkpoint_open,
        checkpoint_poll=_checkpoint_poll,
        diagnose=_method_diagnose_factory(recipe, user_id),
        seed_state=seed_state,
    )
    _mrepo.create_method_run(conn, run_id=run_id, method_id=method_id,
                             user_id=user_id, puppet_id=puppet_id,
                             space_id=space_id, state=harness.state,
                             status="active")
    if method_id:
        _mrepo.touch_method_run(conn, method_id, user_id)
    return harness


def _method_checkpoint_control(conn, held: dict, approval_id: str, *, ok: bool) -> None:
    """Deja la decisión del checkpoint durable en method_runs.control (best-effort:
    un fallo acá jamás rompe el approve — el poll de la held ya alcanza en vivo)."""
    try:
        from app.phase1 import methods_repo as _mrepo
        args = held.get("args") or {}
        _mrepo.update_method_run(conn, str(held.get("run_id")),
                                 control_merge={"checkpoint": {
                                     "approval_id": approval_id, "ok": ok,
                                     "step_id": args.get("step_id")}})
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _method_diagnose_factory(recipe: dict, user_id: Optional[str]):
    """POLÍTICA DE FALLO §5 — diagnose(step, failures, lang) → {diagnosis, remedies}.

    Compone las señales read-only que el recon mapeó (ninguna estaba unificada):
      · texto del result del run ('[MCP error…]' = transporte caído; 401/403/auth
        en el texto = credencial) — a run-time la credencial faltante es MUDA
        (el broker devuelve '' y el server no arranca), por eso se CRUZA con
      · el VAULT del dueño (classify_key_providers: partial ANTES que connected —
        un provider parcial caduca ~1h), y
      · el BELT de la receta (executor-hint que no matchea ningún server cableado
        = capacidad no conectada → conectar MCP).
    remedies.suggested ∈ reconnect | connect_mcp | retry (cure viaja cuando aplique
    vía el endpoint remedy). Sin señal clara → retry honesto. Nunca lanza."""
    servers = set()
    try:
        belt = recipe.get("belt") or {}
        servers = {str(s).lower() for s in (belt.get("tool_filters") or {}).keys()}
    except Exception:
        servers = set()

    def _vault_state():
        connected, partial = set(), set()
        if not user_id:
            return connected, partial
        c = None
        try:
            c = phase1_repo.get_conn()
            keys = phase1_repo.list_keys(c, user_id)
            providers = [k.get("provider", "") for k in keys]
            connected, partial = phase1_repo.classify_key_providers(providers)
        except Exception:
            pass
        finally:
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
        return connected, partial

    def diagnose(step: dict, failures: list, lang: str) -> dict:
        es = (lang or "es") != "en"
        hint = str(step.get("executor") or "").strip().lower()
        fail_text = " ".join(str(f.get("result") or "") for f in (failures or []))[:600]

        # (3) capacidad NO conectada: el paso pide algo que el belt no tiene
        if hint and servers and not any(hint in s or s in hint for s in servers):
            return {
                "diagnosis": ((f"El paso pide «{step.get('executor')}» pero esa capacidad "
                               "no está conectada al agente.") if es else
                              (f"The step asks for “{step.get('executor')}” but that "
                               "capability is not connected to the agent.")),
                "remedies": {"suggested": "connect_mcp",
                             "suggested_label": "Conectar la capacidad" if es
                             else "Connect the capability"},
            }

        # (2) credencial: 401/403/auth en el texto del fallo, o provider PARCIAL en el vault
        low = fail_text.lower()
        _connected, partial = _vault_state()
        cred_signal = any(t in low for t in ("401", "403", "unauthorized", "forbidden",
                                             "auth", "credencial", "api key", "api_key"))
        partial_hit = hint and any(hint in p or p in hint for p in partial)
        if cred_signal or partial_hit:
            why = (("la credencial está parcial y caduca pronto" if partial_hit
                    else "el servicio rechazó la autenticación") if es else
                   ("the credential is partial and expires soon" if partial_hit
                    else "the service rejected authentication"))
            return {
                "diagnosis": ((f"Credencial faltante o vencida: {why}." if es
                               else f"Missing or expired credential: {why}.")
                              + (f" [{fail_text[:160]}]" if fail_text else "")),
                "remedies": {"suggested": "reconnect",
                             "suggested_label": "Reconectar la credencial" if es
                             else "Reconnect the credential"},
            }

        # (1) MCP caído: fallo duro de transporte en el texto real del run
        if "[mcp error" in low or "no response" in low:
            return {
                "diagnosis": ((f"El MCP no responde: {fail_text[:200]}") if es
                              else f"The MCP is not responding: {fail_text[:200]}"),
                "remedies": {"suggested": "retry",
                             "suggested_label": "Reintentar" if es else "Retry"},
            }
        if fail_text:
            return {
                "diagnosis": ((f"La herramienta falló: {fail_text[:200]}") if es
                              else f"The tool failed: {fail_text[:200]}"),
                "remedies": {"suggested": "retry",
                             "suggested_label": "Reintentar" if es else "Retry"},
            }
        return {
            "diagnosis": (("El paso no produjo evidencia real (ninguna tool ejecutada "
                           "con resultado).") if es else
                          "The step produced no real evidence (no tool executed with a result)."),
            "remedies": {"suggested": "retry",
                         "suggested_label": "Reintentar" if es else "Retry"},
        }

    return diagnose


# ── TRAYECTORIA: del RUN RECORD del assembler al campo (3) ─────────────────────

def build_trajectory_from_record(record: dict) -> list[dict]:
    """
    Reconstruye el campo (3) trayectoria a partir del RUN RECORD que devuelve
    assemble_and_run. El run record ES la fuente estructurada: model_route (cada
    decisión de routing = un model_call) + tool_calls (cada uno con su gate_action).

    Forma de cada paso (alineada con schema.sql §7 / instrumentation.build_trayectoria):
      {seq, kind:'model_call'|'tool_call', name, latency_ms, error}
    Para tool_call agregamos gate_decision y, si falló, la CausaCostura del
    assembler (causa/origen/reintentable/reloj) junto al string histórico.

    Honestidad: `latency_ms` sale de `wall_s` cuando el paso lo trae (`:570`), y queda
    `None` cuando no. No se inventan números — el moat se alimenta de lo que REALMENTE
    pasó, y «no lo sé» se dice con `None`, jamás con un cero.

    [GATE 3 · fase 3 · G-10(b)] Acá decía «latency_ms queda None» a secas, y cuarenta
    líneas más abajo se calcula desde `wall_s`. La auditoría 4 lo anotó como una de las
    tres citas podridas: el docstring quedó en el contrato anterior a que `wall_s`
    existiera. Se corrige acá porque es el docstring de esta misma función; el resto de
    G-10 queda declarado en el reporte.
    """
    steps: list[dict] = []
    seq = 0

    # (a) model_calls — uno por decisión de routing (primary/fallback). El error del
    #     model_call se deriva de ok=False en la decisión (gateway/transport falló).
    for dec in record.get("model_route", []) or []:
        seq += 1
        ok = dec.get("ok", True)
        steps.append({
            "seq": seq,
            "kind": "model_call",
            "name": dec.get("model") or "chat.completions",
            "latency_ms": None,   # el assembler no emite latencia por turno hoy (honesto)
            "error": None if ok else (dec.get("error") or "model_call_failed"),
            "tier": dec.get("tier"),
        })

    # (b) tool_calls — uno por llamada a herramienta, con su decisión de gate. El error
    #     se deriva del gate (no se ejecutó: needs_ok/blocked) o del resultado del tool.
    for tc in record.get("tool_calls", []) or []:
        seq += 1
        gate_action = (tc.get("gate_decision") if tc.get("gate_decision") is not None
                       else tc.get("gate_action"))
        result = tc.get("result") or ""
        # [GATE 3 · obra 5] UNA ACCIÓN RETENIDA NO ES UN ERROR: ES PROTECCIÓN (acta de persona usuaria,
        # 2026-08-06). Antes se registraba `error="gate:needs_ok"` y el moat contaba el freno
        # del gate como una falla del run — o sea, contaba la seguridad como un defecto. La
        # retención se firma en `retenida`, que es aditivo y no obliga a parsear un string.
        # MISMO CRITERIO, PALABRA POR PALABRA, que `instrumentation.build_trayectoria`: eran
        # los dos constructores vivos con distinta corrección (auditoría 4 §G-7), y el mismo
        # run podía quedar registrado de dos formas según por dónde entró.
        retenida = gate_action in instr.GATE_RETIENE
        error: Optional[str] = None
        if not retenida and es_error_de_tool(result):
            error = result[:200]
        wall_s = tc.get("wall_s")
        latency_ms = (wall_s * 1000 if isinstance(wall_s, (int, float))
                      and not isinstance(wall_s, bool) else None)
        step = {
            "seq": seq,
            "kind": "tool_call",
            "name": tc.get("tool"),
            "latency_ms": latency_ms,
            "error": error,
            "gate_decision": gate_action,
            "retenida": retenida,
        }
        for key in ("causa", "origen", "reintentable", "timeout_s",
                    "vencio_el_reloj", "detalle"):
            if key in tc:
                step[key] = tc[key]
        steps.append(step)
    return steps


def _build_cost_from_record(record: dict) -> dict:
    """
    Campo (5) costo — COSTO REAL por run, tokens MEDIDOS del response del proveedor.

    El loop del assembler ahora acumula el campo `usage` que Groq/OpenAI-compat devuelve
    en CADA respuesta de chat/completions (record["usage"] = {prompt_tokens, completion_tokens,
    total_tokens, calls, calls_no_usage}). Pasamos esos tokens REALES a build_cost, que
    además computa el USD del run a la tarifa publicada del proveedor (constante documentada
    en instrumentation.py; lo medido es el token, el precio es la constante).

    Honestidad: `tokens_instrumented=True` solo si AL MENOS una llamada trajo usage. Si
    NINGUNA lo trajo (p.ej. todo el run cayó al OSS-directo ollama que omite usage), queda
    False y el conteo es 0 — no inventamos. `calls`/`calls_no_usage` quedan en el costo para
    que el flywheel sepa cuántas llamadas se midieron y cuántas no.
    """
    by_model: dict[str, Any] = {}
    for dec in record.get("model_route", []) or []:
        m = dec.get("model")
        if not m:
            continue
        by_model.setdefault(m, {"turns": 0, "tier": dec.get("tier")})
        by_model[m]["turns"] += 1

    usage = record.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    calls_with_usage = int(usage.get("calls", 0) or 0)
    calls_no_usage = int(usage.get("calls_no_usage", 0) or 0)

    cost = instr.build_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        by_model=by_model or None,
        model_final=record.get("model_final"),
    )
    # tokens_instrumented = True solo si el proveedor REALMENTE reportó tokens en ≥1 llamada.
    cost["tokens_instrumented"] = calls_with_usage > 0
    cost["calls_measured"] = calls_with_usage
    cost["calls_unmeasured"] = calls_no_usage
    return cost


# ── TERMINAL HONESTO POR SSE/EVENTS (Gap #3) ────────────────────────────────────
# El run async surface su progreso por el stream del espacio (tool_call_*, final). Pero
# el `final` del assembler solo lleva la respuesta — no el ESTADO honesto del run. Sin un
# evento terminal con {ok, model_final, run_id, error}, un cliente que mira SOLO el SSE no
# puede reportar honesto y termina dependiendo del POST bloqueante (el bug del Cuarto: 45s
# < ~55s del cerebro → abort). Este `run_done` + `closed` hace al stream AUTOSUFICIENTE:
# el cliente lee el veredicto real del run del propio stream y NO se cuelga esperando.
# Aditivo y a prueba de fallos: un error emitiendo NUNCA tumba el run.
def _emit_run_terminal(on_event: Optional[Callable[[dict], None]], out: dict) -> None:
    """Emite el TERMINAL del run por el stream del espacio: un `closed` ENRIQUECIDO con el
    veredicto honesto del run (ok, model_final, run_id, error, degraded, answer, …). `closed`
    es un tipo válido de EVENT_TYPES y es donde iter_sse_events CORTA limpio (en vez de
    esperar el idle-timeout) — así el stream cierra apenas el run termina. Garantía clave:
    se emite en el `finally` del executor, así que SALE EN TODOS LOS CAMINOS (éxito, gate
    fail-closed, legal-gate, excepción) — un run que falla también cierra el stream con su
    estado real, en vez de dejar al cliente colgado esperando un evento que no llega."""
    if on_event is None:
        return
    rec = out.get("record") or {}
    closed = {
        "type": "closed",
        "kind": "closed",
        "run_id": out.get("run_id"),
        "ok": bool(out.get("ok")),
        "model_final": rec.get("model_final"),
        "error": out.get("error"),
        # La causa tipada viaja junto al error crudo. La UI muestra la causa y reserva el
        # string técnico para detalles; nunca tiene que inferir una persona-copy desde JSON.
        "causa": rec.get("causa"),
        "degraded": out.get("degraded"),
        "answer": out.get("answer", "") or "",
        "turns": rec.get("turns"),
        "trajectory_steps": out.get("trajectory_steps"),
        "tools_cabled": rec.get("tools_cabled"),
        "instrumentation_log_id": out.get("instrumentation_log_id"),
        # STEP 2·B1 · held_actions viaja como OBJETOS (no approval_ids sueltos). El front (Cuarto)
        # DEBE poder distinguir una held PROPIA del padre de una hoisteada de un sub-agente
        # (via_delegation) y atarla a SU tarjeta por identidad — NUNCA por índice. Con el zip por
        # índice viejo, una held de dinero del hijo (que NO emite gate_waiting) le robaba el
        # approval_id a la tarjeta benigna del padre → el OK ejecutaba la acción EQUIVOCADA. Cada
        # held lleva su tool/server/via_delegation/agent_path + la ux del hijo (que el padre no
        # tiene de otra fuente). Espeja la forma de `out["held_actions"]` (el retorno directo del
        # motor, que los harnesses ya consumen como objetos).
        "held_actions": [
            {
                "approval_id": h.get("approval_id"),
                "server": h.get("server"),
                "tool": h.get("tool"),
                "level": h.get("level"),
                "via_delegation": bool(h.get("via_delegation")),
                "agent_path": h.get("agent_path"),
                "depth": h.get("depth"),
                "action_class": h.get("action_class"),
                "ux": h.get("ux"),
            }
            for h in (out.get("held_actions") or [])
        ],
    }
    # BYO-CLI (aditivo BYTE-IDÉNTICO, review LOW #24): solo agregamos las claves nuevas cuando
    # HAY un cerebro CLI — un run legacy sin brain_provider emite el `closed` idéntico a main.
    if rec.get("brain_provider"):
        closed["brain_provider"] = rec["brain_provider"]
    if rec.get("brain_window_exhausted"):
        closed["brain_window_exhausted"] = rec["brain_window_exhausted"]
    # [Gate 4 · F5 · 5.2] EL CORTE SE DICE EN EL TERMINAL, FIRMADO.
    # Sin esto, una obra parada llega al cliente como `ok:false` + `answer` vacío, o sea
    # indistinguible de una que falló — y el usuario vería un cartel rojo por su propia
    # decisión. `causa` es la del vocabulario sellado (`turno_detenido`, que la Sala ya
    # sabe pintar SIN alarma) y `corte` dice quién y dónde. Aditivo: un run que nadie paró
    # emite el `closed` byte-idéntico al de siempre.
    if out.get("cancelado"):
        closed["cancelado"] = True
        closed["causa"] = rec.get("causa")
        closed["corte"] = rec.get("corte")
    try:
        on_event(closed)
    except Exception:
        pass


# ── EL RUN E2E COMPLETO ─────────────────────────────────────────────────────────

# ── Step 2 · A3 · MEMORIA DEL AGENTE · helpers del write/read-path (server-side) ────
# Presupuesto DURO del bloque pineado que entra al framing (además del cap por-tier): que
# la memoria NUNCA domine el system prompt. El bloque real = min(esto, tier.max_bytes).
_A3_PINNED_BUDGET_BYTES = 4096


def _valid_uuid(s: Optional[str]) -> Optional[str]:
    """Devuelve el uuid canónico si `s` es un uuid válido, si no None. El puppet_id del
    Cuarto puede ser 'cuarto-<slug>' (agente SIN guardar) → esos NO keyean memoria ni se
    ligan al run (runs.puppet_id es uuid FK). Sólo un agente GUARDADO (uuid real) recuerda."""
    if not s:
        return None
    try:
        return str(_uuid.UUID(str(s)))
    except (ValueError, AttributeError, TypeError):
        return None


def _build_pinned_memory(memories: list, *, budget_bytes: int) -> str:
    """Arma el bloque COMPACTO de memoria (más-reciente-primero) acotado a budget_bytes.
    Grande → corta con marcador (el panel es el handle: artifacts-por-handle). Nunca crudo."""
    lines: list[str] = []
    used = 0
    shown = 0
    total = 0
    for m in memories:
        c = (m.get("content") or "").strip()
        if not c:
            continue
        total += 1
        line = "- " + c
        b = len(line.encode("utf-8")) + 1
        if used + b > budget_bytes:
            continue   # no cortamos el loop: quizás una entrada más chica todavía entra
        lines.append(line)
        used += b
        shown += 1
    block = "\n".join(lines)
    hidden = total - shown
    if hidden > 0:
        block += f"\n(+{hidden} recuerdo(s) más en tu panel de memoria)"
    return block


def _build_rag_block(hits: list, *, budget_bytes: int) -> str:
    """STEP 2·C1 · Arma el bloque COMPACTO de APUNTES recuperados (mejor-score-primero) acotado
    a budget_bytes. Cada fragmento lleva su PROCEDENCIA `[doc#chunk]` — así el agente (y el
    usuario) saben de QUÉ documento salió el material (evidencia honesta, no una cita inventada).
    Mismo presupuesto/compactado que A3 (_build_pinned_memory): NUNCA cruza el corpus entero al
    contexto — el panel de Conocimiento es el handle (artifacts-por-handle). `hits` = lista de
    (chunk_dict, score) de rag_index.top_k."""
    lines: list[str] = []
    used = 0
    shown = 0
    total = 0
    for ch, _score in hits:
        # STEP 2·C1 · Finding #3 (provenance spoof) — el cuerpo del chunk es CONTENIDO NO CONFIABLE
        # del usuario. Si trae saltos de línea INTERNOS, una línea suya tipo '\n[banco#0] ...' se
        # colaría como una PROCEDENCIA falsa cuando recipe_assembler._rag_wrap cuenta '^\[...\]' en
        # MULTILINE → n_chunks/provenance inflados/spoofeados. Colapsar TODO el whitespace (incl. \n)
        # garantiza EXACTAMENTE un tag [doc#ix] real por chunk (y de paso limpia el texto del modelo).
        c = " ".join((ch.get("content") or "").split())
        if not c:
            continue
        total += 1
        doc = (ch.get("doc_name") or "doc").strip() or "doc"
        ix = ch.get("chunk_ix")
        line = f"[{doc}#{ix}] {c}"
        b = len(line.encode("utf-8")) + 1
        if used + b > budget_bytes:
            continue   # no cortamos el loop: quizás un fragmento más chico todavía entra
        lines.append(line)
        used += b
        shown += 1
    block = "\n".join(lines)
    hidden = total - shown
    if hidden > 0:
        block += f"\n(+{hidden} fragmento(s) más en tu panel de Conocimiento)"
    return block


def _commit_before_external_io(conn: Any, stage: str) -> None:
    """Cierra cualquier transacción antes de cruzar un I/O externo.

    La auditoría de Sala confirmó que `create_run()` ya commitea antes del modelo y
    que el path normal no sostiene un writer SQLite durante esa llamada. Esta frontera
    explícita es el cinturón verificable contra una regresión futura en un repo helper.
    `stage` nombra la costura para tests/traces; no registra datos del turno.
    """
    del stage
    conn.commit()


try:
    from app.infra import observability as _obs
except Exception:                                        # noqa: BLE001
    class _obs:                                          # type: ignore[no-redef]
        @staticmethod
        def marca(*_a, **_k): pass


def run_puppet_e2e(
    recipe: dict,
    prompt: str,
    *,
    puppet_id: Optional[str] = None,
    user_id: Optional[str] = None,
    space_id: Optional[str] = None,
    chat_id: Optional[str] = None,   # LA CONVERSACIÓN (el espacio es del TURNO, no del hilo)
    conn: Optional[Any] = None,
    byok_resolver: Optional[Callable[[str], str]] = None,
    deadline_s: float = 180.0,
    approve: Optional[Callable[[str, str, dict], bool]] = None,
    base_matrix: Optional[dict] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    images: Optional[list] = None,
    lang: str = "es",
    history_text: Optional[str] = None,
    method_id: Optional[str] = None,       # PIEZA MÉTODO · el run corre dirigido por este método
    method_adjust: Optional[str] = None,   # PIEZA MÉTODO · ajuste del dueño SOLO para este run
    method_seed_state: Optional[dict] = None,  # PIEZA MÉTODO · continuación: estado durable previo
    client_tools: Optional[list] = None,   # [FIX-P9] tools que ejecuta la SUPERFICIE (no el motor)
    inbox_dir: Optional[str] = None,       # [T2.5c] los adjuntos PERSISTENTES de esta conversación
) -> dict:
    """
    Corre UN puppet end-to-end por el path de PROD y persiste el moat.

    Orden EXACTO (el de la misión):
      1) crea el run en Postgres (runs)            — repo.create_run
      2) assemble_and_run                           — belt_resolver + ENFORCER en el path
                                                       + loop OSS-first contra el belt real
      3) trayectoria desde el RUN RECORD            — build_trajectory_from_record
      4) persiste instrumentation_logs por run_id   — instrumentation.persist_run (EL MOAT)
      5) cierra el run (done/error)                 — repo.finish_run

    El ENFORCER DE GATES ESTÁ EN EL PATH: assemble_and_run construye el gate desde la
    receta vía build_enforced_gate ANTES de ejecutar cualquier tool. Si no se puede
    construir (faltan mandatorios), el run devuelve error gate fail-closed y NADA corre.

    `conn`: conexión psycopg2 a puppet_ai. Si no se provee, abre una corta y la cierra.
    Devuelve:
      {
        "run_id": str,                       # UUID del run persistido
        "instrumentation_log_id": int|None,  # id de la fila del moat
        "ok": bool,                          # éxito del loop
        "gate_enforced": bool,               # el gate se construyó y montó en el path
        "answer": str,
        "record": { ...run record del assembler... },  # evidencia completa
        "trajectory_steps": int,
        "error": str|None,
      }
    """
    # ══ [Gate 4 · F5 · 5.2] LA OBRA SE REGISTRA ANTES DE EMPEZAR ═════════════════════
    # El handle es el `space_id` — lo elige EL CLIENTE y ya viajó en el pedido, así que
    # existe antes que el `run_id`. Registrar acá (y no después de `create_run`) es lo que
    # permite parar un turno que todavía no arrancó: el usuario puede apretar ⏹ mientras el
    # POST viaja, y sin esto ese apretón no tendría a quién pararle nada.
    # Sin `space_id` (una vara, el CLI, un sub-agente) el handle es None y todo esto es
    # no-op: un run que nadie puede ver tampoco es un run que alguien pueda parar.
    _obs.marca("exec.entra")
    _handle = _turnos_obra.abrir(space_id)
    _turnos_obra.tomar(_handle)

    # ── UN TURNO POR HILO, PORQUE EL WORKDIR ES DEL HILO ──────────────────────────
    # `turnos_obra` NO sirve para esto: su handle es el `space_id`, que es del TURNO —
    # dos mensajes de la misma conversación traen espacios distintos (medido). Así que
    # el candado va por `chat_id`, que es la identidad que de verdad comparte carpeta.
    #
    # POR QUÉ HACE FALTA. La cosecha (`_capture_workdir_outputs`) barre el dir por
    # `mtime`: con dos turnos solapados, el archivo que escribe el primero cae dentro de
    # la ventana del segundo y entra en los DOS — duplicado y mal atribuido. El lado MCP
    # ya está cubierto (`_Conexion.lock_llamada` serializa por conexión); lo que faltaba
    # era esto.
    #
    # Y SI NO SE CONSIGUE, NO SE ROMPE NADA. Pasado `_ESPERA_HILO_S` el turno sigue, pero
    # con carpeta propia: pierde el reuso de los MCP y la vista compartida, que es
    # exactamente como funcionó este producto hasta ahora. Un candado que rechaza turnos
    # sería peor que el problema que viene a resolver.
    _candado = _candado_del_hilo(chat_id)
    _tengo_el_hilo = bool(_candado and _candado.acquire(timeout=_ESPERA_HILO_S))
    if _candado is not None and not _tengo_el_hilo:
        print("[executor] el hilo %s sigue ocupado tras %.0fs; este turno corre con "
              "carpeta propia (sin reuso de MCP)" % (str(chat_id)[:8], _ESPERA_HILO_S),
              file=sys.stderr, flush=True)

    own_conn = conn is None
    if own_conn:
        conn = phase1_repo.get_conn()

    intent = prompt
    run_row: Optional[dict] = None
    out: dict = {
        "run_id": None,
        "instrumentation_log_id": None,
        "ok": False,
        "gate_enforced": False,
        "answer": "",
        "record": None,
        "trajectory_steps": 0,
        "workdir": None,
        "outputs_captured": [],
        "error": None,
    }

    try:
        # BORRADO DE CUENTA (ticket 2 · review): guard de arranque. Un run de una cuenta en
        # soft-delete no arranca — cierra la ventana del job encolado que un worker toma DESPUÉS
        # del borrado (el path HTTP síncrono ya lo corta el middleware; esto cubre la cola durable).
        # No detiene un run YA en su loop (limitación inherente documentada), pero sí impide que
        # uno nuevo empiece a tocar credenciales tras el pedido de borrado.
        if user_id:
            try:
                _dstate = phase1_repo.user_deleted_state(conn, user_id)
            except Exception:
                _dstate = None
            if _dstate and _dstate.get("deleted_at"):
                out["error"] = "account_deleted"
                return out
        # [T9-safety] PRECHECK LEGAL POR NICHO (aditivo, encima del enforcer de gates).
        # El enforcer ya FUERZA money_touch/send a confirma-siempre — esto agrega lo que el
        # core no hace: BLOQUEO por entorno (medicina/HIPAA en prod) + exponer el aviso legal
        # y require_human del nicho (ingeniería human-in-loop, finanzas descargo). Solo puede
        # CORTAR o ANOTAR; nunca afloja. Si la capa no está, el run sigue (fail-open import).
        try:
            if str(_RESOURCE_ROOT / "platform") not in sys.path:
                sys.path.insert(0, str(_RESOURCE_ROOT / "platform"))
            from safety.guards import legal_precheck
            _legal = legal_precheck(recipe, env=os.environ.get("ALEPH_ENV"))
            out["legal"] = _legal
            if not _legal["allow"]:
                out["error"] = f"legal-gate: {_legal['reason']}"
                return out  # NO se crea run ni corre nada (ej. medicina en prod)
        except ImportError:
            pass

        # ── FRONTERA (Step 2 · A1) · TECHO DE TIER, resuelto ANTES de crear el run ────────
        # El techo (max_turns/max_tool_calls) del tier del usuario viaja al assembler como
        # _caps_ceiling y clampa TODO el árbol (top-level + hijos) en el choke point — una
        # receta editada (o un child_model 'own') NO puede subirlo. Se resuelve ACÁ, antes de
        # create_run, para que su SELECT quede en la MISMA transacción que create_run commitea
        # (evita dejar la conexión 'idle in transaction' TODO el run → timeout del pooler en
        # prod dejaría el run sin cerrar). Tier ausente/desconocido → free (el más restrictivo).
        _caps_ceiling = None
        _tier = None          # STEP 2·A2 · tier del dueño (para el aviso honesto si el bus degrada)
        _mem_ceiling = None   # STEP 2·A3 · techo de MEMORIA por-tier (entradas/bytes)
        _account_ceiling = None  # ORDEN 2 · Sistema 2 · techo de MEMORIA DE CUENTA por-tier
        _rag_ceiling = None   # STEP 2·C1 · techo de CORPUS por-tier (docs/bytes) — SÓLO metering
                              # en modo hosted; en self_hosted (default) es None (= sin cap) y la
                              # recuperación de abajo es FUNCIONAL y GRATIS igual (como A3, no B2).
        try:
            if str(_RESOURCE_ROOT / "platform") not in sys.path:
                sys.path.insert(0, str(_RESOURCE_ROOT / "platform"))
            from gates.recipe_enforcer import (runtime_caps_for_tier, memory_caps_for_tier,
                                               rag_caps_for_tier, account_memory_caps_for_tier)
            _tier = None
            if user_id:
                try:
                    _u = phase1_repo.get_user(conn, user_id)
                    _tier = (_u or {}).get("tier")
                except Exception:
                    try:
                        conn.rollback()   # no dejar la conexión envenenada para create_run
                    except Exception:
                        pass
            _caps_ceiling = runtime_caps_for_tier(_tier)
            _mem_ceiling = memory_caps_for_tier(_tier)
            _account_ceiling = account_memory_caps_for_tier(_tier)
            # _rag_ceiling se resuelve acá (misma txn/disciplina que los otros techos) pero la
            # LECTURA de RAG de más abajo NO lo consulta: la retrieval es gratis/funcional. El cap
            # sólo lo consume el UPLOAD (router) en modo hosted. self_hosted → None → no-op.
            _rag_ceiling = rag_caps_for_tier(_tier)
        except ImportError:
            # MURALLA · FAIL-CLOSED ante capa de seguridad rota (review adversarial premium-wall):
            # si gates.recipe_enforcer NO importa (deploy sesgado: el package-import de acá falla
            # aunque el assembler path-cargue el MISMO archivo), NO caer a None. None se lee como
            # PERMITIR en las superficies premium POR-CLAMP: _bus_on=True (bus B2 cableado a free),
            # techos de loop sin clamp (`if _caps_ceiling:`), y tier_max_parallel(None)=8. Eso sería
            # fail-OPEN. Caemos al piso FREE hardcodeado (no depende del import que falló), fiel a la
            # doctrina "tier ausente → el MÁS restrictivo" (== TIER_RUNTIME_CAPS['free']): shared_bus
            # False niega el bus, max_parallel 1 serializa, y los techos de loop clampan.
            _caps_ceiling = {"max_turns": 8, "max_tool_calls": 40, "max_parallel": 1, "shared_bus": False}
            _mem_ceiling = None   # sin capa gates → sin frontera de memoria → NO tocamos memoria (fail-safe A3)
            _account_ceiling = None  # idem: sin gates → sin frontera de cuenta → NO leemos cuenta (fail-safe)
            _rag_ceiling = None

        # ── ORDEN 2 · Sistema 2 · LECTURA de la MEMORIA DE CUENTA (read-path, cruza agentes) ──
        # A diferencia de A3 (gated por puppet GUARDADO+TUYO), la memoria de cuenta la lee CUALQUIER
        # run del dueño — inline, sin guardar, cualquier agente — porque son hechos sobre LA PERSONA,
        # no sobre un agente. Requiere sólo user_id (run autenticado) + la frontera de tier. Un run
        # ANÓNIMO (user_id=None) NO lee cuenta (misma disciplina que BYOK/billing). AISLAMIENTO: se
        # filtra ESTRICTO por owner_id=user_id → jamás la cuenta de otro. Fail-safe: nunca tumba el run.
        # TOGGLE "conoce tu cuenta" (ticket 4): por defecto SÍ. La receta puede apagarlo por-agente
        # con memory.account_read=false (átomo Contexto del Cuarto). Coerción robusta: SÓLO el
        # literal False apaga; ausente/None/basura ⇒ True (default = comportamiento de hoy).
        _acct_read = (recipe.get("memory") or {}).get("account_read", True)
        _acct_ok = _acct_read is not False
        account_pinned: Optional[str] = None
        if user_id and _account_ceiling is not None and not _acct_ok:
            # evidencia honesta: este agente NO conoce tu cuenta (toggle OFF). Sin este flag,
            # un run sin bloque de cuenta sería indistinguible de "no había nada que inyectar".
            out["account_read_disabled"] = True
        _obs.marca("exec.pre_memoria")
        if user_id and _account_ceiling is not None and _acct_ok:
            try:
                _abudget = min(_A3_PINNED_BUDGET_BYTES, int(_account_ceiling["max_bytes"]))
                _amems = phase1_repo.list_account_memories(conn, user_id, pinned_only=True)
                # ORDEN 3 · la cuenta se ORDENA por relevancia al pedido (si el byte-budget trunca,
                # sobrevive lo pertinente) pero NO se dropea: k=None conserva todo, always_kinds=()
                # porque los hechos de cuenta no llevan skill/episódica (el scope ES la categoría).
                _amems = select_relevant_memories(_amems, prompt, k=None, always_kinds=(),
                                                  always_sources=(), order="relevance",
                                                  drop_irrelevant=False)
                account_pinned = _build_pinned_memory(_amems, budget_bytes=_abudget) or None
            except Exception:
                account_pinned = None   # lectura falló → corré SIN memoria de cuenta (degrada suave)
                try:
                    conn.rollback()      # no dejar la txn envenenada para create_run
                except Exception:
                    pass

        # ── STEP 2·A3 · IDENTIDAD del agente + LECTURA de su memoria (write/read-path) ──
        # Sólo un agente GUARDADO que EXISTE y es TUYO (owner == user_id del run) recuerda entre
        # runs, y sólo ese liga runs.puppet_id. AISLAMIENTO ESTRICTO (cruza A1): un run ANÓNIMO o
        # de OTRO usuario NUNCA lee/escribe la memoria de un agente ajeno ni liga su run a él,
        # aunque pase el uuid. El slug de un agente sin guardar (no-uuid) no keyea nada. Se
        # resuelve ANTES de create_run (misma txn que el tier → sin idle-in-transaction).
        _agent_pid: Optional[str] = None
        pinned_memory: Optional[str] = None
        distill_memory = False
        _valid_pid = _valid_uuid(puppet_id)
        if _valid_pid and user_id:
            try:
                _p = phase1_repo.get_puppet(conn, _valid_pid)
            except Exception:
                _p = None
                try:
                    conn.rollback()   # el SELECT falló → txn ABORTADA; sin rollback create_run
                except Exception:     # (y todo el run del DUEÑO) crashea con 'transaction is aborted'
                    pass
            if _p and str(_p.get("owner_id")) == str(user_id):
                # el agente existe y es TUYO → liga runs.puppet_id + identidad SIEMPRE (el linkage
                # del moat no depende de la capa de caps). La MEMORIA (leer pineada + destilar) sí
                # necesita la frontera por-tier; si la capa gates no cargó, corré sin memoria.
                _agent_pid = _valid_pid
                if _mem_ceiling is not None:
                    distill_memory = True   # → aprende al cierre
                    try:
                        _budget = min(_A3_PINNED_BUDGET_BYTES, int(_mem_ceiling["max_bytes"]))
                        _mems = phase1_repo.list_memories(conn, _agent_pid, pinned_only=True)
                        # ORDEN 4 · HERENCIA: al REUSAR el agente en sesión/composición nueva, la
                        # elección del usuario (recipe.memory.inherit) acota el conjunto ELEGIBLE de
                        # su memoria ANTES del recall — 'solo pericia' deja fuera toda la episódica.
                        # Sin política = continuación normal (no acota). La memoria de CUENTA NO pasa
                        # por acá: es otra tabla, otro read-path (arriba, gated _depth==0) → herencia
                        # jamás arrastra un hecho de cuenta a un agente que luego se comparta/compose.
                        _md = recipe.get("memory") if isinstance(recipe, dict) else None
                        _inherit = _md.get("inherit") if isinstance(_md, dict) else None
                        _mems = apply_inheritance(_mems, _inherit)
                        # FIX 26 (deep) · CAPA SEMÁNTICA OPT-IN: si el dueño tiene key de embeddings
                        # (BYOK, la del RAG), sumamos coseno pedido↔memoria al ranking (rescata
                        # paráfrasis que el léxico pierde). Capado a ≤80 memorias (no explotar costo);
                        # try/except → None → cae al léxico+entidad (que YA funciona). Jamás rompe.
                        _sem = None
                        try:
                            if user_id and 0 < len(_mems) <= 80:
                                from app.phase1 import rag_index as _rix
                                from app.phase1 import memory_recall as _mrx
                                _sprov = _rix.pick_embed_provider(user_id)
                                _skey = _rix.resolve_embed_key(user_id, _sprov) if _sprov else None
                                if _skey:
                                    _st = _rix.embed_target_for(_sprov, None)
                                    _commit_before_external_io(conn, "memory_embedding")
                                    _sem = _mrx.compute_semantic_scores(
                                        prompt, _mems,
                                        embed_fn=lambda ts: _rix.embed_texts(
                                            ts, provider=_sprov, model=_st["model"],
                                            api_key=_skey, base_url=_st["base_url"]))
                        except Exception:
                            _sem = None
                        # ORDEN 3 · recall relevante: la PERICIA (skill) siempre viaja; la EPISÓDICA
                        # entra top-k relevante al pedido (no el volcado entero). Preserva recencia.
                        _mems = select_relevant_memories(
                            _mems, prompt, k=EPISODIC_TOPK, always_kinds=("skill",), order="recency",
                            sem_scores=_sem)
                        pinned_memory = _build_pinned_memory(_mems, budget_bytes=_budget) or None
                    except Exception:
                        pinned_memory = None    # lectura falló → corré SIN memoria (degrada suave)
                        try:
                            conn.rollback()     # idem: no dejar la txn envenenada para create_run
                        except Exception:
                            pass

                    # ── PIEZA 1 · CAPTURA EXPLÍCITA DETERMINISTA ("recordá esto") ──────────────
                    # Cuando el usuario PIDE explícitamente guardar algo, la captura NO pasa por el
                    # juicio probabilístico del destilador (que responde "NADA" ~17% de las veces,
                    # ver [[memoria-sonda0-sustrato]]): un detector PURO extrae el contenido VERBATIM
                    # y lo persiste YA, source='user' (que enforce_memory_caps RETIENE por encima de
                    # lo destilado 'agent') + pinned (el READ path lo recupera en sesión fría).
                    # Independiente del resultado del run: add_memory COMMITEA al instante, antes de
                    # create_run — el pedido explícito se honra aunque el run luego degrade o falle.
                    # Fail-safe: un error acá jamás tumba el run.
                    try:
                        _cap = _detect_capture(prompt)
                        if _cap:
                            phase1_repo.add_memory(
                                conn, puppet_id=_agent_pid, content=_cap,
                                source="user", pinned=True, meta={"explicit": True})
                            phase1_repo.enforce_memory_caps(
                                conn, _agent_pid,
                                max_entries=int(_mem_ceiling["max_entries"]),
                                max_bytes=int(_mem_ceiling["max_bytes"]))
                            out["memory_captured"] = _cap
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass

                    # ── PIEZA 2 · OLVIDO / CORRECCIÓN EXPLÍCITA (el inverso de la captura) ─────
                    # DESTRUCTIVO → conservador: el detector no dispara ante negación ni deíctico
                    # sin blanco; y acá CAPEAMOS (un blanco que matchearía TODO no se ejecuta). El
                    # borrado del panel (delete/clear) NO pasa por el gate (estado local del dueño);
                    # esto es lo mismo, disparado por conversación. Fail-safe: nunca tumba el run.
                    try:
                        _forget = _detect_forget(prompt)
                        if _forget:
                            if _forget.get("mode") == "all":
                                _n = phase1_repo.clear_memories(conn, _agent_pid)
                                out["memory_forgotten"] = {"mode": "all", "count": _n}
                            else:
                                _tgt = (_forget.get("target") or "").lower()
                                _allm = phase1_repo.list_memories(conn, _agent_pid)
                                _hits = [m for m in _allm if _tgt in (m.get("content") or "").lower()]
                                # CAP anti-barrido: un blanco que matchea TODO (>1 entrada) es
                                # demasiado genérico → NO borra (probable falso positivo). Red bajo
                                # el determinismo: preferimos NO borrar de más.
                                if _hits and not (len(_hits) == len(_allm) and len(_allm) > 1):
                                    for _m in _hits:
                                        phase1_repo.delete_memory(conn, _m["id"])
                                    out["memory_forgotten"] = {
                                        "mode": "match", "target": _forget.get("target"),
                                        "deleted": [(_m.get("content") or "")[:120] for _m in _hits]}
                                elif _hits:
                                    out["memory_forget_skipped"] = {
                                        "reason": "target_too_generic",
                                        "target": _forget.get("target"), "would_match": len(_hits)}
                        _corr = _detect_correction(prompt)
                        if _corr:
                            # el hecho corregido se AGREGA (supera al viejo por recencia en el recall)
                            phase1_repo.add_memory(
                                conn, puppet_id=_agent_pid, content=_corr["new"], source="user",
                                pinned=True, meta={"explicit": True, "correction": True})
                            _forgot_old = False
                            if _corr.get("old"):
                                _o = _corr["old"].lower(); _new_l = _corr["new"].lower()
                                for _m in phase1_repo.list_memories(conn, _agent_pid):
                                    _c = (_m.get("content") or "").lower()
                                    # borra la vieja contradicha, nunca la que acabás de agregar
                                    if _o in _c and _new_l not in _c:
                                        phase1_repo.delete_memory(conn, _m["id"]); _forgot_old = True
                            phase1_repo.enforce_memory_caps(
                                conn, _agent_pid,
                                max_entries=int(_mem_ceiling["max_entries"]),
                                max_bytes=int(_mem_ceiling["max_bytes"]))
                            out["memory_corrected"] = {"new": _corr["new"], "forgot_old": _forgot_old}
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass

        # ── STEP 2·B2 · MEMORIA COMPARTIDA del Cuarto (composición) · read-path server-side ──
        # La composición = el puppet GUARDADO top-level (_agent_pid = composition_id). Los agentes
        # CONECTADOS al cilindro (línea teal = recipe.memory.members) leen el bus al armar contexto
        # y dejan su aporte al cierre; los NO conectados no lo ven. El BUS entre >1 agente es
        # PREMIUM: shared_bus del tier lo habilita en runtime (free ve el cilindro pero el bus no se
        # cablea; el assembler además RECHAZA una receta free con memory.shared + hijos). AISLAMIENTO
        # por composition_id: dos Cuartos = dos memorias. _caps_ceiling None (CLI/no-prod) = permitir.
        shared_pinned: Optional[str] = None
        shared_members: Optional[list] = None
        shared_author_label: Optional[str] = None
        shared_bus_note: Optional[str] = None   # STEP 2·A2 · aviso HONESTO si el bus degrada por tier
        distill_shared = False
        _bus_on = True if _caps_ceiling is None else bool(_caps_ceiling.get("shared_bus", False))
        _mem_decl = recipe.get("memory") if isinstance(recipe, dict) else None
        _shared_declared = bool(_agent_pid and isinstance(_mem_decl, dict) and _mem_decl.get("shared"))
        if _shared_declared and not _bus_on:
            # ── STEP 2·A2 · DEGRADACIÓN VISIBLE del bus (nunca vacío silencioso) ──────────────
            # La receta PIDIÓ memoria compartida pero el tier del dueño NO cablea el bus (premium).
            # El assembler ya RECHAZA una composición free CON hijos (candado B2). Pero un puppet
            # SOLO con memory.shared en free se PERMITE correr → sin este aviso, el agente consulta
            # el bus/MCP de delegación VACÍO y contesta "la memoria está vacía" (falso-rojo real de
            # 2E·H5). Acá lo hacemos EXPLÍCITO en el veredicto (out) Y en el framing del agente:
            # el bus de EQUIPO es premium, no "sin datos". Su memoria PRIVADA (A3) sigue intacta.
            _deg = {
                "reason": "tier_no_premium",
                "feature": "shared_memory_bus",
                "tier": _tier,
                "min_tier": "basico",
                "message": ("El bus de memoria COMPARTIDA entre agentes es una función Premium; "
                            "tu plan actual no lo cablea. Tu memoria privada sigue disponible, pero "
                            "en esta corrida NO hay memoria de EQUIPO (bus no disponible en tu tier)."),
            }
            out["shared_bus_degraded"] = _deg
            shared_bus_note = _deg["message"]
        elif _shared_declared and _bus_on:
            _declared_members = _mem_decl.get("members")
            # members explícitos (la línea teal por-agente del front) o "*" (legacy = todos
            # los conectados, como el connect-all decorativo de hoy). El assembler matchea
            # shared_self ('nucleo' | slug del hijo) contra esta lista (o el wildcard).
            shared_members = (_declared_members if (isinstance(_declared_members, list)
                                                    and _declared_members) else ["*"])
            shared_author_label = (_p.get("name") if isinstance(_p, dict) else None) or "Núcleo"
            distill_shared = True   # el _is_member del assembler decide si realmente destila
            try:
                _shrows = phase1_repo.list_shared_memories(conn, _agent_pid, pinned_only=True)
                # cada nota entra atribuida a su autor ([Autor] texto) — el bloque muestra QUIÉN
                # escribió qué; el executor reusa el mismo presupuesto/compactado que A3.
                _sh_lines = [{"content": f"[{(x.get('author_label') or 'agente')}] "
                                        + (x.get('content') or '')} for x in _shrows]
                shared_pinned = _build_pinned_memory(
                    _sh_lines, budget_bytes=_A3_PINNED_BUDGET_BYTES) or None
            except Exception:
                shared_pinned = None    # lectura falló → corré SIN bus (degrada suave)
                try:
                    conn.rollback()     # no dejar la txn envenenada para create_run
                except Exception:
                    pass

        # ── STEP 2·C1 · RAG (átomo Conocimiento) · RECUPERACIÓN read-path server-side ──
        # El corpus del Cuarto (docs INDEXADOS por composición) se consulta ACÁ, antes de crear el
        # run y en la MISMA txn (misma disciplina que A3/B2 → sin idle-in-transaction). AISLAMIENTO
        # ESTRICTO por composition_id = _agent_pid (ya verificado DUEÑO arriba): otra composición
        # jamás ve este corpus. La retrieval es FUNCIONAL y GRATIS (self_hosted, como A3 — NO
        # premium como el bus B2); _rag_ceiling sólo mide en modo hosted (upload path). La key de
        # embeddings es BYOK del DUEÑO (Directiva #2): sin key NO caemos a la de Aleph ni a un skip
        # silencioso → anotamos 'rag_no_key' y el run SIGUE sin rag. Los fragmentos son contenido
        # NO confiable del usuario: entran al framing como APUNTES con procedencia [doc#chunk],
        # NUNCA como instrucciones — el piso money/send es INMUTABLE (assert_invariant en el motor).
        _obs.marca("exec.pre_rag")
        rag_block: Optional[str] = None
        _rag_decl = recipe.get("rag") if isinstance(recipe, dict) else None
        if _agent_pid and isinstance(_rag_decl, dict) and _rag_decl.get("enabled"):
            # evidencia honesta del MODO: None (self_hosted → sin cap, retrieval libre) o el
            # techo por-tier {max_docs,max_bytes} (hosted, que el UPLOAD del router enforza).
            out["rag_ceiling"] = _rag_ceiling
            try:
                from app.phase1 import rag_index
                # PIVOT (v2) · la recuperación va por el STORE scopeado a ESTA composición
                # (=_agent_pid, ya verificado DUEÑO arriba), NO por repo.list_chunks_for_retrieval
                # directo: self_hosted (DEFAULT) lee el ARCHIVO sqlite en el disco del usuario;
                # hosted lee el Postgres de Aleph. La ruta del .db la DERIVA el server desde
                # composition_id (el cliente NUNCA la aporta) → dos composiciones = dos archivos =
                # aislamiento estructural, sin que el read-path sepa del modo.
                store = knowledge_store.get_store(conn=conn, composition_id=_agent_pid)
                # ¿Hay corpus? Sin docs no hay nada que recuperar (ni gasto de embed): el run sigue
                # sin rag, sin ruido. usage() abre el file / consulta PG → DENTRO del try (si el
                # store falla, el rollback de abajo saca la txn de Postgres del estado abortado).
                _usage = store.usage()
                if _usage and _usage.get("doc_count"):
                    # Finding #4 · sólo hay algo que RECUPERAR (y por lo tanto sólo vale pagar un embed
                    # BYOK) si existe un chunk indexado. doc_count cuenta TODO doc (incl. pending/error
                    # /error_no_key) → un corpus con puros docs no-indexados NO debe gastar el embed.
                    _indexed = int(_usage.get("indexed_count") or 0)
                    if not _indexed:
                        # HAY docs pero NINGUNO recuperable: NO gastamos un embed que nunca traería
                        # nada. Degradación HONESTA (no skip mudo): sin key → rag_no_key; con key pero
                        # sin índice utilizable → reindexar. Sólo un lookup del broker, jamás un embed.
                        out["rag_note"] = ("rag_needs_reindex"
                                           if rag_index.pick_embed_provider(user_id)
                                           else "rag_no_key")
                    else:
                        # Finding #2 · la RECUPERACIÓN SIGUE AL CORPUS, no a la receta: embebemos la
                        # query con EXACTAMENTE el provider/model con que se indexaron los chunks. Si
                        # la receta pidió otro provider (drift), seguir la receta embebería la query en
                        # otra dimensión → top_k dropea TODO en silencio (rag_block=None sin nota).
                        _cinfo = store.corpus_embed_info()
                        _cprov = _cinfo.get("provider")
                        if _cinfo.get("mixed") or not _cprov:
                            # docs indexados con proveedores/dims que NO concuerdan (o sin firma) → no
                            # hay UNA query que sirva a todo el corpus: honesto, reindexar. Sin embed.
                            out["rag_note"] = "rag_needs_reindex"
                        else:
                            _ekey = rag_index.resolve_embed_key(user_id, _cprov)
                            if not _ekey:
                                # el corpus se indexó con un provider cuya key YA no está (rotación) →
                                # honesto, jamás la key de Aleph ni un empty mudo. Corre sin rag.
                                out["rag_note"] = "rag_provider_unavailable"
                            else:
                                _et = rag_index.embed_target_for(_cprov, _cinfo.get("model"))
                                _commit_before_external_io(conn, "rag_embedding")
                                _qvec = rag_index.embed_texts(
                                    [intent or prompt or ""],
                                    provider=_cprov, model=_et["model"],
                                    api_key=_ekey, base_url=_et["base_url"],
                                )[0]
                                # el store hace top_k por coseno (Python puro) contra los chunks de SU
                                # backend (sqlite file en self_hosted, Postgres en hosted).
                                _hits = store.retrieve_topk(_qvec, k=5)
                                rag_block = _build_rag_block(
                                    _hits, budget_bytes=_A3_PINNED_BUDGET_BYTES) or None
                                if rag_block is None:
                                    # embebimos con la key DEL CORPUS pero top_k igual dropeó TODO: dim
                                    # mismatch residual → honesto (rag_needs_reindex), NUNCA empty mudo.
                                    out["rag_note"] = "rag_needs_reindex"
            except Exception:
                # HIGH bug class (idéntico a A3/B2): CUALQUIER fallo tocando la conn —o el ARCHIVO
                # sqlite del self_hosted store— deja la txn de Postgres ABORTADA/colgada. Sin
                # rollback, create_run (y TODO el run del dueño) crashea con 'transaction is aborted'
                # y el run zombiea 'running'. Un error de sqlite/file DEBE rollbackear la txn de
                # Postgres IGUAL (el fallo puede venir del store, no de la conn) → corré SIN rag,
                # nunca crash/zombie.
                rag_block = None
                try:
                    conn.rollback()
                except Exception:
                    pass

        # [UX·B5] INSTRUCCIONES PERSISTENTES del dueño (cuenta + composición) → van a la
        # capa FRAMING del run (autoridad, a diferencia de la memoria-como-apuntes).
        # Solo filas enabled; una propuesta del agente (enabled=false) JAMÁS se inyecta.
        # Fail-safe con rollback (misma clase de bug HIGH que A3/B2/C1).
        instructions_block = None
        if user_id:
            try:
                from app.phase1 import instructions_repo as _irepo
                instructions_block = _irepo.build_block(conn, user_id, _agent_pid) or None
            except Exception:
                instructions_block = None
                try:
                    conn.rollback()
                except Exception:
                    pass

        # ── PIEZA MÉTODO · cargar el método (owner-gated) ANTES del run ──────────
        # Método inexistente/ajeno/anónimo ⇒ el run corre SIN método y lo DICE
        # (out.method_error): degradación visible, jamás un chip 'dirigiendo' falso.
        _method_spec = None
        if method_id:
            try:
                from app.phase1 import methods_repo as _mrepo0
                if user_id and _valid_uuid(method_id):
                    _method_spec = _mrepo0.get_method(conn, method_id, user_id)
            except Exception:
                _method_spec = None
                try:
                    conn.rollback()
                except Exception:
                    pass
            if _method_spec is None:
                out["method_error"] = "method_not_found"

        # 1) crear el run en Postgres ANTES de correr (el run_id es EL ligador del moat).
        #    puppet_id = el uuid VALIDADO/AUTORIZADO (tuyo); slug/ajeno/anónimo → NULL.
        run_row = phase1_repo.create_run(
            conn, puppet_id=_agent_pid, user_id=user_id,
            space_id=space_id, intent=intent,
        )
        run_id = run_row["id"]
        out["run_id"] = run_id
        # [F5 · 5.2] El `run_id` como ALIAS del handle: parar por espacio y parar por run
        # tienen que ser el mismo acto, y el forense usa el run_id.
        _turnos_obra.ligar(_handle, run_id)

        # OUTPUT DIR ESTABLE DEL RUN: ligado al run_id, bajo data/run_outputs. El agente
        # escribe su obra (planillas, docs) acá con ruta absoluta (el assembler le inyecta
        # la ruta al prompt), persiste tras el run y el endpoint de descarga la sirve.
        run_workdir = str((_RUN_OUTPUTS_ROOT / _carpeta_del_turno(chat_id if _tengo_el_hilo else None,
                                                       space_id if _tengo_el_hilo else None, run_id)).resolve())
        Path(run_workdir).mkdir(parents=True, exist_ok=True)
        out["workdir"] = run_workdir
        #: EL CORTE DE LA COSECHA. Con el workdir COMPARTIDO por espacio, el dir ya trae lo
        #: que escribieron los turnos anteriores; sin este corte, `_capture_workdir_outputs`
        #: (que hace `rglob("*")`) volvería a capturar el .xlsx del turno 3 como obra del
        #: turno 5, y la Biblioteca se llenaría del mismo archivo una vez por turno. Es el
        #: MISMO modo de falla que su docstring ya nombra para los adjuntos.
        #: Se toma ANTES de correr y con un colchón de 1 s: los relojes de archivo tienen
        #: granularidad, y perder una obra por redondeo es peor que capturar una de más.
        _cosecha_desde = time.time() - 1.0

        # [T2.5c] LOS ADJUNTOS DE LA CONVERSACIÓN, DENTRO DEL ALCANCE DEL AGENTE.
        # El inbox vive fuera del run (persiste entre turnos, es del dueño y de la sesión);
        # el server `filesystem` sólo alcanza `${PUPPET_WORKDIR}` y resuelve realpath, así
        # que un symlink NO sirve —lo rechazaría por estar fuera de la allow-list—. Se COPIA.
        #
        # Copia y no hardlink A PROPÓSITO: con hardlink, un `edit_file` del agente escribiría
        # sobre el archivo ORIGINAL del usuario. El adjunto es suyo; el agente trabaja sobre
        # una copia y lo que rompa se pierde con el run.
        if inbox_dir:
            try:
                _src = Path(inbox_dir)
                if _src.is_dir():
                    _dst = Path(run_workdir) / ADJUNTOS_DIR
                    _dst.mkdir(parents=True, exist_ok=True)
                    for _f in sorted(_src.iterdir()):
                        # los internos del inbox (índice, lock) no son del usuario
                        if not _f.is_file() or _f.name.startswith((".", "_")):
                            continue
                        shutil.copy2(_f, _dst / _f.name)
            except Exception as _e:            # noqa: BLE001 — un adjunto no tumba el turno
                log.warning("no pude copiar los adjuntos al workdir: %s", type(_e).__name__)

        # ── PIEZA MÉTODO · construir el ARNÉS (estado externo durable + control) ──
        # Fail-safe: si el arnés no se puede armar, el run corre SIN método y lo
        # dice — jamás zombie por txn envenenada (rollback) ni verde falso.
        _mh = None
        if _method_spec is not None:
            try:
                _mh = _build_method_harness(
                    conn, spec=_method_spec, method_id=method_id,
                    run_id=str(run_id), user_id=user_id, puppet_id=_agent_pid,
                    space_id=space_id, recipe=recipe, lang=lang,
                    adjust=method_adjust, seed_state=method_seed_state,
                )
            except Exception:
                _mh = None
                out["method_error"] = "method_harness_failed"
                try:
                    conn.rollback()
                except Exception:
                    pass

        # 2) assemble_and_run — ENFORCER EN EL PATH + belt real + modelo OSS.
        #    user_id/run_id van AL assembler para que cada COST-EVENT (§4.6) salga ya scopeado
        #    al usuario y al run (lo que T7/T8 billing necesitan; nadie lee costo sin scope).
        # [UX·A1] history_text (conversación previa del chat, registro real) se antepone
        # SOLO al prompt que ve el cerebro; intent/embeds/moat quedan con el prompt crudo.
        _brain_prompt = (history_text + "\n\n" + prompt) if history_text else prompt
        _obs.marca("exec.al_assembler")
        _commit_before_external_io(conn, "model")
        record = _asm().assemble_and_run(
            recipe, _brain_prompt,
            repo_root=_RESOURCE_ROOT,
            byok_resolver=byok_resolver,
            deadline_s=deadline_s,
            approve=approve,
            base_matrix=base_matrix,
            on_event=on_event,
            workdir=run_workdir,
            images=images,
            user_id=user_id,
            run_id=run_id,
            lang=lang,
            client_tools=client_tools,     # [FIX-P9] se le DECLARAN al modelo; el motor no las corre
            _caps_ceiling=_caps_ceiling,   # STEP 2·A1 FRONTERA · techo de tier (clampa todo el árbol)
            account_tier=_tier,            # MURALLA PREMIUM · tier de la CUENTA (server-side) → gate autoritativo
            agent_id=_agent_pid,           # STEP 2·A3 · identidad del agente (keyea la memoria)
            pinned_memory=pinned_memory,   # STEP 2·A3 · su memoria compacta → framing PINEADO
            account_pinned=account_pinned, # ORDEN 2 · Sistema 2 · hechos de CUENTA (sobre la persona) → framing
            distill_memory=distill_memory, # STEP 2·A3 · destilar aprendizajes al cierre del run
            shared_pinned=shared_pinned,   # STEP 2·B2 · bloque compartido del Cuarto (agentes conectados)
            shared_members=shared_members, # STEP 2·B2 · membresía teal (identidades conectadas al cilindro)
            shared_self=("nucleo" if shared_members else None),  # STEP 2·B2 · identidad del top-level
            shared_author_label=shared_author_label,             # STEP 2·B2 · nombre del núcleo para atribuir
            shared_bus_note=shared_bus_note,  # STEP 2·A2 · aviso HONESTO al framing si el bus degrada por tier
            distill_shared=distill_shared, # STEP 2·B2 · destilar el aporte al bus al cierre
            rag_block=rag_block,           # STEP 2·C1 · APUNTES recuperados del Conocimiento (str|None)
            instructions_block=instructions_block,  # UX·B5 · instrucciones del dueño → framing
            method_harness=_mh,            # PIEZA MÉTODO · el arnés (None = run byte-idéntico)
        )
        out["record"] = record
        out["ok"] = bool(record.get("ok"))
        if isinstance(record, dict) and record.get("method"):
            out["method"] = record["method"]   # resumen del arnés (estado durable en method_runs)

        # ── STEP 2·A3 · PERSISTIR lo destilado (write-path server-side; NO pasa por el gate) ──
        # El motor devolvió record['memory_distilled'] (aprendizajes durables). Los guardamos
        # keyed por el agente y aplicamos la FRONTERA por-tier (evicta las 'agent' viejas). Fail
        # -safe: un error guardando memoria NUNCA tumba el run (la obra ya está).
        _distilled = record.get("memory_distilled") if isinstance(record, dict) else None
        if _agent_pid and _mem_ceiling is not None and _distilled:
            try:
                # FIX 26 · SANGRÍA DE CAPTURA (dedupe + cap diario + backstop de meta). Reusa las
                # heurísticas léxicas del read-path (memory_recall) para no re-implementar tokenizado.
                from app.phase1 import memory_recall as _mrec
                import os as _os
                _daily_cap = int(_os.environ.get("PUPPET_MEM_DAILY_CAP", "40"))
                _today = phase1_repo.count_agent_memories_today(conn, _agent_pid)
                _existing = phase1_repo.list_memories(conn, _agent_pid)
                _seen = [(_mrec._salient_tokens(m.get("content", "")), m.get("id")) for m in _existing]
                _saved = _reinforced = _meta_dropped = _capped = 0
                # TICKET 26 · CITA VERIFICABLE (patrón Copilot): cada memoria destilada guarda su ORIGEN
                # — el run que la generó + un excerpt del pedido — para poder auditarla contra su fuente
                # (¿de dónde salió este "aprendizaje"?). run_id ancla al espacio/eventos del run.
                _cite = {"run_id": run_id, "from": ((prompt[:160] if isinstance(prompt, str) and prompt
                                                     else "(pedido con adjuntos)"))}
                for _item in _distilled:
                    # PIEZA 2 · {content, provenance}; ORDEN 2 · + kind (skill|episodica). Back-compat
                    # con str y con dict sin kind (default fail-safe: episódica → no viaja sola).
                    if isinstance(_item, dict):
                        _content = _item.get("content") or ""
                        _prov = _item.get("provenance", "inferencia")
                        _kind = _item.get("kind", "episodica")
                    else:
                        _content, _prov, _kind = _item, "inferencia", "episodica"
                    if not _content:
                        continue
                    # (3) META · kind-at-origin (ticket 26): el destilador tagueó kind='meta' explícito →
                    # se PERSISTE con kind=meta (auditable) pero FUERA del budget de dominio (el recall la
                    # demota vía _meta_of; NO cuenta al cap de dominio). El BACKSTOP léxico (_is_meta) sigue
                    # para lo NO-tagueado → drop. Ambos caminos: la meta jamás ahoga los hechos de dominio.
                    if _kind == "meta":
                        phase1_repo.add_memory(
                            conn, puppet_id=_agent_pid, content=_content, source="agent",
                            pinned=True, meta={"run_id": run_id, "provenance": _prov, "kind": "meta", "cite": _cite})
                        _meta_dropped += 1
                        continue
                    if _mrec._is_meta(_content):
                        _meta_dropped += 1
                        continue
                    _tk = _mrec._salient_tokens(_content)
                    # (1) DEDUPE EN CAPTURA · equivalente a una existente → REFUERZA la existente
                    # (bump updated_at = más viva en el recall), jamás duplica. Mata las N copias.
                    _dupid = next((mid for (kt, mid) in _seen
                                   if mid and _mrec._jaccard(_tk, kt) >= 0.72), None)
                    if _dupid:
                        phase1_repo.touch_memory(conn, _dupid); _reinforced += 1
                        continue
                    # (2) CAP DIARIO por agente (config PUPPET_MEM_DAILY_CAP, no hardcode) · mata 273/día.
                    if _today >= _daily_cap:
                        _capped += 1
                        continue
                    _row = phase1_repo.add_memory(
                        conn, puppet_id=_agent_pid, content=_content,
                        source="agent", pinned=True,
                        meta={"run_id": run_id, "provenance": _prov, "kind": _kind, "cite": _cite})
                    _seen.insert(0, (_tk, _row.get("id") if _row else None))
                    _today += 1; _saved += 1
                phase1_repo.enforce_memory_caps(
                    conn, _agent_pid,
                    max_entries=int(_mem_ceiling["max_entries"]),
                    max_bytes=int(_mem_ceiling["max_bytes"]))
                out["memory_saved"] = _saved
                if _reinforced:
                    out["memory_reinforced"] = _reinforced
                if _meta_dropped:
                    out["memory_meta_dropped"] = _meta_dropped
                if _capped:
                    out["memory_daily_capped"] = _capped
            except Exception:
                try:
                    conn.rollback()   # STEP 2·A3 · un fallo del write-path (INSERT/enforce) deja la
                except Exception:     # txn ABORTADA; sin rollback, persist_run/finish_run crashean en
                    pass              # cascada y el run queda colgado en 'running' (zombie). Espeja el
                                      # read-path A3 + held-actions. Fail-safe: sólo pierde este batch.

        # ── STEP 2·B2 · PERSISTIR los aportes al BUS COMPARTIDO (write-path server-side, NO gate) ──
        # record['shared_distilled'] = LISTA de {author_agent_id, author_label, content} del
        # top-level Y de los hijos conectados (burbujeados por el motor). Se guardan keyed por
        # composition_id (= _agent_pid = el Cuarto) con su AUTORÍA y se aplica la frontera por-tier.
        # NO pasa por el gate (op server-side, como A3). Fail-safe: nunca tumba el run.
        _shared_items = record.get("shared_distilled") if isinstance(record, dict) else None
        if _agent_pid and _bus_on and _mem_ceiling is not None and _shared_items:
            try:
                _sv = 0
                for _sit in _shared_items:
                    if not isinstance(_sit, dict) or not str(_sit.get("content") or "").strip():
                        continue
                    phase1_repo.add_shared_memory(
                        conn, composition_id=_agent_pid,
                        content=str(_sit.get("content")),
                        author_agent_id=_sit.get("author_agent_id"),
                        author_label=_sit.get("author_label"),
                        source="agent", pinned=True,
                        # ORDEN 2 · el aporte al bus también lleva kind + provenance (antes se
                        # perdían acá: la meta B2 sólo guardaba run_id). Defaults fail-safe.
                        meta={"run_id": run_id,
                              "provenance": _sit.get("provenance", "inferencia"),
                              "kind": _sit.get("kind", "episodica")})
                    _sv += 1
                phase1_repo.enforce_shared_memory_caps(
                    conn, _agent_pid,
                    max_entries=int(_mem_ceiling["max_entries"]),
                    max_bytes=int(_mem_ceiling["max_bytes"]))
                out["shared_memory_saved"] = _sv
            except Exception:
                try:
                    conn.rollback()   # STEP 2·B2 · idem A3: un fallo guardando (deadlock de caps con
                except Exception:     # runs concurrentes del MISMO Cuarto, error transitorio) NO debe
                    pass              # envenenar la txn → persist_run/finish_run tumbarían el run del
                                      # dueño y lo dejarían en 'running'. Fail-safe: pierde sólo el batch.
        out["gate_enforced"] = bool(record.get("gate_enforced"))
        out["answer"] = record.get("answer", "") or ""
        # [UX·B5 + ORDEN 5] PROPUESTAS del agente que CIERRAN la respuesta: instrucción persistente
        # (autoridad) y hecho_de_cuenta (Sistema 2). AMBAS se extraen del answer ORIGINAL, NO
        # encadenadas — sólo el ÚLTIMO bloque CIERRA la respuesta, así que a lo sumo UNA se captura y
        # un bloque ENTERRADO en una cita de terceros JAMÁS se captura ni se recorta en silencio
        # (anti-laundering — review orden-5: encadenar recorte→re-extraer podía re-exponer un bloque
        # enterrado). Nacen INERTES (source='agent', sin autoridad) hasta que el humano las active/
        # confirme. Fail-safe: jamás tumban el run.
        if user_id and out["answer"]:
            _orig_answer = out["answer"]
            # (a) instrucción persistente (bloque que cierra la respuesta)
            try:
                from app.phase1 import instructions_repo as _irepo2
                _prop, _clean_ans = _irepo2.extract_proposal(_orig_answer)
                if _prop:
                    out["answer"] = _clean_ans or ""
                    _prow = _irepo2.add_proposal(conn, user_id=user_id, puppet_id=_agent_pid,
                                                 content=_prop, run_id=str(out.get("run_id")))
                    out["instruction_proposed"] = bool(_prow)
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
            # (b) hecho de MEMORIA DE CUENTA — nace INERTE (pinned=FALSE → NO entra al framing hasta
            # confirmar). Extraído del MISMO answer ORIGINAL (instrucción y hecho no cierran a la vez
            # → sin conflicto de recorte). El bloque se recorta SIEMPRE (aunque se rechace la
            # promoción). Filtro AUTH-NEVER-PERSIST: una autorización JAMÁS se promueve (regla dura) →
            # account_proposal_rejected honesto. Expuesto en account_proposed para el "¿guardar?".
            try:
                from app.phase1 import account_proposal as _aprop
                _afact, _aclean = _aprop.extract_account_proposal(_orig_answer)
                if _afact:
                    out["answer"] = _aclean or ""     # recortá el bloque pase lo que pase
                    _scr_ok, _scr_why = _aprop.screen_account_fact(_afact)
                    if _scr_ok:
                        _arow = phase1_repo.add_account_proposal(
                            conn, owner_id=user_id, content=_afact, run_id=str(out.get("run_id")))
                        out["account_proposed"] = ({"id": str(_arow["id"]), "content": _afact}
                                                   if _arow else None)   # None = cap de pendientes lleno
                    else:
                        out["account_proposed"] = None
                        out["account_proposal_rejected"] = _scr_why   # 'authorization' | 'empty'
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
        # COST-EVENTS (§4.6): el ledger por-call (modelo + tools), ya scopeado a user_id/run_id.
        # T5/T4 los PRODUCEN; T7/T8 los CONSUMEN. Los exponemos en la salida del executor para
        # que la capa de billing los persista/agregue (su slice), sin re-derivarlos.
        out["cost_events"] = record.get("cost_events", [])
        out["model_alias"] = record.get("model_alias")
        # FALLBACK VISIBLE (C6): si el brain cayó a la red OSS, el resumen viaja en la salida
        # del run (telemetría) — None cuando el cerebro pedido respondió. No es self-report:
        # sale del route_log real del assembler. La UI/telemetría lo MUESTRA, no es silencioso.
        out["degraded"] = record.get("degraded")

        # 3) trayectoria desde el RUN RECORD (campo 3)
        trayectoria = build_trajectory_from_record(record)
        out["trajectory_steps"] = len(trayectoria)

        # campo (2) belt: snapshot de la receta usada + lo que el assembler REALMENTE
        # cableó/resolvió (evidencia: belt resuelto, tools cableadas, gate enforced).
        belt_snapshot = {
            "recipe": recipe,
            "resolved_belt": record.get("belt"),
            "tools_cabled": record.get("tools_cabled", []),
            "tools_dropped": record.get("tools_dropped", []),
            "gate_enforced": record.get("gate_enforced", False),
            "gate_decisions": record.get("gate_decisions", []),
            "model_final": record.get("model_final"),
        }

        # campo (4) señal: aún no hay feedback del usuario en un run recién corrido;
        #   marcamos abandoned solo si el loop no produjo respuesta. Explícita queda None.
        senal = instr.build_signal(
            explicit=None,
            saved=False,
            edited=False,
            abandoned=not out["ok"],
        )

        # campo (5) costo: honesto (el loop no emite tokens hoy → total 0, desglose por turnos)
        costo = _build_cost_from_record(record)

        # 4) persistir LA fila del moat ligando por run_id los 5 campos
        log_id = instr.persist_run(
            conn,
            run_id=run_id,
            intent=intent,
            belt=belt_snapshot,
            trayectoria=trayectoria,
            senal=senal,
            costo=costo,
        )
        out["instrumentation_log_id"] = log_id
        out["error"] = record.get("error")

        # OUTPUT del run (Biblioteca = "Su obra"): persistir la respuesta como output.
        # El run PRODUCE la obra; sin esto la Biblioteca queda vacía. No tumba el run si falla.
        if out["ok"] and (out["answer"] or "").strip():
            try:
                phase1_repo.create_output(
                    conn, run_id=run_id, kind="message", mime="text/markdown",
                    content=out["answer"][:20000],
                )
            except Exception:
                pass

        # OBRA EN ARCHIVOS: capturar lo que el run escribió en su output dir como outputs
        # kind=file (descargables de Biblioteca). Independiente de la respuesta de texto:
        # un run puede producir SOLO un archivo. Este es el fix del bug — antes el .xlsx
        # quedaba huérfano en disco y nunca aparecía como obra.
        if out["ok"]:
            try:
                out["outputs_captured"] = _capture_workdir_outputs(
                    conn, run_id, run_workdir, desde=_cosecha_desde)
            except Exception as cap_exc:
                out["outputs_captured"] = []
                out.setdefault("warnings", []).append(f"capture: {type(cap_exc).__name__}")

        # OBRA RICA: si el run escribió un artifact estructurado en su workdir (FEM →
        # convergence/fieldplot; electrónica → planilla del BOM cotizado), lo surfaceamos
        # como out["obra"] para que La Sala lo rinda con su renderer (no una descarga
        # cruda). Ver _capture_rich_obra: ADITIVO + fail-closed (solo dispara si el archivo
        # existe y parsea con el shape esperado; jamás toca runs que no lo producen).
        if out["ok"]:
            _obra = _capture_rich_obra(run_workdir, desde=_cosecha_desde)
            if _obra is not None:
                out["obra"] = _cap_obra(_obra)   # ticket B3/IN4 · una obra grande no tumba el run

        # ACCIONES RETENIDAS (send/money que el send-gate SOSTUVO en needs_ok): persistirlas
        # para approve-by-HTTP. Cada una guarda la receta + server/tool/args → el OK explícito
        # del dueño por HTTP la ejecuta luego (deuda #1). El gate sostiene; el correo no salió.
        out["held_actions"] = []
        # ══ [Gate 4 · F5 · 5.2] UNA OBRA PARADA NO DEJA ACCIONES APROBABLES ═══════════
        # Éste era el peor de los estados falsos que la auditoría inventarió (H6): una
        # `held_action` es una acción de dinero o de envío esperando un OK, y persistirla
        # después de que el dueño paró el turno deja un botón vivo que puede EJECUTARLA
        # más tarde — mandar el correo que el usuario canceló, con su OK de hace media
        # hora sobre un turno que ya no existe.
        # No se persisten: quedan en el record (el forense las ve) y fuera de la DB (nadie
        # las puede aprobar). Parar tiene que valer también para lo que quedó a medias.
        _cancelada = _turnos_obra.fue_detenido(_handle)
        if _cancelada and record.get("held_actions"):
            out["held_no_persistidas"] = [
                {"server": h.get("server"), "tool": h.get("tool")}
                for h in record.get("held_actions") or []]
        for ha in ([] if _cancelada else (record.get("held_actions", []) or [])):
            try:
                # STEP 2·B1 · GATE ANIDADO: una acción retenida de un SUB-AGENTE viaja con la
                # receta DE ESE hijo (hoist en recipe_assembler._hoist_child_held_actions) →
                # se persiste con ella para que approve-by-HTTP re-arme el belt/gate/keys DEL
                # HIJO (execute_held_tool), no el del padre. Sin hoist (held propia del padre) →
                # la receta del run. El OK SIGUE subiendo al humano en cualquier nivel del árbol.
                _ha_recipe = ha.get("recipe") or recipe
                # B1 · árbol: qué sub-agente pide el OK (raíz→hoja) + profundidad. Se PERSISTEN
                # (fix provenance) para que un re-read del DB (recarga de la página / listado de
                # pendientes tras reinicio) siga sabiendo QUÉ sub-agente pidió la acción.
                row = phase1_repo.create_held_action(
                    conn, run_id=run_id, user_id=user_id, recipe=_ha_recipe,
                    server=ha.get("server", ""), tool=ha.get("tool", ""),
                    args=ha.get("args", {}) or {}, level=ha.get("level"),
                    agent_path=ha.get("agent_path"),
                    via_delegation=bool(ha.get("via_delegation")),
                    depth=ha.get("depth"),
                    turn_text=ha.get("turn_text"),   # [UX·B4] el "porque Y" durable
                )
                out["held_actions"].append({
                    "approval_id": str(row["id"]),
                    "server": row.get("server"),
                    "tool": row.get("tool"),
                    "level": row.get("level"),
                    "args": ha.get("args", {}),
                    # [UX·B4] la intención del turno que pidió la acción (card informada)
                    "turn_text": ha.get("turn_text"),
                    # A2 · bitácora: POR QUÉ quedó retenida (clase de acción + perilla vigente).
                    # La perilla también vive durable en held_actions.recipe.autonomy.
                    "action_class": ha.get("action_class"),
                    "autonomy": ha.get("autonomy"),
                    # B1 · árbol: qué sub-agente pide el OK (raíz→hoja) y a qué profundidad.
                    "agent_path": ha.get("agent_path"),
                    "via_delegation": bool(ha.get("via_delegation")),
                    "depth": ha.get("depth"),
                    # B1 · la UX del gate del HIJO (el hijo no emite gate_waiting): el front la
                    # necesita para pintar la tarjeta correcta y que el OK sea INFORMADO.
                    "ux": ha.get("ux"),
                })
            except Exception:
                # Un fallo persistiendo UNA held NUNCA tumba el run — pero sin rollback la txn
                # Postgres queda ABORTADA (InFailedSqlTransaction) y arrastra en cascada a las
                # held HERMANAS (incl. money) + al finish_run de abajo → run colgado en 'running'.
                # Espeja el fix HIGH de A3 (mismo except-swallow, misma cura). Cada held es
                # independiente: el rollback deja la conexión limpia para la siguiente.
                try:
                    conn.rollback()
                except Exception:
                    pass

        # 5) cerrar el run (done si ok, error si no). Guardado: si algo previo dejó la txn
        # envenenada, un rollback deja que el estado TERMINAL sí aterrice (no un run zombi).
        # [F5 · 5.2 · D6] `cancelado` es un estado NUEVO y deliberado, hermano del
        # `huerfano` que inventó `run_lifecycle` con el mismo argumento escrito:
        # «'error' mentiría (el turno no falló, se cortó)». Un turno que una PERSONA paró
        # tampoco falló, y tampoco es huérfano —hubo un motor y llegó hasta acá—.
        # Acordado con F4: huerfano = se murió el proceso · cancelado = lo paró alguien.
        _estado = ("cancelado" if _cancelada
                   else ("done" if out["ok"] else "error"))
        out["cancelado"] = bool(_cancelada)
        try:
            phase1_repo.finish_run(conn, run_id, status=_estado)
        except Exception:
            try:
                conn.rollback()
                phase1_repo.finish_run(conn, run_id, status=_estado)
            except Exception:
                pass
        return out

    except Exception as exc:
        # Si ya creamos el run, marcarlo error (no dejar un run colgado en 'running').
        if run_row is not None:
            try:
                conn.rollback()   # DEFENSA (review B2): si la excepción vino de una txn ABORTADA,
            except Exception:     # finish_run correría sobre una conexión envenenada y TAMBIÉN
                pass              # fallaría → el run quedaría colgado (lo que este handler evita).
            try:
                phase1_repo.finish_run(conn, run_row["id"], status="error")
            except Exception:
                pass
        out["error"] = f"executor: {type(exc).__name__}: {exc}"
        return out
    finally:
        # TERMINAL HONESTO: emitido en el finally → cubre TODOS los caminos de salida
        # (éxito, gate fail-closed, legal-gate, excepción). El stream SSE recibe el
        # veredicto real del run aunque algo haya fallado. Se emite ANTES de cerrar la
        # conexión propia (no requiere DB; solo appendea al events.jsonl del espacio).
        _emit_run_terminal(on_event, out)
        # [F5 · 5.2] EL REGISTRO SE LIMPIA SIEMPRE. Un registro que crece es una fuga con
        # forma de tabla, y un `space_id` reusado pararía una obra que no es.
        _turnos_obra.cerrar(_handle)
        _turnos_obra.soltar()
        # El candado del hilo se suelta SIEMPRE, pase lo que pase: uno que se queda tomado
        # deja la conversación entera esperando 90 s por turno, para siempre.
        if _tengo_el_hilo and _candado is not None:
            try:
                _candado.release()
            except RuntimeError:
                pass
        if own_conn and conn is not None:
            conn.close()


def _iso(dt) -> Optional[str]:
    """datetime → ISO string (o None). Para surfacear decided_at (timestamp durable de
    la decisión) en la respuesta de approve-by-HTTP: la bitácora de A2 lo hace explícito."""
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


def approve_held_action(
    approval_id: str,
    *,
    ok: bool,
    user_id: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict:
    """APPROVE-BY-HTTP: aprueba (ok=True → EJECUTA) o rechaza (ok=False) una acción retenida.

    El correo/pago NO salió durante el run (el gate lo sostuvo en needs_ok). Acá, con el OK
    EXPLÍCITO del dueño, se ejecuta de verdad — y SOLO acá. Aislamiento por usuario: si se
    provee user_id, debe ser el dueño de la acción. Idempotente: una acción ya decidida no se
    re-ejecuta. La credencial sale del BROKER REAL ligado al dueño (no un atajo).

    Devuelve {found, executed, status, result, error}.
    """
    own_conn = conn is None
    if own_conn:
        conn = phase1_repo.get_conn()
    try:
        # RECOVERY-SWEEP (caveat #2): revive filas colgadas en 'executing' de un proceso caído
        # mid-send (TTL generoso; NO toca approves concurrentes en vuelo). Si ESTA acción quedó
        # colgada, vuelve a 'held' y el OK de abajo la puede re-aprobar. Best-effort.
        try:
            phase1_repo.recover_stuck_executing(conn)
        except Exception:
            pass

        ha = phase1_repo.get_held_action(conn, approval_id)
        if ha is None:
            return {"found": False, "executed": False, "error": "approval_id no encontrado"}
        if user_id is not None and str(ha.get("user_id")) != str(user_id):
            return {"found": True, "authorized": False, "executed": False,
                    "error": "esa acción no es tuya"}
        status = ha.get("status")
        if status != "held":
            # ya decidida o EN VUELO (executing) por otro request: no re-ejecutar.
            return {"found": True, "executed": status == "executed",
                    "status": status, "already_decided": True}

        if not ok:
            # RECHAZO atómico: solo transiciona si SIGUE en 'held' (no pisa una que ya se está
            # ejecutando por un OK concurrente). Si perdió la carrera → already_decided.
            # A2 · bitácora: el APPROVER (quién rechazó) queda explícito en el result durable.
            rejected = phase1_repo.decide_held_action(
                conn, approval_id, status="rejected",
                result=(f"rechazada por el usuario {user_id}" if user_id
                        else "rechazada por el usuario"), expect="held")
            if rejected is None:
                cur = phase1_repo.get_held_action(conn, approval_id) or {}
                return {"found": True, "executed": cur.get("status") == "executed",
                        "status": cur.get("status"), "already_decided": True}
            # PIEZA MÉTODO · el rechazo de un CHECKPOINT también queda durable en el
            # control-plane del arnés (por si el run ya cortó y hay una continuación).
            if ha.get("server") == "metodo" and ha.get("tool") == "checkpoint":
                _method_checkpoint_control(conn, ha, approval_id, ok=False)
            return {"found": True, "executed": False, "status": "rejected",
                    "approver": user_id, "decided_at": _iso(rejected.get("decided_at"))}

        # ── ok=True → CLAIM ATÓMICO ANTES DE EJECUTAR (cierre del doble-gasto) ──────────────
        # held→executing en UN UPDATE condicional. Bajo N requests concurrentes, SOLO el ganador
        # del claim recibe la fila; el resto ve None y devuelve already_decided SIN tocar Gmail/
        # pago. Esto serializa el efecto externo a EXACTAMENTE-UNA-VEZ.
        claimed = phase1_repo.claim_held_action(conn, approval_id)
        if claimed is None:
            cur = phase1_repo.get_held_action(conn, approval_id) or {}
            return {"found": True, "executed": cur.get("status") == "executed",
                    "status": cur.get("status"), "already_decided": True}

        # ── PIEZA MÉTODO · CHECKPOINT SENTINELA (server='metodo'): la card B4 decide
        # el checkpoint del arnés — NO hay tool que ejecutar (execute_held_tool
        # intentaría arrancar un server inexistente). El claim atómico ya serializó
        # exactamente-una-vez; se sella 'executed' (=aprobado) y la decisión queda
        # TAMBIÉN en method_runs.control (por si el run ya cortó esperando).
        if claimed.get("server") == "metodo" and claimed.get("tool") == "checkpoint":
            done = phase1_repo.decide_held_action(
                conn, approval_id, status="executed",
                result=(f"checkpoint aprobado por {user_id}" if user_id
                        else "checkpoint aprobado"), expect="executing")
            _method_checkpoint_control(conn, claimed, approval_id, ok=True)
            return {"found": True, "executed": False, "status": "executed",
                    "checkpoint": True, "approver": user_id,
                    "decided_at": _iso((done or {}).get("decided_at"))}

        # SOLO el ganador del claim llega acá. Ejecuta con la recipe/args PERSISTIDOS (los que
        # el dueño vio — integridad HELD↔OK), credencial del BROKER REAL ligado al dueño.
        from app.phase1 import credential_broker
        resolver = credential_broker.make_user_resolver(
            claimed.get("user_id"), get_conn=phase1_repo.get_conn)
        # MURALLA PREMIUM · el tier del gate al EJECUTAR sale de la CUENTA del DUEÑO de la held
        # (fresh del DB, no de recipe.tier que el cliente edita). Un level 'blocked'/'tier_block'
        # NO se ejecuta ni con OK si la cuenta no es premium. Fail-closed: si no resuelve el tier,
        # None → build_enforced_gate lo mapea a 'average' (bloquea). Premium bloqueado por error
        # (molesto) > premium abierto por error (te vacían el moat).
        _held_tier = None
        try:
            _htu = phase1_repo.get_user(conn, claimed.get("user_id"))
            _held_tier = (_htu or {}).get("tier")
        except Exception:
            try:
                conn.rollback()   # no envenenar la txn para el decide_held_action de abajo
            except Exception:
                pass
            _held_tier = None
        try:
            res = _asm().execute_held_tool(
                claimed["recipe"], claimed["server"], claimed["tool"], claimed["args"],
                repo_root=_RESOURCE_ROOT, byok_resolver=resolver,
                account_tier=_held_tier,
            )
        except Exception as exc:
            # Excepción inesperada TRAS el claim (caveat #1): revertir executing→held para que el
            # dueño pueda reintentar — no perder la acción ni dejarla colgada en 'executing'.
            phase1_repo.decide_held_action(
                conn, approval_id, status="held",
                result=f"error de ejecución: {type(exc).__name__}: {exc}"[:4000],
                expect="executing")
            return {"found": True, "executed": False, "status": "held",
                    "error": f"ejecución falló: {type(exc).__name__}"}

        if res.get("executed"):
            # A2 · bitácora: decided_at (timestamp durable) + approver (user_id, anclado por
            # anti-IDOR = dueño) se surfacean en la respuesta; la política vive en recipe.autonomy.
            # TICKET 36 · auditabilidad: si fue una escritura FORJADA disparada por el ejecutor
            # confiable, el `result` durable guarda el EFECTO REAL + la request armada que se pegó.
            _armed = res.get("armed_request")
            _durable = (json.dumps({"effect": res.get("result"), "armed_request": _armed},
                                   ensure_ascii=False, default=str)
                        if _armed is not None else str(res.get("result")))
            decided = phase1_repo.decide_held_action(
                conn, approval_id, status="executed",
                result=_durable[:4000], expect="executing")
            return {"found": True, "executed": True, "status": "executed",
                    "result": res.get("result"), "armed_request": _armed,
                    "approver": user_id, "decided_at": _iso((decided or {}).get("decided_at"))}
        # Falló la ejecución (sin excepción) — caveat #1: revertir executing→held para reintentar.
        phase1_repo.decide_held_action(
            conn, approval_id, status="held",
            result=(res.get("error") or "no se pudo ejecutar")[:4000], expect="executing")
        return {"found": True, "executed": False, "status": "held",
                "error": res.get("error") or "no se pudo ejecutar la acción"}
    finally:
        if own_conn and conn is not None:
            conn.close()


__all__ = ["run_puppet_e2e", "build_trajectory_from_record", "approve_held_action"]
