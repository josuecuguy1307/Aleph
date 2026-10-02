-- Puppet AI — Schema v0 (FASE 0 · Database & Data)
-- Corre DENTRO de la base lógica `puppet_ai` del Postgres EXISTENTE de persona usuaria
-- (postgresql@17 :5432). No se inventa un servidor nuevo.
--
-- Regla madre del schema: la RECETA vive como JSONB parametrizable.
-- NADA hardcodeado por nicho. "Agregar nicho = escribir receta, no recodear."
--
-- El moat = `instrumentation_logs`: una fila liga por `run_id` los 5 campos
-- exactos del loop (intent · belt · trayectoria · señal · costo).

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ───────────────────────────────────────────────────────────────────────────
-- 1. users
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE NOT NULL,
  display_name  TEXT,
  tier          TEXT NOT NULL DEFAULT 'free',  -- free|basico|tecnico (texto: los tiers evolucionan, no enum)
  password_hash TEXT,                          -- AUTH (T6): scrypt$<salt>$<dk>. NULL = cuenta legacy passwordless.
  session_version BIGINT NOT NULL DEFAULT 0,   -- revoca sesiones Fernet al cambiar credenciales/logout
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Migración idempotente: DBs creadas antes de AUTH (T6) no tenían la columna; el código
-- (repo.register_user/login_user) la requiere. ADD COLUMN IF NOT EXISTS converge fresh+existente.
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version BIGINT NOT NULL DEFAULT 0;

-- ───────────────────────────────────────────────────────────────────────────
-- 2. puppets (recetas) — la receta como config.json parametrizable (JSONB)
--    NO columnas hardcodeadas por nicho. El contrato taller↔assembler↔run.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS puppets (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id               UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name                   TEXT NOT NULL,
  nicho                  TEXT NOT NULL,              -- string libre: cowork|research|programacion|educacion|finanzas|...
  config                 JSONB NOT NULL,             -- LA RECETA: model, belt, tool_filters, framing, rag, temp, max_turns...
  recipe_schema_version  TEXT NOT NULL DEFAULT 'v0', -- contra qué versión del contrato se validó la receta
  version                INTEGER NOT NULL DEFAULT 1, -- versión de ESTA receta (sube al editar en el taller)
  status                 TEXT NOT NULL DEFAULT 'draft', -- draft|active|archived
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_puppets_owner      ON puppets(owner_id);
CREATE INDEX IF NOT EXISTS idx_puppets_nicho      ON puppets(nicho);
CREATE INDEX IF NOT EXISTS idx_puppets_config_gin ON puppets USING GIN (config);  -- consultar DENTRO de la receta

-- ───────────────────────────────────────────────────────────────────────────
-- 3. runs — una ejecución (un "espacio") de un puppet
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  puppet_id    UUID REFERENCES puppets(id) ON DELETE SET NULL,
  user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  space_id     TEXT,                                  -- el space_id del stream de eventos (platform/assembler/session.py)
  intent       TEXT,                                  -- qué pidió el usuario (también espejado en instrumentation_logs)
  status       TEXT NOT NULL DEFAULT 'running',       -- running|done|error|abandoned|huerfano
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  -- MULTIAGENTE (migración 0018 · docs/multiagente.md §4): un salto de cadena es un run
  -- NORMAL enlazado POR CAMPO. Todo NULL = run normal, que es lo que era antes de existir
  -- estas columnas. El ciclo de vida del run no cambia.
  parent_run_id  UUID REFERENCES runs(id) ON DELETE SET NULL,  -- el globo padre; NULL = run normal
  hop_index      INTEGER,                                       -- posición del salto (0-based)
  hop_latency_ms BIGINT,                                        -- LATENCIA MEDIDA de ese salto (ms enteros)
  modo           TEXT                                           -- el modo del run PADRE; NULL = run normal
);
CREATE INDEX IF NOT EXISTS idx_runs_puppet ON runs(puppet_id);
CREATE INDEX IF NOT EXISTS idx_runs_space  ON runs(space_id);
CREATE INDEX IF NOT EXISTS idx_runs_parent ON runs(parent_run_id, hop_index) WHERE parent_run_id IS NOT NULL;

-- ───────────────────────────────────────────────────────────────────────────
-- 4. outputs — artefactos producidos por un run (el artefacto vivo de la sala)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outputs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id      UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,        -- file|report|image|message|chart|...
  mime        TEXT,
  uri         TEXT,                 -- path/uri al artefacto persistente
  content     TEXT,                 -- inline si es chico
  bytes       BIGINT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outputs_run ON outputs(run_id);

