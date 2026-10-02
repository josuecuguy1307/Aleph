"""Identidad, containment y dueño inmutable de los espacios de eventos."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

_SPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_CLAIM = ".access.json"


class SpaceAccessError(ValueError):
    pass


def validate_space_id(space_id: str) -> str:
    value = str(space_id or "").strip()
    if not _SPACE_RE.fullmatch(value):
        raise SpaceAccessError("space_id inválido")
    return value


def space_dir(root: str | Path, space_id: str, *, create: bool = False) -> Path:
    sid = validate_space_id(space_id)
    base = Path(root).expanduser()
    if create:
        base.mkdir(parents=True, exist_ok=True)
    resolved_base = base.resolve(strict=False)
    candidate = resolved_base / sid
    if candidate.is_symlink():
        raise SpaceAccessError("el directorio del space no puede ser un symlink")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(resolved_base)
    except ValueError as exc:
        raise SpaceAccessError("space_id fuera de la raíz de espacios") from exc
    if create:
        resolved.mkdir(mode=0o700, parents=False, exist_ok=True)
        if resolved.is_symlink() or resolved.resolve(strict=True).parent != resolved_base:
            raise SpaceAccessError("directorio de space inseguro")
    return resolved


def _normalize_claim(raw: object) -> dict:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise SpaceAccessError("claim de space corrupto")
    public = raw.get("public") is True
    owner = str(raw.get("owner_id") or "").strip() or None
    if public == bool(owner):
        raise SpaceAccessError("claim de space ambiguo")
    return {"version": 1, "public": public, "owner_id": owner}


def read_claim(root: str | Path, space_id: str) -> Optional[dict]:
    directory = space_dir(root, space_id)
    path = directory / _CLAIM
    if not path.exists():
        return None
    if path.is_symlink():
        raise SpaceAccessError("claim de space no puede ser symlink")
    try:
        return _normalize_claim(json.loads(path.read_text(encoding="utf-8")))
    except SpaceAccessError:
        raise
    except Exception as exc:
        raise SpaceAccessError("claim de space corrupto") from exc


def claim_space(root: str | Path, space_id: str, *, owner_id: Optional[str] = None,
                public: bool = False) -> dict:
    owner = str(owner_id or "").strip() or None
    wanted = _normalize_claim({"version": 1, "public": bool(public), "owner_id": owner})
    directory = space_dir(root, space_id)
    created = False
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        created = True
    except FileExistsError:
        if directory.is_symlink():
            raise SpaceAccessError("el directorio del space no puede ser un symlink")
        existing = read_claim(root, space_id)
        if existing is None:
            # Un directorio heredado sin claim puede contener eventos sensibles. Adoptarlo
            # permitiría que el primero que adivine su id se atribuya su contenido.
            raise SpaceAccessError("space heredado sin dueño; requiere migración confiable")
        if existing != wanted:
            raise SpaceAccessError("el space ya pertenece a otro principal")
        return existing
    if directory.resolve(strict=True).parent != directory.parent.resolve(strict=True):
        if created:
            directory.rmdir()
        raise SpaceAccessError("directorio de space inseguro")
    path = directory / _CLAIM
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    payload = (json.dumps(wanted, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        existing = read_claim(root, space_id)
        if existing != wanted:
            raise SpaceAccessError("el space ya pertenece a otro principal")
        return existing
    except Exception:
        if created:
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    return wanted
