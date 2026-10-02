"""
bootstrap.py — arranque/parada de la infra de runtime (worker pool) para el lifespan
de FastAPI. Singleton del pool. Idempotente.

Guardas (para no spinnear workers donde no se debe):
  - PUPPET_WORKERS="0"  → no se arranca el pool (modo solo-API).
  - pytest corriendo    → no se arranca (la suite no debe abrir threads ni tocar la DB
                          real por el solo hecho de instanciar la app con TestClient).

Env (con defaults):
  PUPPET_WORKERS            nº de workers (default 4; "0" desactiva)
  PUPPET_WORKER_POLL_S      poll de cola vacía (default 1.0)
  PUPPET_WORKER_HEARTBEAT_S heartbeat durante un job (default 15.0)
  PUPPET_WORKER_RECLAIM_S   cada cuánto corre el reaper (default 60.0)
  PUPPET_WORKER_STALE_S     antigüedad de heartbeat para reclamar un zombie (default 120.0)
"""

from __future__ import annotations

import os
import sys

_pool = None


def _enabled() -> bool:
    if os.environ.get("PUPPET_WORKERS", "").strip() == "0":
        return False
    if "pytest" in sys.modules:
        return False
    return True


def get_worker_pool():
    global _pool
    if _pool is None:
        from app.infra.worker import WorkerPool
        from app.infra import run_handler

        def _f(name, default):
            return float(os.environ.get(name, default))

        n = int(os.environ.get("PUPPET_WORKERS", "4") or "4")
        _pool = WorkerPool(
            {"puppet_run": run_handler.handle},
            n_workers=n,
            poll_interval_s=_f("PUPPET_WORKER_POLL_S", "1.0"),
            heartbeat_s=_f("PUPPET_WORKER_HEARTBEAT_S", "15.0"),
            reclaim_every_s=_f("PUPPET_WORKER_RECLAIM_S", "60.0"),
            reclaim_older_than_s=_f("PUPPET_WORKER_STALE_S", "120.0"),
        )
    return _pool


def start():
    """Arranca el pool (si corresponde): reclama lo que quedó corriendo de un crash
    anterior y levanta los workers + reaper. Devuelve el pool o None."""
    from app.infra import observability
    if not _enabled():
        observability._emit({"event": "workers.skip",
                             "reason": "PUPPET_WORKERS=0 o pytest"})
        return None
    pool = get_worker_pool()
    try:
        pool.reclaim_on_boot()
    except Exception as exc:
        observability.capture_exception(exc, where="boot_reclaim")
    pool.start()
    return pool


def stop():
    global _pool
    if _pool is not None:
        try:
            _pool.stop()
        finally:
            _pool = None
