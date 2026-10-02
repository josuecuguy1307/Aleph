"""Lazy-init service singletons shared by session and live routes.

[Aleph · F6] El runtime de canales de IM se extirpó — ver ../../../EXTIRPACIONES.md."""

from __future__ import annotations

import os

from src.api._compat import host_attr as _host_attr, set_host_attr as _set_host_attr
from src.api.helpers import RUNS_DIR, SESSIONS_DIR
from src.config.accessor import get_env_config


# ============================================================================
# Global singletons
# ============================================================================

_session_service = None


# ============================================================================
# Lazy initializers
# ============================================================================


def _get_session_service():
    """Lazy-init session service when ENABLE_SESSION_RUNTIME=true."""
    global _session_service

    import sys as _sys
    _host = _sys.modules.get("api_server")
    if _host is not None and hasattr(_host, "_session_service"):
        host_val = getattr(_host, "_session_service")
        if host_val is not None:
            return host_val
    elif _session_service is not None:
        return _session_service

    if not get_env_config().api.enable_session_runtime:
        return None

    import asyncio

    from src.session.events import EventBus
    from src.session.service import SessionService
    from src.session.store import SessionStore

    # Honor monkeypatched SESSIONS_DIR / RUNS_DIR on api_server.
    sessions_dir = _host_attr("SESSIONS_DIR", SESSIONS_DIR)
    runs_dir = _host_attr("RUNS_DIR", RUNS_DIR)

    store = SessionStore(base_dir=sessions_dir)
    event_bus = EventBus()

    try:
        loop = asyncio.get_event_loop()
        event_bus.set_loop(loop)
    except RuntimeError:
        pass

    _session_service = SessionService(
        store=store,
        event_bus=event_bus,
        runs_dir=runs_dir,
    )
    _set_host_attr("_session_service", _session_service)
    return _session_service
