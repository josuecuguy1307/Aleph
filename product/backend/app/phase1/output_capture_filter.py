"""
output_capture_filter.py — clasifica qué archivos de un workdir son OBRA REAL del agente
vs RUIDO (VCS / caches / build / deps) cuando el workdir resulta ser un repo.

POR QUÉ (T5 follow-up #5): `_capture_workdir_outputs` (executor.py) recorría con
`rglob('*')` y solo saltaba dotfiles de RAÍZ (`p.name.startswith('.')`), así que cuando el
agente trabaja sobre un repo git metía recursivamente `.git/**`, `.pytest_cache/**` y
`__pycache__/*.pyc` en la Biblioteca del usuario (~37 outputs basura en un run real). Esto
ensucia "Su obra" y entierra el artefacto real.

AISLADO A PROPÓSITO: módulo puro, sin DB, sin executor, sin PUPPET_BELTS. El wire a
executor._capture_workdir_outputs es de 1 línea (cambiar el loop por `captured_files(root)`),
para aplicarse cuando el carril que hoy edita executor.py confirme estabilidad. Stdlib only.
"""
from __future__ import annotations

from pathlib import Path

# Dirs de ruido: si CUALQUIER componente del path relativo es uno de estos, el archivo es ruido.
# VCS, caches de test/type, build, deps, metadata de IDE/SO.
_NOISE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", ".tox", ".idea", ".vscode",
    ".ipynb_checkpoints", ".cache", ".next", ".turbo",
}
# Sufijos de archivos compilados/lock/temporales que nunca son "la obra".
_NOISE_SUFFIXES = {".pyc", ".pyo", ".pyd", ".class", ".o", ".obj", ".so", ".egg-info"}
# Nombres exactos de ruido (incluye metadata de SO y de git que no es contenido).
_NOISE_NAMES = {".DS_Store", "Thumbs.db", ".gitignore", ".gitattributes", ".gitmodules"}


def is_noise(rel: Path) -> bool:
    """True si `rel` (path RELATIVO al workdir) es ruido VCS/cache/build/deps y NO obra real."""
    parts = rel.parts
    for part in parts:
        if part in _NOISE_DIRS or part.endswith(".egg-info"):
            return True
    name = rel.name
    if name in _NOISE_NAMES or name.startswith("."):  # conserva el skip de dotfiles previo
        return True
    if rel.suffix.lower() in _NOISE_SUFFIXES:
        return True
    return False


def captured_files(root: str | Path) -> list[Path]:
    """Archivos de `root` que son OBRA REAL (excluye ruido + 0 bytes). Devuelve paths absolutos
    ordenados, listos para que el caller calcule mime y los persista como outputs kind=file.
    Reemplazo 1-a-1 del loop de `_capture_workdir_outputs` (mismo contrato: file, no oculto/ruido,
    >0 bytes)."""
    root = Path(root)
    out: list[Path] = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if is_noise(rel):
            continue
        try:
            if p.stat().st_size == 0:
                continue
        except OSError:
            continue
        out.append(p)
    return out


__all__ = ["captured_files", "is_noise"]
