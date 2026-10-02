"""
_state.py — persistencia chiquita y atómica para la capa de safety (stdlib).

Un JSON por dominio (rate, blast, killswitch) bajo data/safety/, con lock de archivo
(fcntl) + escritura atómica (tmp+rename+fsync). No es una base de datos: es estado de
guard que debe sobrevivir reinicios y no corromperse bajo dos procesos (el recon corre
en subproceso aparte del backend). Mismo patrón que el event-store del org.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config

try:
    import fcntl  # POSIX (macOS/Linux) — el entorno del org
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover
    _HAVE_FCNTL = False


def _path(name: str) -> Path:
    config.ensure_safety_dir()
    return config.SAFETY_DIR / f"{name}.json"


@contextmanager
def locked(name: str) -> Iterator[dict[str, Any]]:
    """
    Abre el JSON `name` bajo lock exclusivo, lo entrega como dict mutable, y al salir
    lo persiste atómico. Crea {} si no existía.
    """
    p = _path(name)
    lock_path = p.with_suffix(".lock")
    lock_f = open(lock_path, "w")
    try:
        if _HAVE_FCNTL:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        data: dict[str, Any] = {}
        if p.exists():
            try:
                data = json.loads(p.read_text("utf-8") or "{}")
            except (json.JSONDecodeError, OSError):
                data = {}
        yield data
        # persistir atómico
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    finally:
        if _HAVE_FCNTL:
            try:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        lock_f.close()


def read(name: str) -> dict[str, Any]:
    """Lectura sin lock (snapshot best-effort para status/diagnóstico)."""
    p = _path(name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8") or "{}")
    except (json.JSONDecodeError, OSError):
        return {}


def now() -> float:
    return time.time()
