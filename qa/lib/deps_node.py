#!/usr/bin/env python3
"""deps_node.py — LAS VARAS DE NODE CORREN EN UN WORKTREE.

EL AGUJERO, MEDIDO (2026-08-08 sobre un worktree testigo):

    $ node product/app/design/sala/verify_slice_d_controls.mjs
    Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'playwright'

**140 varas `.mjs`** importan playwright. `node_modules/` no está en git —es un artefacto
local que vive sólo en el árbol principal— y `git worktree add` no lo copia. Así que
cualquier vara de navegador muere con un stack trace de Node en cuanto se la corre desde
un árbol que no sea el principal. Y un stack trace no es un rojo: quien lee `tail -1` ve
`Node.js v22.20.0` y no sabe si la obra está bien o mal.

No es «poner una nota en la cabecera de una vara»: son 140 archivos y el que las corre no
elige el árbol. Se resuelve donde se puede resolver una sola vez — un symlink al
`node_modules` del repo principal, que `git rev-parse --git-common-dir` sabe encontrar
desde cualquier worktree.

  · IDEMPOTENTE: si ya hay un `node_modules` (directorio real o symlink), no toca nada.
  · NO DESTRUCTIVO: nunca borra ni reemplaza.
  · HONESTO: si el principal tampoco lo tiene, lo dice y devuelve False. Un `npm install`
    no es algo que una vara deba disparar sola.

    product/backend/.venv/bin/python qa/lib/deps_node.py        # asegura + reporta
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

__all__ = ["repo_principal", "asegurar_node_modules"]


def repo_principal(desde: Path | None = None) -> Path | None:
    """El árbol de trabajo principal, visto desde cualquier worktree."""
    desde = desde or Path(__file__).resolve().parents[2]
    try:
        salida = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=desde, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if salida.returncode != 0:
        return None
    common = Path(salida.stdout.strip())
    return common.parent if common.name == ".git" else None


def asegurar_node_modules(arbol: Path | None = None) -> tuple[bool, str]:
    """(listo, motivo). `listo` = hay un `node_modules` alcanzable desde `arbol`."""
    arbol = arbol or Path(__file__).resolve().parents[2]
    propio = arbol / "node_modules"
    if propio.exists():
        return True, f"ya existe: {propio}"
    principal = repo_principal(arbol)
    if principal is None:
        return False, "no se pudo ubicar el árbol principal (¿esto es un repo git?)"
    if principal.resolve() == arbol.resolve():
        return False, f"el árbol principal es éste y no tiene node_modules: {propio}"
    origen = principal / "node_modules"
    if not origen.is_dir():
        return False, f"el árbol principal tampoco lo tiene: {origen} (falta un `npm install`)"
    try:
        os.symlink(origen, propio)
    except OSError as exc:
        return False, f"no se pudo enlazar {propio} → {origen}: {exc}"
    return True, f"enlazado: {propio} → {origen}"


if __name__ == "__main__":
    _listo, _motivo = asegurar_node_modules()
    print(("✓ " if _listo else "✗ ") + _motivo)
    sys.exit(0 if _listo else 1)
