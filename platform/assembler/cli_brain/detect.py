#!/usr/bin/env python3
"""detect.py — detección honesta de los providers BYO-CLI (D2).

Los providers salen de `registry.SPECS` (E1). Cada uno con su estado real e
independiente (los estados no se contagian). Cache con TTL corto para que la UI
pueda preguntar seguido sin spawnear un proceso por render. JAMÁS toca tokens:
la única interacción con el auth de cada CLI es su comando de estado.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

from .base import BrainStatus, CliBrainProvider
from .registry import instantiate_providers

PROVIDERS: dict[str, CliBrainProvider] = instantiate_providers()
# model-id OpenAI-compat del server :8926 → provider (para rutear /chat/completions)
_BY_MODEL_ID: dict[str, CliBrainProvider] = {
    p.response_model_id: p for p in PROVIDERS.values()
}

DETECT_TTL = float(os.environ.get("PUPPET_CLI_BRAIN_DETECT_TTL", "20"))

_cache: dict[str, BrainStatus] = {}
_lock = threading.Lock()


def get_provider(name: str) -> Optional[CliBrainProvider]:
    """Acepta provider_id ('claude_cli') o model-id del server ('claude-code-cli')."""
    return PROVIDERS.get(name) or _BY_MODEL_ID.get(name)


def detect_one(provider_id: str, *, ttl: Optional[float] = None,
               force_refresh: bool = False) -> Optional[BrainStatus]:
    p = PROVIDERS.get(provider_id)
    if p is None:
        return None
    ttl = DETECT_TTL if ttl is None else ttl
    with _lock:
        st = _cache.get(provider_id)
        if not force_refresh and st and (time.time() - st.checked_at) < ttl:
            return st
    st = p.detect()  # fuera del lock: el spawn puede tardar; cada provider es independiente
    with _lock:
        _cache[provider_id] = st
    if provider_id == "claude_cli" and st.state != "ready":
        # Una sesión caída invalida cualquier permiso observado ANTES de su vencimiento.
        # El próximo login empieza con acceso UNKNOWN hasta una ejecución real.
        try:
            from .evidence import clear_access
            clear_access(provider_id)
        except OSError:
            pass                         # el estado vivo manda; el próximo sondeo reintenta
    return st


def detect_statuses(*, ttl: Optional[float] = None,
                    force_refresh: bool = False) -> dict:
    """{provider_id: BrainStatus} — los objetos crudos (uso interno)."""
    return {pid: detect_one(pid, ttl=ttl, force_refresh=force_refresh) for pid in PROVIDERS}


def detect_all(*, ttl: Optional[float] = None, public: bool = False,
               force_refresh: bool = False) -> dict:
    """{provider_id: status.to_dict(public=)} — cada CLI con su estado real, sin contagio.
    `public=True` = forma que sale por HTTP (sin path del binario, con `installed` bool)."""
    from .evidence import decorate_status
    return {pid: decorate_status(st.to_dict(public=public))
            for pid, st in detect_statuses(ttl=ttl, force_refresh=force_refresh).items()}


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()
