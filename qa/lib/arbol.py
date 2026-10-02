#!/usr/bin/env python3
"""arbol.py — UNA VARA NO SABE EN QUÉ WORKTREE LA CORRIERON.

══ [H5b · 2026-08-08] EL AGUJERO, MEDIDO EN LA REGRESIÓN DE ESTA FASE ═════════════════
Dos varas verdes en `<repo-a>` y rojas en `<repo-b>`, por la
misma causa:

    qa/verify_probar_por_familia.py:129   FileNotFoundError:
        '<repo>/product/backend/.venv/bin/python'
    qa/verify_sala_restaura_byok_front.mjs
        {"1_positivo":{"ok":false,"detalle":"sin venv del backend"}}

`product/backend/.venv` es un artefacto local: existe en el árbol principal y **no viaja**
a un worktree, igual que `node_modules` (ver `deps_node.py`, el mismo agujero del lado de
Node). Una vara que arma `RAIZ / "product/backend/.venv/bin/python"` está afirmando que la
corrieron desde el árbol principal, y eso no se lo puede prometer nadie.

Peor que romper: **rompe distinto**. Una tira `FileNotFoundError`, la otra se anota a sí
misma `ok:false` con «sin venv del backend» — que se lee como un fallo del producto y no
como un intérprete que no está donde la vara creía.

  ══ EL ORDEN DE BÚSQUEDA, Y POR QUÉ ═════════════════════════════════════════════════
    1. el venv del árbol PROPIO — si el worktree tiene el suyo, es el que corresponde;
    2. el venv del árbol PRINCIPAL, ubicado con `git rev-parse --git-common-dir`;
    3. `sys.executable` — el intérprete con el que ya estamos corriendo.
  El (3) importa: si alguien corrió la vara con el venv de producción, ese intérprete YA
  tiene lo que hace falta, y pedirle un path fijo era pedirle de más.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

__all__ = ["principal", "venv_python", "hay_venv_propio"]


def principal(desde: Path | None = None) -> Path | None:
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


def _candidato(raiz: Path) -> Path:
    return raiz / "product" / "backend" / ".venv" / "bin" / "python"


def hay_venv_propio(arbol: Path | None = None) -> bool:
    arbol = arbol or Path(__file__).resolve().parents[2]
    return _candidato(arbol).exists()


def venv_python(arbol: Path | None = None) -> str:
    """El intérprete del backend que SÍ existe. Nunca devuelve un path inexistente."""
    arbol = arbol or Path(__file__).resolve().parents[2]
    propio = _candidato(arbol)
    if propio.exists():
        return str(propio)
    p = principal(arbol)
    if p is not None:
        ajeno = _candidato(p)
        if ajeno.exists():
            return str(ajeno)
    return sys.executable


if __name__ == "__main__":
    _arbol = Path(__file__).resolve().parents[2]
    print(f"árbol:      {_arbol}")
    print(f"principal:  {principal(_arbol)}")
    print(f"venv propio:{' sí' if hay_venv_propio(_arbol) else ' no'}")
    print(f"python:     {venv_python(_arbol)}")
