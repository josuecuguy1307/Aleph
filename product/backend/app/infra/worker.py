"""
worker.py — worker pool que drena la cola job_queue SIN bloquear los requests.

Diseño:
  - N threads worker. Cada uno: claim_one (atómico, SKIP LOCKED) → ejecuta el handler
    del `kind` → mark_done/mark_error. Si no hay job, duerme `poll_interval_s`.
  - Mientras un job corre, un ticker latedea (heartbeat) cada `heartbeat_s`: así un job
    sano NO se reclama, pero uno cuyo worker murió deja de latir y SÍ se reclama.
  - Un reaper periódico llama jobs.reclaim_stale (zombies de workers caídos).
  - Acotado: el nº de workers acota la concurrencia real → no se agota Postgres ni la
    RAM aunque lleguen 1000 enqueues. La cola absorbe el pico; el pool drena a ritmo.
  - Shutdown graceful: stop() pide parar, cada worker termina el job en curso y sale.

Aislamiento de fallos: una excepción de un handler se captura, marca el job 'error'
(con retry si quedan intentos) y se reporta a Sentry. NUNCA tumba el thread ni a los
otros jobs (ese es el corazón de "N runs concurrentes no se caen").

Conexiones: cada operación de cola usa una conexión del pool (platform/db/pool.py),
corta y devuelta — no retiene conexiones largas durante el run.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

# pool de DB de infra (platform/db/pool.py)
_PLATFORM_DB = Path(__file__).resolve().parents[4] / "platform" / "db"
if str(_PLATFORM_DB) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DB))

from app.infra import jobs

# Handler de un kind: recibe el dict del job, devuelve un dict (result).
# Puede devolver result["run_id"] para ligar el run producido.
Handler = Callable[[dict], dict]


def _log(msg: str) -> None:
    print(f"[worker] {msg}", file=sys.stderr, flush=True)


def _pooled():
    from pool import pooled_conn  # platform/db/pool.py
    return pooled_conn()


class _Heartbeat:
    """Ticker que latedea un job mientras corre. Se detiene al cerrar el `with`."""

    def __init__(self, job_id: str, worker_id: str, interval_s: float):
        self.job_id = job_id
        self.worker_id = worker_id
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._t: Optional[threading.Thread] = None

    def __enter__(self):
        self._t = threading.Thread(target=self._loop, name=f"hb-{self.job_id[:8]}", daemon=True)
        self._t.start()
        return self

    def _loop(self):
        while not self._stop.wait(self.interval_s):
            try:
                with _pooled() as conn:
                    jobs.heartbeat(conn, self.job_id, self.worker_id)
            except Exception:
                pass  # un fallo de heartbeat no debe matar el job

    def __exit__(self, *exc):
        self._stop.set()
        if self._t:
            self._t.join(timeout=2.0)


class WorkerPool:
    def __init__(
        self,
        handlers: dict[str, Handler],
        *,
        n_workers: int = 4,
        poll_interval_s: float = 1.0,
        heartbeat_s: float = 15.0,
        reclaim_every_s: float = 60.0,
        reclaim_older_than_s: float = 120.0,
        retry_backoff_s: float = 30.0,
    ):
        self.handlers = handlers
        self.n_workers = max(1, int(n_workers))
        self.poll_interval_s = poll_interval_s
        self.heartbeat_s = heartbeat_s
        self.reclaim_every_s = reclaim_every_s
        self.reclaim_older_than_s = reclaim_older_than_s
        self.retry_backoff_s = retry_backoff_s
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started = False

    # ── ciclo de un worker ──────────────────────────────────────────────────
    def _worker_loop(self, idx: int) -> None:
        worker_id = jobs.worker_identity(f"w{idx}")
        while not self._stop.is_set():
            job = None
            try:
                with _pooled() as conn:
                    job = jobs.claim_one(conn, worker_id)
            except Exception as exc:
                _log(f"{worker_id} claim falló (DB?): {exc}")
                self._stop.wait(self.poll_interval_s * 2)
                continue

            if job is None:
                self._stop.wait(self.poll_interval_s)
                continue

            self._run_job(worker_id, job)

    def _run_job(self, worker_id: str, job: dict) -> None:
        job_id = job["id"]
        kind = job["kind"]
        handler = self.handlers.get(kind)
        if handler is None:
            msg = f"sin handler para kind='{kind}'"
            _log(f"{worker_id} job {job_id}: {msg}")
            with _pooled() as conn:
                jobs.mark_error(conn, job_id, msg, retry_backoff_s=self.retry_backoff_s)
            return

        try:
            with _Heartbeat(job_id, worker_id, self.heartbeat_s):
                result = handler(job) or {}
            run_id = result.get("run_id") if isinstance(result, dict) else None
            with _pooled() as conn:
                jobs.mark_done(conn, job_id, result, run_id=run_id)
            _log(f"{worker_id} job {job_id} ({kind}) ✓ done run={run_id}")
        except Exception as exc:
            tb = traceback.format_exc()
            try:
                with _pooled() as conn:
                    new_status = jobs.mark_error(
                        conn, job_id, f"{exc}\n{tb}", retry_backoff_s=self.retry_backoff_s
                    )
            except Exception as e2:
                new_status = f"mark_error-falló:{e2}"
            _log(f"{worker_id} job {job_id} ({kind}) ✗ {type(exc).__name__}: {exc} → {new_status}")
            # ALERTING: el error se reporta a Sentry (no-op si no hay DSN).
            try:
                from app.infra import observability
                observability.capture_job_error(job, exc)
            except Exception:
                pass

    # ── reaper ────────────────────────────────────────────────────────────────
    def _reaper_loop(self) -> None:
        while not self._stop.wait(self.reclaim_every_s):
            try:
                with _pooled() as conn:
                    rep = jobs.reclaim_stale(conn, older_than_s=self.reclaim_older_than_s)
                if rep["requeued"] or rep["failed"]:
                    _log(f"reaper: re-encolados={rep['requeued']} fallados={rep['failed']}")
            except Exception as exc:
                _log(f"reaper falló: {exc}")

    # ── arranque / parada ──────────────────────────────────────────────────────
    def reclaim_on_boot(self) -> dict:
        """Al bootear: reclama lo que quedó 'running' cuando el proceso anterior cayó.
        ESTO es lo que hace que un reinicio no pierda runs encolados."""
        with _pooled() as conn:
            rep = jobs.reclaim_stale(conn, older_than_s=self.reclaim_older_than_s)
        if rep["requeued"] or rep["failed"]:
            _log(f"boot reclaim: re-encolados={rep['requeued']} fallados={rep['failed']}")
        return rep

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()
        for i in range(self.n_workers):
            t = threading.Thread(target=self._worker_loop, args=(i,), name=f"worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        r = threading.Thread(target=self._reaper_loop, name="reaper", daemon=True)
        r.start()
        self._threads.append(r)
        _log(f"pool arriba: {self.n_workers} workers + reaper")

    def stop(self, timeout_s: float = 30.0) -> None:
        """Pide parar; cada worker termina el job en curso y sale. Cierra el pool."""
        if not self._started:
            return
        _log("parando pool (graceful)…")
        self._stop.set()
        deadline = time.monotonic() + timeout_s
        for t in self._threads:
            remaining = max(0.1, deadline - time.monotonic())
            t.join(timeout=remaining)
        self._threads.clear()
        self._started = False
        try:
            from pool import close_pool
            close_pool()
        except Exception:
            pass
        _log("pool detenido.")
