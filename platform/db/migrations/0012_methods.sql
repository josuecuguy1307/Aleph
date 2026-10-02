-- 0011_methods — pieza MÉTODO (workflows): biblioteca + estado del arnés por run.
--
-- QUÉ ES (ORDEN_METODO.md):
--   · methods      — la BIBLIOTECA DE LA CASA: objetos Method (pasos en lenguaje
--     natural, steps PLANOS con campo phase + phases[] aditivo) por CUENTA.
--     Los agentes equipan por REFERENCIA (belt.method_refs[] dentro del recipe,
--     precedente belt.agent_refs[]) — acá vive el OBJETO, jamás el vínculo.
--     Editar el método actualiza a todos los agentes que lo referencian.
--   · method_runs  — el ESTADO EXTERNO del arnés (filosofía dura: el modelo NUNCA
--     es dueño del estado del workflow) + control-plane durable (pause/resume/
--     remedy/checkpoint) polleado entre turnos. state.spec congela el método TAL
--     COMO CORRE (con method_adjust aplicado): un resume sobrevive a ediciones de
--     la biblioteca y a la muerte del proceso.
--
-- ANTI-IDOR: methods scope SIEMPRE por user_id (sesión); recurso ajeno == 404
-- indistinguible (patrón instructions/account_memories). method_runs se accede
-- vía el run (run_owner) o por user_id directo.
--
-- CAPS: crear métodos = ILIMITADO en todos los tiers (ORDEN §7). Solo caps de
-- SANIDAD (bytes por método, pasos por método) iguales para todos, en el router.
-- Lo premium es el EXPORT TOTAL y la bóveda, no la creación.
--
-- MADURACIÓN (local básico): run_count/last_run_at en la fila; el detalle
-- acumulado NO viaja en ningún export (regla §7).

CREATE TABLE IF NOT EXISTS methods (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  spec         JSONB NOT NULL,                  -- el objeto Method completo (steps[], phases[], extras round-trip)
  bytes        BIGINT NOT NULL DEFAULT 0,       -- tamaño UTF-8 del spec (cap de sanidad)
  run_count    INTEGER NOT NULL DEFAULT 0,      -- maduración local básica
  last_run_at  TIMESTAMPTZ,                     -- alimenta last_run_days del match
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_methods_owner ON methods (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS method_runs (
  run_id       UUID PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
  method_id    UUID REFERENCES methods(id) ON DELETE SET NULL,  -- SET NULL: borrar el método no rompe el estado del run
  user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
  puppet_id    UUID,                            -- sin FK: puede ser un agente no guardado
  space_id     TEXT,                            -- para narrar continuaciones por el mismo espinazo
  status       TEXT NOT NULL DEFAULT 'active'
               CHECK (status IN ('active','waiting_checkpoint','paused_failure',
                                 'paused_user','scheduled_retry','completed','abandoned')),
  state        JSONB NOT NULL,                  -- {spec, step_status{}, attempts{}, skipped[], current, notes[]}
  control      JSONB,                           -- control-plane: {pause, resume_spec, remedy, checkpoint{approval_id,ok}}
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_method_runs_method ON method_runs (method_id);
CREATE INDEX IF NOT EXISTS idx_method_runs_owner  ON method_runs (user_id, updated_at DESC);
