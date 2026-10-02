-- 0009_instructions — INSTRUCCIONES PERSISTENTES (Ola UX-UNIVERSAL · B5).
--
-- QUÉ ES: las instrucciones del DUEÑO al agente — tono, formato, contexto del usuario —
-- que se inyectan al armar el contexto de CADA run (capa framing, con autoridad; a
-- diferencia de la memoria A3/B2 que entra como "apuntes"). Dos niveles:
--   · CUENTA (puppet_id NULL): aplican a todas las composiciones del usuario.
--   · COMPOSICIÓN (puppet_id = puppets.id del Cuarto guardado): solo ese agente.
--
-- ANTI-IDOR: scope SIEMPRE por user_id (sesión) + owner-check del puppet (patrón
-- _mem_gate). Composición B jamás ve las instrucciones de A.
--
-- ESCRITO-POR-AGENTE (provenance boundary): el agente puede PROPONER una instrucción
-- (source='agent') pero la fila nace INERTE (enabled=FALSE) — no se inyecta hasta que
-- el humano la ACTIVA explícitamente desde el panel (PATCH enabled=true). La escritura
-- efectiva pasa por ese OK; la proveniencia queda en meta ({run_id de la propuesta}).
-- Una instrucción JAMÁS puede aflojar candados: los pisos del gate (money/send) son
-- inmutables por assert_invariant, independientes del texto inyectado.
--
-- CAPS: se reusa el presupuesto por tier de memoria (memory_caps_for_tier) por scope;
-- el router RECHAZA con error honesto al exceder (las instrucciones no se desalojan
-- solas: son autoridad del dueño, no cache).

CREATE TABLE IF NOT EXISTS instructions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  puppet_id   UUID REFERENCES puppets(id) ON DELETE CASCADE,  -- NULL = nivel CUENTA
  source      TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user','agent')),
  content     TEXT NOT NULL,
  bytes       BIGINT NOT NULL DEFAULT 0,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,   -- propuestas del agente nacen FALSE
  meta        JSONB,                            -- proveniencia: {run_id, approved_at, ...}
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_instructions_scope ON instructions (user_id, puppet_id, created_at);
