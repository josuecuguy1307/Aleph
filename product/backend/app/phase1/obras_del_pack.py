"""obras_del_pack.py — EL ALMACÉN PROPIO DE UN PACK, LEÍDO POR LA CASA.

[Educación · los artefactos · cortes 3 y 4]

EL AGUJERO QUE TAPA, Y POR QUÉ NO ES EL MISMO QUE EL DE FINANZAS
────────────────────────────────────────────────────────────────
`artefactos_del_borde.py` cosecha los `role:"tool"` que cruzan el borde. Sirve para un
stack cuyas tools devuelven JSON —Finanzas hace `json.dumps` (`market_data.py:228`)— y
**no puede servir para Educación**, medido: su harness arma el mensaje con
`"content": result_text` (`core/agentic/tool_dispatch.py:637-645`), que es la PROSA que
lee el modelo, y lo estructurado se queda en `metadata` / `tool_metadata_by_id`, que no
cruzan el protocolo OpenAI. Barridas las **19** clases de tool de
`deeptutor/tools/builtin/__init__.py`: **ninguna** pone `json.dumps` adentro de
`ToolResult(content=…)`. O sea que por el borde no hay nada que abrir, ni hoy ni con una
fila nueva.

Y hay un segundo corte que una fila tampoco arregla: los entregables de verdad del tutor
—el ejercicio, el informe de investigación, la visualización, la ruta de estudio, la
solución— **no son resultados de tool**: son resultados de CAPACIDAD, y nunca aparecen
como `role:"tool"`. El borde sólo ve pasos de LLM.

EL MECANISMO YA EXISTÍA; FALTABA EL LECTOR
──────────────────────────────────────────
Antes de escribir un canal nuevo se fue a buscar si el stack ya escribía esto en algún
lado. **Lo escribe, y en un solo lugar, para TODO turno — de chat y de capacidad.**
`services/session/turn_runtime.py` persiste cada respuesta del asistente con:

  · `capability`       — qué capacidad la produjo (`:1717 capability=capability_name`)
  · `attachments_json` — los archivos generados, con `url` · `filename` · `mime_type` ·
                         `size_bytes`, armados por `artifact_attachments.py` **justo
                         para** que la UI pueda pintar tarjetas abribles (`:1719`)
  · `events_json`      — el stream entero del turno, y ahí adentro va el evento `result`
                         que `emit_capability_result` emite (`stream.result(payload)`,
                         `agents/_shared/capability_result.py:46`)

MEDIDO sobre el `chat_history.db` REAL del dueño (51 mensajes): `events_json` guarda
**24 eventos `result`**, con `source` = la capacidad y `metadata` = su payload
(`{response, completed, engine, rounds, tool_steps, metadata}` para `chat`). El canal no
sólo existe: ya está lleno.

Y LAS CINCO CAPACIDADES COMPARTEN UN CAMPO, `response`, que es el texto que el usuario
ve — leído de los cinco emisores, uno por uno:
    chat            `agents/chat/agent_loop.py:247`            (además MEDIDO en disco)
    deep_research   `agents/research/pipeline.py:617`          el informe entero
    deep_question   `agents/question/pipeline.py:1274`         el enunciado / preface
    visualize       `agents/visualize/capability.py:265`       el bloque cercado
    math_animator   `agents/math_animator/capability.py:203`   el resumen
Por eso el destino de una capacidad es UNA fila del puente, la que ya existía —
`bridge.TABLE["educacion"]["report"]`— y no cinco filas nuevas: se adapta la FORMA (el
texto pasa a `content`), jamás el dato.

LO QUE ESTE MÓDULO **NO** HACE
──────────────────────────────
  · No traduce: eso es del puente, y sigue siéndolo. Acá se decide QUÉ es una obra.
  · No autoriza: el dueño del `sid` se verifica río arriba, en el borde.
  · No adivina rutas ni clases: **las declara la tabla de abajo**, workspace por
    workspace. Un workspace que no está no lee nada — cero regresión para los otros cinco.
  · No escribe en el almacén del pack: abre sqlite en `mode=ro`. El store es del stack.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

log = logging.getLogger("aleph.obras_del_pack")

try:
    import aleph_paths as _ap
except ImportError:  # pragma: no cover — dev sin `platform/` en el path
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

#: El prefijo con el que el stack acuña la URL de un artefacto
#: (`services/sandbox/artifacts.py`: `"/api/outputs/" + quote(relative_path)`). Es la
#: única referencia que el registro guarda, así que es por donde se vuelve al archivo.
_PREFIJO_SALIDAS = "/api/outputs/"

#: Un archivo más grande que esto no viaja con sus bytes: cruza como FICHA. No es una
#: opinión de producto — es el techo que evita meterle 40 MB de base64 a un artefacto que
#: después hay que pintar. La ficha dice nombre, tamaño y ruta, que es la verdad.
TOPE_BYTES = 4_000_000

#: `workspace → cómo se lee SU almacén`. Todo declarado, nada inferido.
#:
#: `raiz` son los segmentos DESDE `pack.raiz_pack(ws)` — y no salen de una intuición:
#: `pack.py:2536-2539` dice, con todas las letras, que para `config_format == "deeptutor"`
#: el `DEEPTUTOR_HOME` es `raiz_pack(ws) / "runtime"`. De ahí para abajo manda el
#: `PathService` del stack: `get_public_outputs_root()` devuelve su `_user_data_dir`, o sea
#: `<home>/data/user`, y el store de sesiones vive en `<home>/data/user/chat_history.db`.
#: MEDIDO contra la máquina del dueño: ahí está el archivo, con 51 mensajes.
#:
#: `capacidades` mapea la capacidad del stack al `kind` del puente. `chat` va a `None` A
#: PROPÓSITO: su respuesta ya viaja al hilo de la casa por `hilo_workspace`, y volver a
#: guardarla como obra sería el mismo texto dos veces en dos superficies.
#:
#: `clases` mapea la EXTENSIÓN del archivo generado a su `kind`. Es el mismo criterio que
#: `claseDe()` de `openwork.js:127-136`, que ya se midió contra un stack vivo; lo que
#: cambia es de dónde sale el archivo, no cómo se lo nombra.
ALMACEN_POR_WORKSPACE: dict[str, dict] = {
    "educacion": {
        "raiz": ("runtime",),
        "publico": ("data", "user"),
        "db": ("data", "user", "chat_history.db"),
        "capacidades": {
            "chat": None,
            "deep_research": "report",
            "deep_question": "report",
            "deep_solve": "report",
            "mastery_path": "report",
            "visualize": "report",
            "math_animator": "report",
        },
        "clases": {
            "png": "figura", "jpg": "figura", "jpeg": "figura", "webp": "figura",
            "gif": "figura", "svg": "figura",
            "csv": "planilla",
            "md": "documento", "txt": "documento", "json": "documento",
            "py": "documento", "html": "documento",
        },
        "por_defecto": "archivo",
    },
}


def almacen_de(workspace: Any) -> dict:
    """La declaración de ese workspace. Desconocido → vacío, o sea: no pasa nada.

    Tolera `None`, `""` y mayúsculas por la misma razón que su gemela de
    `artefactos_del_borde`: el nombre llega por cabecera HTTP y un mapa que se pierde por
    un rótulo con otra caja sería el fallo mudo que esto viene a evitar.
    """
    if not isinstance(workspace, str):
        return {}
    return ALMACEN_POR_WORKSPACE.get(workspace.strip().casefold(), {})


def raiz_del_pack(workspace: str) -> Path:
    """La raíz del pack, con la MISMA regla que `pack.raiz_pack`.

    Se replica la línea en vez de importar `workspaces.pack`: ese módulo levanta procesos
    y pesa 158 KB, y este archivo tiene que poder importarse en una vara sin arrastrarlo.
    `qa/verify_obras_del_pack.py` compara las dos rutas y se pone roja si divergen — que
    es más de lo que un comentario pidiendo sincronía puede prometer.
    """
    return _ap.user_data_dir() / "workspaces" / str(workspace or "")


def ruta_del_almacen(workspace: str) -> Optional[Path]:
    """El `chat_history.db` de ese pack, o `None` si el workspace no declara almacén."""
    decl = almacen_de(workspace)
    if not decl:
        return None
    return raiz_del_pack(workspace).joinpath(*decl["raiz"], *decl["db"])


def _raiz_publica(workspace: str) -> Optional[Path]:
    decl = almacen_de(workspace)
    if not decl:
        return None
    return raiz_del_pack(workspace).joinpath(*decl["raiz"], *decl["publico"])


def _archivo_de_url(url: str, publica: Path) -> Optional[Path]:
    """La URL `/api/outputs/...` de vuelta a su archivo, con la MISMA guarda que el stack.

    Es la contraparte de `artifact_attachments._resolve_artifact_path`: sin el `relative_to`
    una URL con `..` adentro saldría del workspace público, y este módulo estaría leyendo
    archivos del disco del dueño por pedido de un proceso ajeno. La guarda no es defensa
    de más: la URL viene de un registro que escribe OTRO programa.
    """
    if not url.startswith(_PREFIJO_SALIDAS):
        return None
    try:
        candidato = (publica / unquote(url[len(_PREFIJO_SALIDAS):])).resolve()
        candidato.relative_to(publica.resolve())
    except (ValueError, OSError):
        return None
    return candidato if candidato.is_file() else None


def _clase_de(nombre: str, decl: dict) -> str:
    ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    return decl["clases"].get(ext, decl["por_defecto"])


def _cuerpo(camino: Path, kind: str) -> dict:
    """Los bytes del archivo, en el sobre que el puente sabe abrir — o sólo su ficha.

    LA REGLA: un archivo de texto viaja como texto (`encoding: "utf8"`), uno binario en
    base64, y uno demasiado grande **no viaja**: cruza como ficha, que dice la verdad
    (nombre, tamaño, ruta) en vez de reventar un artefacto con 40 MB adentro.
    """
    try:
        tam = camino.stat().st_size
    except OSError:
        return {}
    base = {"name": camino.name, "size": tam, "path": str(camino),
            "format": camino.suffix.lstrip(".").lower()}
    if tam > TOPE_BYTES:
        return base
    try:
        crudo = camino.read_bytes()
    except OSError:
        return base
    if kind in ("planilla", "documento", "report"):
        try:
            return {**base, "content": crudo.decode("utf-8"), "encoding": "utf8"}
        except UnicodeDecodeError:
            # Declaró texto y no es texto: NO se fuerza. Cae a ficha, que es honesto.
            return base
    if kind == "figura":
        if camino.suffix.lower() == ".svg":
            try:
                return {**base, "content": crudo.decode("utf-8"), "encoding": "utf8"}
            except UnicodeDecodeError:
                return base
        return {**base, "content": base64.b64encode(crudo).decode("ascii"),
                "encoding": "base64"}
    return base


def _huella(kind: str, nombre: str, data: dict) -> str:
    """sha256 del DATO, no del id de la fila.

    Igual que en `artefactos_del_borde`: el mismo archivo referido desde dos mensajes es
    UNA obra, y un reintento que produce los mismos bytes no debe dejar una copia. Cuando
    los bytes no viajan (ficha), la huella se arma con tamaño y ruta, que es lo que hay.
    """
    firma = data.get("content")
    if not isinstance(firma, str):
        firma = "%s\x1f%s" % (data.get("path", ""), data.get("size", ""))
    return hashlib.sha256(("%s\x1f%s\x1f%s" % (kind, nombre, firma)).encode("utf-8")).hexdigest()


def leer(workspace: Any, *, desde: int = 0, tope_filas: int = 200) -> list:
    """Las obras que el almacén del pack tiene y la casa todavía no.

    Devuelve `[{"kind", "fuente", "name", "data", "huella", "mensaje"}]` — la MISMA forma
    que devuelve `artefactos_del_borde.cosechar`, para que el borde no tenga dos caminos
    de escritura. `fuente` dice si salió de un archivo generado o de una capacidad.

    NUNCA LEVANTA. El almacén es de otro programa: puede no existir, estar a medio
    escribir, tener otro esquema mañana o estar bloqueado por el propio stack. Todo eso
    sale por el mismo lado —lista vacía— y el turno sigue. Un artefacto perdido es malo;
    un turno tumbado por ir a buscarlo es peor.
    """
    decl = almacen_de(workspace)
    if not decl:
        return []
    ruta = ruta_del_almacen(str(workspace))
    publica = _raiz_publica(str(workspace))
    if not ruta or not ruta.is_file() or not publica:
        return []
    filas: list = []
    try:
        # `mode=ro` y `immutable=0`: se LEE un store vivo que otro proceso está usando.
        # Abrirlo de lectura-escritura crearía un `-wal` nuestro al lado del suyo.
        con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=2.0)
        try:
            cur = con.execute(
                "select id, capability, attachments_json, events_json from messages "
                "where role = 'assistant' and id > ? order by id limit ?",
                (int(desde or 0), int(tope_filas)))
            filas = cur.fetchall()
        finally:
            con.close()
    except Exception as exc:                              # noqa: BLE001 — store ajeno
        log.info("obras_del_pack: no se pudo leer %s — %s", ruta, exc)
        return []

    out: list = []
    # ⚠️ LA DEDUPLICACIÓN VA ACÁ ADENTRO, y la encontró la vara: el MISMO archivo se
    # referencia desde varios mensajes (el turno que lo generó y el que lo cita después),
    # así que sin esto una gráfica dejaba dos obras iguales en la Biblioteca. El memo del
    # borde (`artefactos_del_borde.es_nueva`) también la habría atajado, pero es por chat
    # y en proceso: la lista que sale de acá tiene que estar limpia POR SÍ MISMA, o
    # cualquier otro llamador hereda el duplicado. Es la misma `vistas` que ya usa
    # `cosechar`, por el mismo motivo.
    vistas: set = set()
    for mid, capacidad, adjuntos, eventos in filas:
        # ── los ARCHIVOS que el turno generó ───────────────────────────────────────────
        for entrada in _lista(adjuntos):
            url = str(entrada.get("url") or "")
            camino = _archivo_de_url(url, publica)
            if camino is None:
                continue
            nombre = str(entrada.get("filename") or camino.name)
            kind = _clase_de(nombre, decl)
            data = _cuerpo(camino, kind)
            if not data:
                continue
            huella = _huella(kind, nombre, data)
            if huella in vistas:
                continue                 # el mismo archivo, citado desde otro mensaje
            vistas.add(huella)
            out.append({"kind": kind, "fuente": "archivo", "name": nombre, "data": data,
                        "huella": huella, "mensaje": mid})
        # ── y lo que la CAPACIDAD entregó ──────────────────────────────────────────────
        kind_cap = (decl["capacidades"] or {}).get(str(capacidad or ""))
        if not kind_cap:
            continue                     # capacidad no declarada, o declarada como `None`
        texto = _respuesta_de(eventos)
        if not texto:
            continue
        nombre = "%s · %s" % (workspace, capacidad)
        data = {"name": nombre, "content": texto}
        huella = _huella(kind_cap, nombre, data)
        if huella in vistas:
            continue                     # la misma entrega, repetida en el store
        vistas.add(huella)
        out.append({"kind": kind_cap, "fuente": "capacidad", "name": nombre, "data": data,
                    "huella": huella, "mensaje": mid})
    return out


def _lista(crudo: Any) -> list:
    """El JSON de un campo del store ajeno, o vacío. Nunca levanta."""
    if isinstance(crudo, (list, tuple)):
        return [x for x in crudo if isinstance(x, dict)]
    if not isinstance(crudo, str) or not crudo.strip():
        return []
    try:
        d = json.loads(crudo)
    except (ValueError, TypeError):
        return []
    return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []


def _respuesta_de(eventos: Any) -> str:
    """El `response` del evento `result` del turno — el texto que el usuario vio.

    ⚠️ EL EVENTO SE LLAMA `result`, NO `capability_result`. Perdí una vuelta buscando el
    segundo: `emit_capability_result` termina en `stream.result(payload)`
    (`agents/_shared/capability_result.py:46`), así que el `type` que queda escrito es
    `result` y el nombre de la capacidad viaja en `source`. Buscar el nombre de la función
    en vez del nombre del evento da cero sobre un store que sí lo tiene.
    """
    for e in reversed(_lista(eventos)):
        if e.get("type") != "result":
            continue
        md = e.get("metadata")
        if isinstance(md, dict) and isinstance(md.get("response"), str):
            return md["response"].strip()
    return ""


__all__ = ["ALMACEN_POR_WORKSPACE", "almacen_de", "raiz_del_pack", "ruta_del_almacen",
           "leer", "TOPE_BYTES"]
