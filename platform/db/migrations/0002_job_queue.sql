-- 0002_job_queue — cola de trabajo DURABLE (T8-infra).
--
-- POR QUÉ: hoy /v1/puppets/run corre el executor SÍNCRONO dentro del request →
-- bloquea un thread del server por toda la duración del run, y si el proceso se
-- reinicia mid-run el trabajo se pierde (el row de `runs` queda 'running' huérfano).
-- Esta cola desacopla el disparo del request de la EJECUCIÓN: un job se encola y un
-- worker pool acotado lo procesa. Sobrevive reinicios (es una tabla) y se reclama al
-- bootear (un job 'running' sin heartbeat vuelve a 'queued').
--
-- Dequeue seguro entre N workers concurrentes: SELECT ... FOR UPDATE SKIP LOCKED.
-- Scope por user_id (contrato AUTH §4.5): un job lleva su dueño; nada se procesa
-- fuera de scope. NO reemplaza a `runs` ni a `instrumentation_logs` — los ALIMENTA:
-- el handler del job crea/actualiza el run y persiste el moat por el path existente.

CREATE TABLE IF NOT EXISTS job_queue (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind          TEXT NOT NULL,                       -- 'puppet_run' | (extensible)
  status        TEXT NOT NULL DEFAULT 'queued',      -- queued|running|done|error|dead
  priority      INT  NOT NULL DEFAULT 0,             -- mayor primero
  payload       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- args del job (ej. recipe/prompt/space_id)
  result        JSONB,                               -- salida del handler al terminar (done)
  error         TEXT,                                -- traza/motivo al fallar (error|dead)
  run_id        UUID REFERENCES runs(id)  ON DELETE SET NULL,   -- run producido (si aplica)
  user_id       UUID REFERENCES users(id) ON DELETE SET NULL,   -- dueño (scope)
  attempts      INT  NOT NULL DEFAULT 0,             -- nº de veces que un worker lo tomó
  max_attempts  INT  NOT NULL DEFAULT 1,             -- tope de reintentos (1 = sin retry)
  locked_by     TEXT,                                -- id del worker que lo sostiene
  locked_at     TIMESTAMPTZ,
  heartbeat_at  TIMESTAMPTZ,                         -- liveness del worker (reclamo de zombies)
  available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),  -- scheduling: delay / backoff de retry
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ
);

-- claim: solo mira los 'queued' ya disponibles, ordenados por prioridad y antigüedad.
CREATE INDEX IF NOT EXISTS idx_job_queue_claim
  ON job_queue (priority DESC, available_at ASC)
  WHERE status = 'queued';

-- reclamo de zombies: los 'running' por heartbeat viejo.
CREATE INDEX IF NOT EXISTS idx_job_queue_reclaim
  ON job_queue (heartbeat_at)
  WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_job_queue_status ON job_queue (status);
CREATE INDEX IF NOT EXISTS idx_job_queue_run    ON job_queue (run_id);
CREATE INDEX IF NOT EXISTS idx_job_queue_user   ON job_queue (user_id);
