"""
verify_infra.py — verificación DURA del DONE-BAR de T8 contra el Postgres REAL.

Prueba la MECÁNICA de la infra con jobs sintéticos (sin LLM, rápido y barato):
  CHECK 1 — N runs concurrentes no se caen: 12 jobs (ok+slow+que-fallan) por un pool
            de 4 workers; un job que explota NO tumba el pool ni a los demás.
  CHECK 2a — restart no pierde runs (cola): jobs encolados sobreviven un "reinicio"
            (re-instanciar el pool) y se drenan.
  CHECK 2b — restart no pierde runs (mid-run): un job que estaba 'running' cuando el
            worker murió se RECLAMA (requeue si quedan intentos; error registrado si no
            — nunca queda zombie 'running' para siempre).
  CHECK 3 — observabilidad: capture_job_error ejecuta sin romper (no-op sin DSN), y la
            telemetría emite. (El e2e con DSN real se valida aparte.)

Corre con la marca de jobs '__verify%' y LIMPIA al final (no ensucia la cola real).
Salida: PASS/FAIL por check + exit code.

Uso:  product/backend/.venv/bin/python -m app.infra.verify_infra   (cwd=product/backend)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# pool más holgado para el test (4 workers + heartbeats + reaper)
os.environ.setdefault("PUPPET_DB_POOL_MAX", "25")

# platform/db en el path (igual que worker.py) para `from pool import ...`
_PLATFORM_DB = Path(__file__).resolve().parents[4] / "platform" / "db"
if str(_PLATFORM_DB) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_DB))


def _pooled():
    from pool import pooled_conn
    return pooled_conn()


def _cleanup():
    with _pooled() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job_queue WHERE kind LIKE '\\_\\_verify%';")
        conn.commit()


def _verify_stats() -> dict:
    with _pooled() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, count(*) FROM job_queue WHERE kind LIKE '\\_\\_verify%' GROUP BY status;"
            )
            out = {"queued": 0, "running": 0, "done": 0, "error": 0}
            for s, n in cur.fetchall():
                out[s] = n
            return out


# ── handlers sintéticos ────────────────────────────────────────────────────────
def _h_ok(job):
    return {"ok": True, "n": (job.get("payload") or {}).get("n")}


def _h_slow(job):
    time.sleep(0.4)
    return {"ok": True, "slow": True}


def _h_err(job):
    raise RuntimeError("fallo sintético de verificación (esperado)")


_HANDLERS = {"__verify_ok__": _h_ok, "__verify_slow__": _h_slow, "__verify_err__": _h_err}


def _wait_drain(timeout_s=30.0):
    """Espera a que no queden '__verify%' en queued/running."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        st = _verify_stats()
        if st["queued"] == 0 and st["running"] == 0:
            return st
        time.sleep(0.2)
    return _verify_stats()


def check1_concurrencia() -> bool:
    from app.infra import jobs
    from app.infra.worker import WorkerPool
    print("\n── CHECK 1: N concurrentes + aislamiento de fallos ──")
    with _pooled() as conn:
        for i in range(6):
            jobs.enqueue(conn, "__verify_ok__", {"n": i})
        for i in range(3):
            jobs.enqueue(conn, "__verify_slow__", {"n": i})
        for i in range(3):
            jobs.enqueue(conn, "__verify_err__", {"n": i}, max_attempts=1)
    pool = WorkerPool(_HANDLERS, n_workers=4, poll_interval_s=0.1,
                      heartbeat_s=2.0, reclaim_every_s=5.0, retry_backoff_s=0.2)
    pool.start()
    st = _wait_drain()
    alive = pool._started and any(t.is_alive() for t in pool._threads)
    pool.stop(timeout_s=5.0)
    ok = (st["done"] == 9 and st["error"] == 3 and alive)
    print(f"  done={st['done']} (esperado 9), error={st['error']} (esperado 3), pool_vivo={alive}")
    print(f"  {'PASS' if ok else 'FAIL'} — 9 ok/slow completaron; 3 que explotan no tumbaron el pool")
    _cleanup()
    return ok


