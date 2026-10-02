"""build_id.py — LA IDENTIDAD DE BUILD (compilación). [Casa 2 · Fase 4 · 4.3]

Distinta de `role.py` (ALEPH_ROLE = qué SUPERFICIE corre este proceso: control|client, runtime).
Esto es qué ARTEFACTO es (public|founder|dev, compilación):

    public   el `.exe` público. El muro de premium-local va BAKED (S3: el usuario no lo apaga).
    founder  artefacto privado del dueño (seguridad por AUSENCIA; el código founder no está en public).
    dev      corriendo del árbol de fuentes (tests/CI): el muro es opt-out por env, cómodo para dev.

⚠️ EL BAKED GANA sobre la env. Un `.exe` public trae `aleph_build_id.ALEPH_BUILD="public"` (lo
genera `preparar_cliente.sh`), y ESO manda: `ALEPH_BUILD=dev` en el env del usuario NO puede
degradar un build shipped a dev y regalarse el premium. En dev (sin baked) la env decide, default
`dev`. Es el principio founder=build: lo retenido se resuelve en compilación, no en runtime.
"""
from __future__ import annotations

import os

PUBLIC, FOUNDER, DEV = "public", "founder", "dev"
_VALID = (PUBLIC, FOUNDER, DEV)


def _baked() -> str | None:
    """El build type HORNEADO en el artefacto, o None si es un árbol de fuentes (dev)."""
    try:
        import aleph_build_id  # generado por preparar_cliente.sh; ausente en source
    except ImportError:
        return None
    v = str(getattr(aleph_build_id, "ALEPH_BUILD", "")).strip().lower()
    return v if v in _VALID else None


def current() -> str:
    """El build de ESTE artefacto. Baked GANA (no override-able por env); si no, env; si no, dev."""
    baked = _baked()
    if baked:
        return baked
    env = (os.environ.get("ALEPH_BUILD") or "").strip().lower()
    return env if env in _VALID else DEV


def is_public() -> bool:
    return current() == PUBLIC


def is_founder() -> bool:
    return current() == FOUNDER


def is_dev() -> bool:
    return current() == DEV


def is_shipped() -> bool:
    """¿Es un artefacto distribuido (no el árbol de fuentes)? → el muro de premium va BAKED."""
    return current() in (PUBLIC, FOUNDER)


def describe() -> str:
    b = _baked()
    return (f"ALEPH_BUILD={current()}" + (" (baked)" if b else " (env/default)"))


__all__ = ["PUBLIC", "FOUNDER", "DEV", "current",
           "is_public", "is_founder", "is_dev", "is_shipped", "describe"]
