"""
mesa/almacen.py — persistencia del borrador retomable (filesystem, aislado por-principal).

Espeja la coherencia del resto de synth_belts: filesystem, no Postgres. Cada construcción es
`data/construcciones/<namespace>/<construccion_id>/snapshot.json`, donde <namespace> sale del
Principal (u/<user> | anon/<hash>) — dos principals distintos NO comparten borradores (mismo
aislamiento que el vault de credenciales).

Escritura ATÓMICA (write-to-temp + os.replace) para que un corte a mitad de escritura no deje
un snapshot corrupto — el borrador es justamente la red contra los cortes.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.mesa.modelos import Snapshot  # noqa: E402

#: dir AISLADO y gitignored, hermano de synth_belts / capture_library.
CONSTRUCCIONES_DIR: Path = C.SYNTH_BELTS_DIR.parent / "construcciones"


# root se resuelve en tiempo de LLAMADA (no como default congelado al import) → el módulo es
# parcheable en tests (almacen.CONSTRUCCIONES_DIR = tmp) y un solo lugar define el default.
def _root(root: Path | None) -> Path:
    return root if root is not None else CONSTRUCCIONES_DIR


def _dir_de(principal: C.Principal, construccion_id: str, *, root: Path | None = None) -> Path:
    return _root(root) / C.credential_namespace(principal) / construccion_id


def _snapshot_path(principal: C.Principal, construccion_id: str, *, root: Path | None = None) -> Path:
    return _dir_de(principal, construccion_id, root=root) / "snapshot.json"


def guardar(principal: C.Principal, snap: Snapshot, *, root: Path | None = None) -> Path:
    """Escribe el snapshot de forma ATÓMICA. Devuelve el path escrito."""
    path = _snapshot_path(principal, snap.construccion_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(snap.to_dict(), ensure_ascii=False, indent=1)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".snap-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)   # atómico dentro del mismo filesystem
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return path


def cargar(principal: C.Principal, construccion_id: str, *, root: Path | None = None) -> Optional[Snapshot]:
    """Lee el snapshot de una construcción del principal, o None si no existe."""
    path = _snapshot_path(principal, construccion_id, root=root)
    if not path.exists():
        return None
    try:
        return Snapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def listar(principal: C.Principal, *, root: Path | None = None) -> list[Snapshot]:
    """Todos los borradores del principal, más recientes primero."""
    base = _root(root) / C.credential_namespace(principal)
    if not base.exists():
        return []
    out: list[Snapshot] = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        snap_path = child / "snapshot.json"
        if not snap_path.exists():
            continue
        try:
            out.append(Snapshot.from_dict(json.loads(snap_path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    out.sort(key=lambda s: s.tocada_en, reverse=True)
    return out


__all__ = ["CONSTRUCCIONES_DIR", "guardar", "cargar", "listar"]