def check2a_restart_cola() -> bool:
    from app.infra import jobs
    from app.infra.worker import WorkerPool
    print("\n── CHECK 2a: restart no pierde runs (cola encolada sobrevive) ──")
    with _pooled() as conn:
        for i in range(5):
            jobs.enqueue(conn, "__verify_ok__", {"n": i})
    # "reinicio": NO arrancamos workers; simulamos que el proceso cayó y vuelve.
    st_before = _verify_stats()
    pool = WorkerPool(_HANDLERS, n_workers=3, poll_interval_s=0.1)
    pool.reclaim_on_boot()  # lo que corre el lifespan al bootear
    pool.start()
    st = _wait_drain()
    pool.stop(timeout_s=5.0)
    ok = (st_before["queued"] == 5 and st["done"] == 5)
    print(f"  antes={st_before['queued']} queued (sobrevivieron al 'reinicio'); después done={st['done']}")
    print(f"  {'PASS' if ok else 'FAIL'} — los 5 encolados se drenaron tras el reinicio")
    _cleanup()
    return ok


def check2b_reclaim_midrun() -> bool:
    from app.infra import jobs
    from app.infra.worker import WorkerPool
    print("\n── CHECK 2b: reclaim de un run que estaba corriendo cuando el worker murió ──")
    # con reintentos (max_attempts=2): debe RE-ENCOLAR y completar
    with _pooled() as conn:
        for i in range(3):
            jobs.enqueue(conn, "__verify_ok__", {"n": i}, max_attempts=2)
    # simular in-flight: un worker 'fantasma' los toma y muere (heartbeat queda viejo)
    with _pooled() as conn:
        for _ in range(3):
            jobs.claim_one(conn, "ghost-worker-muerto")
    with _pooled() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE job_queue SET heartbeat_at = now() - interval '999 seconds' "
                "WHERE kind='__verify_ok__' AND status='running';"
            )
        conn.commit()
    st_zombie = _verify_stats()
    # boot reclaim con umbral chico → re-encola los zombies
    with _pooled() as conn:
        rep = jobs.reclaim_stale(conn, older_than_s=60.0)
    st_after_reclaim = _verify_stats()
    pool = WorkerPool(_HANDLERS, n_workers=3, poll_interval_s=0.1)
    pool.start()
    st = _wait_drain()
    pool.stop(timeout_s=5.0)
    ok = (st_zombie["running"] == 3 and rep["requeued"] == 3 and st["done"] == 3)
    print(f"  zombies running={st_zombie['running']}, reclaim requeued={rep['requeued']}, "
          f"tras reclaim queued={st_after_reclaim['queued']}, final done={st['done']}")
    print(f"  {'PASS' if ok else 'FAIL'} — el run mid-crash se reclamó y completó (no quedó zombie)")
    _cleanup()
    return ok


def check3_observabilidad() -> bool:
    from app.infra import observability
    print("\n── CHECK 3: observabilidad (captura de error + telemetría) ──")
    fake_job = {"id": "00000000-0000-0000-0000-000000000000", "kind": "__verify_err__",
                "user_id": None, "attempts": 1, "max_attempts": 1}
    try:
        observability.capture_job_error(fake_job, RuntimeError("error de prueba"))
        observability.record_run("done", run_id="r-test", job_id="j-test", ok=True)
        alert = observability.check_queue_alert({"queued": 0, "running": 0, "done": 1, "error": 0})
        ok = (alert is None)  # cola sana → sin alerta
        print(f"  capture_job_error ejecutó · record_run ejecutó · alerta(cola sana)={alert}")
        print(f"  sentry_activo={observability.is_enabled()} (no-op esperado sin SENTRY_DSN)")
        print(f"  {'PASS' if ok else 'FAIL'} — el path de observabilidad corre sin romper")
        return ok
    except Exception as exc:
        print(f"  FAIL — observabilidad rompió: {exc}")
        return False


def main() -> int:
    _cleanup()  # arrancar limpio
    results = {
        "check1_concurrencia": check1_concurrencia(),
        "check2a_restart_cola": check2a_restart_cola(),
        "check2b_reclaim_midrun": check2b_reclaim_midrun(),
        "check3_observabilidad": check3_observabilidad(),
    }
    print("\n══════════ RESUMEN ══════════")
    for k, v in results.items():
        print(f"  {'✓' if v else '✗'} {k}")
    all_ok = all(results.values())
    print(f"\n{'✓ DONE-BAR de mecánica: VERDE' if all_ok else '✗ HAY FALLOS'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
