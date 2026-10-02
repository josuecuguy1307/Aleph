-- 0001_baseline — Puppet AI · schema v0 CONGELADO (baseline de migraciones).
-- Contenido idéntico a platform/db/schema.sql al adoptar el sistema de migraciones
-- (2026-06-21, T8-infra). Una baseline NO se vuelve a editar jamás: todo cambio
-- futuro entra como una migración nueva (0002, 0003, ...). schema.sql se conserva
-- como referencia legible del estado total; migrations/ es la fuente de verdad.
--
-- Es idempotente (CREATE ... IF NOT EXISTS): aplicarla sobre la base ya poblada de
-- persona usuaria es un no-op; sobre una base fresca, la construye entera.

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ───────────────────────────────────────────────────────────────────────────
-- 1. users
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE NOT NULL,
  display_name  TEXT,
  tier          TEXT NOT NULL DEFAULT 'free',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ───────────────────────────────────────────────────────────────────────────
-- 2. puppets (recetas)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS puppets (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id               UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name                   TEXT NOT NULL,
  nicho                  TEXT NOT NULL,
  config                 JSONB NOT NULL,
  recipe_schema_version  TEXT NOT NULL DEFAULT 'v0',
  version                INTEGER NOT NULL DEFAULT 1,
  status                 TEXT NOT NULL DEFAULT 'draft',
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_puppets_owner      ON puppets(owner_id);
CREATE INDEX IF NOT EXISTS idx_puppets_nicho      ON puppets(nicho);
CREATE INDEX IF NOT EXISTS idx_puppets_config_gin ON puppets USING GIN (config);

-- ───────────────────────────────────────────────────────────────────────────
-- 3. runs
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  puppet_id    UUID REFERENCES puppets(id) ON DELETE SET NULL,
  user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  space_id     TEXT,
  intent       TEXT,
  status       TEXT NOT NULL DEFAULT 'running',
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_runs_puppet ON runs(puppet_id);
CREATE INDEX IF NOT EXISTS idx_runs_space  ON runs(space_id);

-- ───────────────────────────────────────────────────────────────────────────
-- 4. outputs
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outputs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id      UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,
  mime        TEXT,
  uri         TEXT,
  content     TEXT,
  bytes       BIGINT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outputs_run ON outputs(run_id);

-- ───────────────────────────────────────────────────────────────────────────
-- 5. historial
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS historial (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
  puppet_id   UUID REFERENCES puppets(id) ON DELETE SET NULL,
  run_id      UUID REFERENCES runs(id) ON DELETE SET NULL,
  event       TEXT NOT NULL,
  detail      JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_historial_user ON historial(user_id, created_at DESC);

-- ───────────────────────────────────────────────────────────────────────────
-- 6. keys — BYOK cifradas AT-REST
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS keys (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider    TEXT NOT NULL,
  ciphertext  BYTEA NOT NULL,
  enc_scheme  TEXT NOT NULL DEFAULT 'fernet-v1',
  last4       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, provider)
);

-- ───────────────────────────────────────────────────────────────────────────
-- 7. instrumentation_logs — EL MOAT
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS instrumentation_logs (
  id           BIGSERIAL PRIMARY KEY,
  run_id       UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  intent       TEXT,
  belt         JSONB NOT NULL,
  trayectoria  JSONB NOT NULL,
  senal        JSONB,
  costo        JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_instr_run       ON instrumentation_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_instr_belt_gin  ON instrumentation_logs USING GIN (belt);
CREATE INDEX IF NOT EXISTS idx_instr_senal_gin ON instrumentation_logs USING GIN (senal);

-- ───────────────────────────────────────────────────────────────────────────
-- 8. held_actions — acciones de alta consecuencia retenidas por el send-gate
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS held_actions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id       UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  recipe       JSONB NOT NULL,
  server       TEXT NOT NULL,
  tool         TEXT NOT NULL,
  args         JSONB NOT NULL,
  level        TEXT,
  status       TEXT NOT NULL DEFAULT 'held',
  result       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_held_actions_run    ON held_actions(run_id);
CREATE INDEX IF NOT EXISTS idx_held_actions_status ON held_actions(status);
