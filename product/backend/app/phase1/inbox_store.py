"""inbox_store.py — EL INBOX DE LA CONVERSACIÓN. [T2.5c · adjuntar documentos]

QUÉ ES, Y POR QUÉ NO ES UN DATA-URL
-----------------------------------
Un adjunto no es un mensaje: es un ARCHIVO que el turno siguiente también tiene que poder
mirar. Mandarlo como data-URL adentro del prompt lo ata a ESE turno —y encima sólo sirve
para imágenes, porque es el único campo que el modelo multimodal consume—. Acá el archivo
se ESCRIBE, y al agente le llega una RUTA.

Es el patrón de Oficina, medido antes de copiarlo
(`third_party/openwork/apps/app/src/react-app/domains/session/sync/attachment-file-part.ts`):
sube el archivo a un inbox del workspace y le pasa al agente la ruta. Y encaja con lo que
la casa YA tiene: MEDIDO el 2026-08-19 (`qa/verify_kit_lee_documentos.py`), el kit lee
pdf · docx · xlsx con `markitdown.convert_to_markdown` y csv/txt con
`filesystem.read_text_file`, keyless y sin red. No hace falta ningún lector nuevo — hacía
falta que el archivo existiera en algún lado.

EL DUEÑO Y EL AISLAMIENTO SON ESTRUCTURALES, no un chequeo
----------------------------------------------------------
La ruta es `data_root()/inbox/<dueño>/<sesión>/`. Los archivos de un usuario no están en el
árbol de otro: no hay una comparación que se pueda olvidar. Y una sesión no ve los archivos
de otra salvo que alguien lo pida explícitamente, porque su carpeta es otra.

El dueño se guarda HASHEADO (sha256, 24 hex). No es paranoia: `data_root()` puede terminar
en un backup, un log de `ls` o una captura de pantalla, y un `user_id` en el nombre de una
carpeta es un identificador de persona a la intemperie. El hash aísla igual y no cuenta
nada de quién es.

LO QUE SE COPIA DE `artifact_store` (el precedente de persistencia con dueño de la casa):
  · rutas bajo `aleph_paths.data_root()` — jamás aritmética de `parents[N]`, que bajo
    PyInstaller cae DENTRO de `_MEIPASS` y se borra al cerrar la app (censo §J.1).
  · escritura ATÓMICA (tmp + `os.replace`): un proceso que muere a mitad no deja medio
    archivo que después alguien lee como si estuviera entero.
  · `flock` alrededor del índice: dos pestañas de la misma sesión comparten carpeta.
  · `sha256` del contenido: la integridad se puede comprobar, no se promete.

LO QUE NO HACE, A PROPÓSITO
  · No convierte nada. Guardar es guardar; leer es del kit. Un convertidor acá sería una
    segunda opinión sobre `markitdown`.
  · No borra por su cuenta. Un adjunto que desaparece solo es peor que uno que ocupa disco:
    el usuario preguntó por él dos turnos después y ya no está.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

#: Tope por archivo. No es gusto: el body del POST lo sostiene el proceso en memoria, y un
#: archivo enorme no es «lento», es un server que se cae. Se corta con causa visible.
MAX_BYTES = 25 * 1024 * 1024

#: Tope por sesión: el inbox persiste a propósito, así que sin techo crece para siempre.
MAX_BYTES_SESION = 200 * 1024 * 1024

_INDICE = "_inbox.json"

#: extensión → MIME. Espeja el mapa de Oficina (`attachment-file-part.ts`), que ya resolvió
#: esto para 30+ extensiones. Se declara acá y no se deduce con `mimetypes` porque el mapa
#: de la stdlib varía por máquina (lee `/etc/mime.types`) y eso hace que el mismo archivo
#: se clasifique distinto en dos computadoras.
MIME_POR_EXT: dict[str, str] = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain", "md": "text/markdown", "markdown": "text/markdown",
    "csv": "text/csv", "tsv": "text/tab-separated-values",
    "json": "application/json", "jsonl": "application/json",
    "xml": "application/xml", "yaml": "text/yaml", "yml": "text/yaml",
    "html": "text/html", "htm": "text/html", "css": "text/css",
    "js": "application/javascript", "ts": "text/plain", "py": "text/plain",
    "sh": "text/plain", "sql": "text/plain", "log": "text/plain",
    "toml": "text/plain", "ini": "text/plain", "conf": "text/plain",
}

_GENERICO = "application/octet-stream"


class InboxError(Exception):
    """Fallo tipado y VISIBLE (jamás un silencio). El router mapea `code` → HTTP."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _data_root() -> Path:
    try:
        import aleph_paths
        return aleph_paths.data_root()
    except Exception:
        # Mismo respaldo que artifact_store: en un checkout pelado, el árbol.
        return Path(__file__).resolve().parents[4] / "product" / "backend" / "data"


def _safe(s: str, largo: int = 120) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]", "_", str(s or "").strip())[:largo]
    return out or "default"


def _dueno_dir(owner: str) -> str:
    """El dueño, hasheado. Aísla igual y no deja el id de una persona en una ruta."""
    o = str(owner or "").strip()
    if not o:
        raise InboxError("sin_dueno", "Un adjunto necesita saber de quién es.")
    return hashlib.sha256(o.encode("utf-8")).hexdigest()[:24]