-- ───────────────────────────────────────────────────────────────────────────
-- 5. historial — histórico legible (humano) de actividad por usuario/puppet.
--    Distinto de instrumentation_logs (señal de máquina): esto es lo que el
--    usuario ve en su línea de tiempo.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS historial (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
  puppet_id   UUID REFERENCES puppets(id) ON DELETE SET NULL,
  run_id      UUID REFERENCES runs(id) ON DELETE SET NULL,
  event       TEXT NOT NULL,        -- created_puppet|edited_config|ran|saved_output|abandoned|...
  detail      JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_historial_user ON historial(user_id, created_at DESC);

-- ───────────────────────────────────────────────────────────────────────────
-- 6. keys — BYOK cifradas AT-REST. NUNCA plaintext.
--    `ciphertext` = token Fernet (AES-128-CBC + HMAC). La clave de cifrado vive
--    fuera de la DB (env PUPPET_DB_ENC_KEY o platform/db/secrets/enc.key).
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS keys (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider    TEXT NOT NULL,                       -- openai|anthropic|groq|openrouter|...
  ciphertext  BYTEA NOT NULL,                       -- Fernet token. NUNCA el valor plano.
  enc_scheme  TEXT NOT NULL DEFAULT 'fernet-v1',
  last4       TEXT,                                 -- últimos 4 chars para que el usuario reconozca su key (no secreto)
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, provider)
);

-- ───────────────────────────────────────────────────────────────────────────
-- 7. instrumentation_logs — EL MOAT.
--    Una fila liga por `run_id` los 5 campos EXACTOS del loop:
--      (1) intent      — qué pidió el usuario
--      (2) belt        — la receta usada (snapshot de config.json al correr)
--      (3) trayectoria — secuencia de model-calls + tool-calls, cada uno con latency_ms y error
--      (4) señal       — explícita (👍/👎) + implícita (guardó/editó/abandonó)
--      (5) costo       — tokens
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS instrumentation_logs (
  id           BIGSERIAL PRIMARY KEY,
  run_id       UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,  -- EL LIGADOR
  intent       TEXT,                 -- (1)
  belt         JSONB NOT NULL,       -- (2) snapshot de la receta
  trayectoria  JSONB NOT NULL,       -- (3) [{seq,kind:'model_call'|'tool_call',name,latency_ms,error},...]
  senal        JSONB,                -- (4) {explicit:'up'|'down'|null, implicit:{saved,edited,abandoned}}
  costo        JSONB,                -- (5) {prompt_tokens,completion_tokens,total_tokens,by_model}
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_instr_run       ON instrumentation_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_instr_belt_gin  ON instrumentation_logs USING GIN (belt);
CREATE INDEX IF NOT EXISTS idx_instr_senal_gin ON instrumentation_logs USING GIN (senal);

-- ───────────────────────────────────────────────────────────────────────────
-- 8. held_actions — acciones de ALTA CONSECUENCIA retenidas por el send-gate
--    (send/money) esperando el OK EXPLÍCITO del usuario por HTTP (approve-by-HTTP,
--    deuda #1 post-Fase-4). El gate SOSTIENE: el correo/pago NO sale hasta que el
--    dueño aprueba. Durable (sobrevive reinicios) y recuperable por approval_id.
--    Guarda la `recipe` para re-armar el belt y ejecutar la acción EXACTA al aprobar.
--    El invariante §3.5 se mantiene: el único camino a ejecutar es el OK explícito.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS held_actions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),   -- approval_id
  run_id       UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  recipe       JSONB NOT NULL,        -- para re-armar el belt y ejecutar la acción al aprobar
  server       TEXT NOT NULL,         -- belt server (ej. gmail)
  tool         TEXT NOT NULL,         -- la tool retenida (ej. send_email)
  args         JSONB NOT NULL,        -- argumentos EXACTOS propuestos por el agente
  level        TEXT,                  -- nivel del gate (ej. confirma-siempre) para la UX
  status       TEXT NOT NULL DEFAULT 'held',  -- held|executed|rejected
  result       TEXT,                  -- resultado tras ejecutar / motivo del rechazo
  -- STEP 2·B1 · provenance del árbol de delegación (una held puede venir de un SUB-AGENTE).
  agent_path     JSONB,               -- camino raíz→hoja: qué sub-agente pidió el OK (null = held propia del padre)
  via_delegation BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE si subió (hoist) de un hijo/nieto
  depth          INTEGER,             -- profundidad del sub-agente que la retuvo (0 = raíz)
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_held_actions_run    ON held_actions(run_id);
CREATE INDEX IF NOT EXISTS idx_held_actions_status ON held_actions(status);
