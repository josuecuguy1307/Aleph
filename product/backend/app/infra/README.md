# infra — capa de RUNTIME/INFRA (T8)

La base sobre la que corren las features. **No contiene lógica de features**: agrega
durabilidad, concurrencia y observabilidad de forma **aditiva** (no toca `/v1/puppets/run`
ni el executor — los *llama*).

## Qué resuelve (DONE-BAR)

| Garantía | Cómo |
|---|---|
| **N runs concurrentes no se caen** | Cola Postgres (`job_queue`) + worker pool acotado. Un job que explota se aísla (marca `error`/retry) y **no tumba el pool ni a los demás**. El run corre fuera del thread del request → el server sigue respondiendo. |
| **Un restart no pierde runs** | La cola es una tabla (los `queued` sobreviven el reinicio). Al bootear, `reclaim_on_boot()` recupera lo que quedó `running` cuando el proceso cayó: lo re-encola (si quedan intentos) o lo marca `error` (nunca queda zombie `running` para siempre). |
| **Los errores aparecen en Sentry** | `observability.py` cablea `sentry_sdk` (FastAPI/Starlette) + middleware de telemetría + captura en fallos de job y 5xx. **Guardado por `SENTRY_DSN`** (no-op sin DSN). *Ver "Sentry: pendiente" abajo.* |

## Piezas

- `jobs.py` — API de cola sobre `job_queue` (migración `0002`). Dequeue atómico con
  `FOR UPDATE SKIP LOCKED`; `heartbeat`, `mark_done`, `mark_error` (con retry+backoff),
  `reclaim_stale`, `stats`.
- `worker.py` — `WorkerPool`: N threads que drenan la cola, latedean durante cada job,
  un reaper periódico reclama zombies. Shutdown graceful.
- `run_handler.py` — handler `puppet_run`: reusa las MISMAS costuras que `/v1/puppets/run`
  (byok_resolver, política money/send §3.5, emitter a la Sala) y llama a
  `executor.run_puppet_e2e`. La validación/authz va en el enqueue; acá solo ejecuta.
- `infra_router.py` — endpoints aditivos:
  - `POST /v1/runs/enqueue` — encola (valida+autoriza al toque) → `{job_id, status}`. **No bloquea.**
  - `GET /v1/jobs/{id}` · `GET /v1/jobs?user_id=` — estado de jobs (scopeado al dueño, anti-IDOR).
  - `GET /health/deep` — DB viva + profundidad de cola (para monitores externos).
- `observability.py` — Sentry + telemetría JSON + `check_queue_alert`.
- `bootstrap.py` — arranque/parada del pool en el lifespan de `main.py`.
- `verify_infra.py` — verificación dura del DONE-BAR contra Postgres real (ver abajo).

## Cómo correr

```bash
# migraciones (versionadas; idempotente)
.venv/bin/python platform/db/migrate.py            # aplica pendientes
.venv/bin/python platform/db/migrate.py status     # aplicadas vs pendientes

# backups (pg_dump -Fc + rotación)
.venv/bin/python platform/db/backup.py             # crea + rota
.venv/bin/python platform/db/backup.py --list
.venv/bin/python platform/db/backup.py --restore <archivo.dump>   # DESTRUCTIVO

# servidor (el lifespan arranca el worker pool)
.venv/bin/python -m uvicorn app.main:app --port 8080

# verificación de la mecánica (rápida, sin LLM, contra Postgres real)
.venv/bin/python -m app.infra.verify_infra         # CHECK 1/2a/2b/3 → PASS/FAIL
```

## Env knobs

| Var | Default | Qué |
|---|---|---|
| `PUPPET_WORKERS` | `4` | nº de workers (`0` = solo-API, no arranca el pool; los tests lo desactivan) |
| `PUPPET_WORKER_POLL_S` | `1.0` | poll de cola vacía |
| `PUPPET_WORKER_HEARTBEAT_S` | `15.0` | heartbeat durante un job |
| `PUPPET_WORKER_RECLAIM_S` | `60.0` | cada cuánto corre el reaper |
| `PUPPET_WORKER_STALE_S` | `120.0` | antigüedad de heartbeat para reclamar un zombie |
| `PUPPET_DB_POOL_MIN`/`MAX` | `1`/`10` | tamaño del pool de conexiones de infra (`platform/db/pool.py`) |
| `PUPPET_DB_BACKUP_DIR`/`KEEP` | `platform/db/backups`/`7` | dir de dumps / cuántos conservar |
| `SENTRY_DSN` | — | si está, Sentry se inicializa. Sin él, todo es no-op. |
| `SENTRY_ENVIRONMENT` | `dev` | entorno reportado a Sentry |
| `ALEPH_QUEUE_ALERT_DEPTH` | `100` | umbral de `queued` para emitir alerta |

## Sentry: pendiente (bloqueo honesto)

El código está **cableado y verificado localmente** (init no-op sin DSN ✓, paths de captura
ejecutan ✓, SDK instalado ✓). Para que los errores **aparezcan de verdad** en Sentry falta
**provisionar un DSN** — no se incluye una organización personal en esta copia. Dos pasos:

1. Crear un proyecto Python en la organización elegida (UI de Sentry) → copiar su DSN.
2. Exportar `SENTRY_DSN=<dsn>` (+ `SENTRY_ENVIRONMENT=prod`) y reiniciar el server.

Verificación post-DSN: forzar un 5xx o un job que falle → el evento aparece en
la organización elegida (consultable por `search_issues`).

## Notas de coordinación

- **Migraciones = fuente de verdad** desde ahora. `schema.sql` queda como referencia legible;
  `0001_baseline.sql` está CONGELADO. Todo cambio futuro = una migración nueva (`0003_…`).
- El `get_conn()` de features queda **intacto** — el pool (`pool.py`) es opt-in para infra.
- `puppet_run` se encola con `max_attempts=1` por default (un run no se auto-reintenta salvo
  que el caller lo pida). Un crash mid-run con `max_attempts=1` deja el job en `error`
  (registrado, recuperable por re-enqueue), **no** un zombie.