def dir_de(owner: str, session_id: str) -> Path:
    """La carpeta de ESTA sesión de ESTE dueño. Se crea si no está."""
    d = _data_root() / "inbox" / _dueno_dir(owner) / _safe(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _nombre_seguro(filename: str) -> str:
    """El nombre que llega del cliente NO se usa como ruta.

    Se le saca todo separador y todo `..` antes de tocar el disco: un `../../aleph.db` en
    `filename` es el camino más corto a escribir fuera del inbox. Se conserva la extensión
    porque de ella sale el MIME —y porque el agente la necesita para saber qué está mirando.
    """
    base = os.path.basename(str(filename or "").replace("\\", "/"))
    base = base.replace("..", "_")
    limpio = _safe(base, 96)
    if "." not in limpio:
        return limpio
    tallo, _, ext = limpio.rpartition(".")
    return f"{tallo or 'archivo'}.{_safe(ext, 12).lower()}"


def mime_de(nombre: str) -> str:
    ext = nombre.rpartition(".")[2].lower() if "." in nombre else ""
    return MIME_POR_EXT.get(ext, _GENERICO)


def _indice_path(d: Path) -> Path:
    return d / _INDICE


def _leer_indice(d: Path) -> list:
    p = _indice_path(d)
    if not p.exists():
        return []
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
        return datos.get("archivos", []) if isinstance(datos, dict) else []
    except (OSError, ValueError):
        # Índice corrupto: se RENOMBRA y se sigue. Descartarlo en silencio perdería la
        # lista sin que nadie se entere (B-9). Los archivos en disco no se tocan.
        try:
            p.rename(p.with_name(p.name + f".corrupt-{int(time.time())}"))
        except OSError:
            pass
        return []


def _escribir_indice(d: Path, archivos: list) -> None:
    p = _indice_path(d)
    tmp = p.with_name(p.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps({"schema_version": 1, "archivos": archivos},
                              ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


class _Candado:
    """flock alrededor del índice: dos pestañas de la misma sesión comparten carpeta."""

    def __init__(self, d: Path):
        self._p = d / ".lock"
        self._fh = None

    def __enter__(self):
        self._fh = open(self._p, "a+")
        try:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except Exception:                                  # noqa: BLE001 — sin flock se sigue
            pass
        return self

    def __exit__(self, *_exc):
        try:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except Exception:                                  # noqa: BLE001
            pass
        try:
            self._fh.close()
        except Exception:                                  # noqa: BLE001
            pass
        return False


def guardar(owner: str, session_id: str, filename: str, datos: bytes) -> dict:
    """Escribe un adjunto y devuelve su ficha. Atómico; nunca pisa en silencio.

    Un nombre repetido NO sobrescribe: se le agrega un sufijo. Pisar el archivo anterior
    borraría algo que el usuario podría estar por preguntar — y sin avisarle.
    """
    if not isinstance(datos, (bytes, bytearray)) or not datos:
        raise InboxError("vacio", "Ese archivo llegó vacío.")
    if len(datos) > MAX_BYTES:
        raise InboxError("muy_grande",
                         f"Ese archivo pesa más de {MAX_BYTES // (1024 * 1024)} MB.")

    d = dir_de(owner, session_id)
    with _Candado(d):
        archivos = _leer_indice(d)
        usados = sum(int(a.get("bytes") or 0) for a in archivos)
        if usados + len(datos) > MAX_BYTES_SESION:
            raise InboxError(
                "sesion_llena",
                f"Esta conversación ya juntó {MAX_BYTES_SESION // (1024 * 1024)} MB de "
                f"adjuntos. Quita alguno o inicia una conversación nueva.")

        nombre = _nombre_seguro(filename)
        destino = d / nombre
        if destino.exists():
            tallo, _, ext = nombre.rpartition(".")
            n = 2
            while destino.exists():
                nombre = f"{tallo or 'archivo'}-{n}" + (f".{ext}" if ext else "")
                destino = d / nombre
                n += 1

        tmp = destino.with_name(destino.name + f".tmp-{os.getpid()}")
        tmp.write_bytes(bytes(datos))
        os.replace(tmp, destino)

        ficha = {
            "nombre": nombre,
            "ruta": str(destino),
            "bytes": len(datos),
            "mime": mime_de(nombre),
            "sha256": hashlib.sha256(bytes(datos)).hexdigest(),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        archivos.append(ficha)
        _escribir_indice(d, archivos)
    return ficha


def listar(owner: str, session_id: str) -> list:
    """Los adjuntos de esta sesión. Sólo los que SIGUEN en disco: una ficha cuyo archivo
    no está es una promesa rota, y devolverla haría que el agente pida una ruta muerta."""
    d = dir_de(owner, session_id)
    with _Candado(d):
        return [a for a in _leer_indice(d) if a.get("ruta") and Path(a["ruta"]).exists()]


def quitar(owner: str, session_id: str, nombre: str) -> bool:
    """Saca un adjunto (archivo + ficha). Sólo por nombre, y saneado: el nombre viene del
    cliente y jamás se usa como ruta."""
    d = dir_de(owner, session_id)
    seguro = _nombre_seguro(nombre)
    with _Candado(d):
        archivos = _leer_indice(d)
        quedan = [a for a in archivos if a.get("nombre") != seguro]
        if len(quedan) == len(archivos):
            return False
        try:
            (d / seguro).unlink(missing_ok=True)
        except OSError:
            pass
        _escribir_indice(d, quedan)
    return True


__all__ = ["InboxError", "MAX_BYTES", "MAX_BYTES_SESION", "MIME_POR_EXT",
           "dir_de", "mime_de", "guardar", "listar", "quitar"]
