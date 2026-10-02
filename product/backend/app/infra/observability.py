"""
observability.py — Sentry + telemetría de runs + alerting (T8).

OBJETIVO (DONE-BAR): los errores APARECEN en Sentry. Además: telemetría estructurada
de cada request y de cada job/run, y una señal de alerta cuando la cola se atasca.

Diseño defensivo:
  - Si `sentry_sdk` no está instalado, o no hay SENTRY_DSN en el entorno, TODO esto es
    un no-op silencioso. Dev local no necesita un DSN; prod inyecta SENTRY_DSN.
  - La telemetría siempre emite una línea JSON a stderr (sirve aunque no haya Sentry:
    la consume cualquier colector de logs / Platform Ops).

Config (env):
  SENTRY_DSN          — si está, se inicializa Sentry. Si no, no-op.
  SENTRY_ENVIRONMENT  — 'dev'|'staging'|'prod' (default 'dev').
  SENTRY_TRACES_SAMPLE_RATE — default 0.0 (sin tracing de performance salvo que se pida).
  ALEPH_QUEUE_ALERT_DEPTH   — umbral de 'queued' para emitir alerta (default 100).
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

_sentry = None          # módulo sentry_sdk si se inicializó
_initialized = False


def _emit(record: dict) -> None:
    """Línea JSON a stderr (telemetría base, independiente de Sentry)."""
    try:
        record.setdefault("ts", time.time())
        sys.stderr.write("TELEMETRY " + json.dumps(record, ensure_ascii=False, default=str) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


#: LAS MARCAS DEL TURNO. Prendidas con `ALEPH_ETAPAS=1`.
#:
#: POR QUÉ MARCAS Y NO UN CONTEXT MANAGER: envolver bloques pide re-indentar cientos de
#: líneas del camino caliente, y una obra de medición que reescribe el código que mide es
#: la peor forma de empezar. Una marca es UNA línea en el borde de cada etapa; los deltas
#: se calculan después, fuera del turno — el mismo criterio que ya usa `grabador_prompt`.
#:
#: POR QUÉ SALE POR `_emit`: es el tap que YA existe y ya viaja al `Aleph.log` del sidecar
#: (`TELEMETRY …`). Un segundo canal sería otro archivo que nadie correlaciona.
_ETAPAS = (os.environ.get("ALEPH_ETAPAS") or "").strip().lower() not in ("", "0", "false", "no")


def marca(nombre: str, **extra: Any) -> None:
    """Un instante con nombre en el camino del turno. Apagada, cuesta una comparación."""
    if not _ETAPAS:
        return
    try:
        _emit({"event": "marca", "nombre": nombre, "mono": time.perf_counter(), **extra})
    except Exception:                                    # noqa: BLE001
        pass                                             # un tap que rompe el turno no mide: miente


def is_enabled() -> bool:
    return _sentry is not None


# ── init ────────────────────────────────────────────────────────────────────

def init_observability(app=None) -> bool:
    """Inicializa Sentry si hay DSN + monta el middleware de telemetría en `app`.
    Idempotente. Devuelve True si Sentry quedó activo."""
    global _sentry, _initialized
    if _initialized:
        if app is not None:
            _install_middleware(app)
        return is_enabled()
    _initialized = True

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration

            sentry_sdk.init(
                dsn=dsn,
                environment=os.environ.get("SENTRY_ENVIRONMENT", "dev"),
                traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
                integrations=[StarletteIntegration(), FastApiIntegration()],
                send_default_pii=False,  # nunca PII por defecto (data sensible)
            )
            _sentry = sentry_sdk
            _emit({"event": "observability.init", "sentry": "on",
                   "env": os.environ.get("SENTRY_ENVIRONMENT", "dev")})
        except Exception as exc:  # sentry_sdk ausente o init roto → seguimos sin él
            _emit({"event": "observability.init", "sentry": "off", "reason": str(exc)})
    else:
        _emit({"event": "observability.init", "sentry": "off", "reason": "sin SENTRY_DSN"})

    if app is not None:
        _install_middleware(app)
    return is_enabled()


def _install_middleware(app) -> None:
    """Middleware de telemetría: tiempo + status por request; captura 5xx/excepciones."""
    if getattr(app, "_aleph_telemetry_installed", False):
        return
    app._aleph_telemetry_installed = True

    from starlette.requests import Request

    @app.middleware("http")
    async def _telemetry(request: "Request", call_next):
        t0 = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            dt = (time.monotonic() - t0) * 1000
            _emit({"event": "request", "method": request.method,
                   "path": request.url.path, "status": 500, "ms": round(dt, 1),
                   "error": str(exc)})
            capture_exception(exc, where="request", path=request.url.path)
            raise
        dt = (time.monotonic() - t0) * 1000
        rec = {"event": "request", "method": request.method,
               "path": request.url.path, "status": response.status_code, "ms": round(dt, 1)}
        if response.status_code >= 500:
            _emit(rec)
            capture_message(f"5xx en {request.url.path}", level="error", **rec)
        else:
            _emit(rec)
        return response


# ── captura de errores (lo que hace que "aparezcan en Sentry") ────────────────

def capture_exception(exc: BaseException, **context: Any) -> None:
    _emit({"event": "exception", "type": type(exc).__name__, "msg": str(exc), **context})
    if _sentry is None:
        return
    try:
        with _sentry.push_scope() as scope:
            for k, v in context.items():
                scope.set_tag(k, str(v)[:200]) if isinstance(v, (str, int, float, bool)) else scope.set_extra(k, v)
            _sentry.capture_exception(exc)
    except Exception:
        pass


def capture_message(message: str, *, level: str = "error", **context: Any) -> None:
    if _sentry is None:
        return
    try:
        with _sentry.push_scope() as scope:
            for k, v in context.items():
                scope.set_extra(k, v)
            _sentry.capture_message(message, level=level)
    except Exception:
        pass


def capture_job_error(job: dict, exc: BaseException) -> None:
    """Reporta el fallo de un job a Sentry con contexto (id, kind, user, intentos).
    Lo llama el worker pool. ALERTING: un job que se agota llega acá."""
    capture_exception(
        exc,
        where="job",
        job_id=str(job.get("id")),
        kind=job.get("kind"),
        user_id=str(job.get("user_id")),
        attempts=job.get("attempts"),
        max_attempts=job.get("max_attempts"),
    )


# ── telemetría de runs ────────────────────────────────────────────────────────

def record_run(event: str, *, run_id: Optional[str] = None, job_id: Optional[str] = None,
               **fields: Any) -> None:
    """Hito del ciclo de vida de un run/job (enqueued|started|done|error|...).
    Línea JSON + breadcrumb de Sentry (contexto del próximo error)."""
    rec = {"event": f"run.{event}", "run_id": run_id, "job_id": job_id, **fields}
    _emit(rec)
    if _sentry is not None:
        try:
            _sentry.add_breadcrumb(category="run", message=event, data=rec, level="info")
        except Exception:
            pass


# ── alerting de cola ──────────────────────────────────────────────────────────

def check_queue_alert(stats: dict) -> Optional[dict]:
    """Si la cola 'queued' supera el umbral, o hay 'error', emite una alerta (Sentry +
    log). Devuelve el dict de alerta o None. Lo puede llamar un health-check periódico."""
    threshold = int(os.environ.get("ALEPH_QUEUE_ALERT_DEPTH", "100"))
    queued = int(stats.get("queued", 0))
    errors = int(stats.get("error", 0))
    if queued >= threshold or errors > 0:
        alert = {"event": "alert.queue", "queued": queued, "errors": errors, "threshold": threshold}
        _emit(alert)
        capture_message(
            f"Cola atascada: queued={queued} errors={errors}",
            level="warning", **alert,
        )
        return alert
    return None
