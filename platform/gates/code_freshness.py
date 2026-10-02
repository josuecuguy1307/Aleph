"""code_freshness.py — huella de frescura del código del backend (Step 2 · A1).

PROBLEMA (A1): el backend corre SIN `--reload`; su código queda CONGELADO en el
import del proceso. Un edit posterior a un `.py` NO lo toma hasta reiniciar → se
testea la versión vieja → falsos verdes/rojos indistinguibles (root-cause del único
false-green de OAuth en el Caso 2).

SOLUCIÓN: una huella determinista del árbol de código que el backend REALMENTE carga
(app/ del backend + platform/). El backend la calcula UNA vez al arranque y la publica
en `/health`; el harness la recalcula sobre el disco ANTES de cada tanda y compara:
si el disco es más nuevo que lo que el proceso cargó → el backend está STALE → abortar.

FUENTE ÚNICA: este módulo lo importan LOS DOS (backend y harness) para que la huella
se compute IDÉNTICO en ambos lados. No depende de git (funciona con árbol sucio):
la señal dura es el **max mtime** del código runtime; el git-SHA es contexto extra.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

# Directorios que el backend REALMENTE importa en runtime (relativos al repo root).
# Se excluyen tests y basura para no disparar falsos "stale" al editar el harness.
_SCAN_DIRS = (
    ("product", "backend", "app"),
    ("platform",),
)
_EXCLUDE_DIR_PARTS = {"__pycache__", ".venv", "node_modules", "data", ".git", ".pytest_cache"}


def _is_runtime_py(p: Path) -> bool:
    if p.suffix != ".py":
        return False
    parts = set(p.parts)
    if parts & _EXCLUDE_DIR_PARTS:
        return False
    name = p.name
    # los tests no cambian el comportamiento del backend → no deben forzar reinicio
    if name.startswith("test_") or name.endswith("_test.py"):
        return False
    if "tests" in p.parts:
        return False
    return True


def _scan(repo_root: Path) -> tuple[float, int, Optional[str]]:
    """(max_mtime, file_count, newest_rel_path) del código runtime bajo repo_root."""
    max_mtime = 0.0
    count = 0
    newest: Optional[Path] = None
    for parts in _SCAN_DIRS:
        base = repo_root.joinpath(*parts)
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if not _is_runtime_py(p):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            count += 1
            if m > max_mtime:
                max_mtime = m
                newest = p
    rel = None
    if newest is not None:
        try:
            rel = str(newest.relative_to(repo_root))
        except ValueError:
            rel = str(newest)
    return max_mtime, count, rel


def _git(repo_root: Path) -> tuple[Optional[str], Optional[bool]]:
    """(sha_corto, dirty) o (None, None) si git no está disponible. Nunca lanza."""
    def _run(args: list[str]) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode != 0:
                return None
            return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    sha = _run(["rev-parse", "--short=12", "HEAD"])
    if sha is None:
        return None, None
    porcelain = _run(["status", "--porcelain"])
    dirty = None if porcelain is None else bool(porcelain.strip())
    return sha, dirty


def compute_fingerprint(repo_root: os.PathLike | str) -> dict[str, Any]:
    """Huella determinista del código runtime en `repo_root`. Idéntica en backend y harness."""
    root = Path(repo_root).resolve()
    max_mtime, count, newest = _scan(root)
    sha, dirty = _git(root)
    return {
        "git_sha": sha,                       # None si no hay git
        "git_dirty": dirty,                   # True si hay cambios sin commitear
        "source_mtime": round(max_mtime, 3),  # SEÑAL DURA de frescura (epoch)
        "source_mtime_iso": (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(max_mtime)) if max_mtime else None
        ),
        "source_files": count,
        "newest_source": newest,              # qué archivo marca la huella (debug)
        "repo_root": str(root),
    }


# ── Preflight del harness ─────────────────────────────────────────────────────────

class StaleBackendError(RuntimeError):
    """El backend corre código más viejo que el disco → cualquier test es basura."""


def assert_backend_fresh(health_code: dict, repo_root: os.PathLike | str,
                         *, slack_seconds: float = 2.0) -> dict[str, Any]:
    """Compara la huella que /health reporta (lo que el proceso CARGÓ) contra el disco AHORA.

    `health_code` = el sub-objeto `code` de GET /health.
    Lanza StaleBackendError si el disco tiene código más nuevo (backend stale → reiniciar).
    Devuelve un dict de diagnóstico en el caso fresco.
    """
    disk = compute_fingerprint(repo_root)
    # el backend no pudo huellar al arrancar (git/scan falló) → NO afirmamos "fresco" ni "stale":
    # es un estado desconocido y hay que resolverlo antes de confiar en la tanda.
    if health_code.get("error") or not health_code.get("source_mtime"):
        raise StaleBackendError(
            "FRESCURA DESCONOCIDA: /health no reporta huella de código ({}). No puedo garantizar "
            "que el backend no esté stale — reinicia/diagnostica antes de correr."
            .format(health_code.get("error") or "source_mtime ausente"))
    loaded_mtime = float(health_code.get("source_mtime") or 0.0)
    disk_mtime = float(disk.get("source_mtime") or 0.0)
    delta = disk_mtime - loaded_mtime
    diag = {
        "fresh": delta <= slack_seconds,
        "loaded_mtime": loaded_mtime,
        "disk_mtime": disk_mtime,
        "delta_seconds": round(delta, 3),
        "loaded_sha": health_code.get("git_sha"),
        "disk_sha": disk.get("git_sha"),
        "newest_source_on_disk": disk.get("newest_source"),
    }
    if delta > slack_seconds:
        raise StaleBackendError(
            "BACKEND STALE: el disco tiene código {:.1f}s más nuevo que el proceso cargado "
            "(archivo: {}). Reinicia el backend antes de correr esta tanda — si no, pruebas "
            "código viejo (A1).".format(delta, disk.get("newest_source"))
        )
    return diag
