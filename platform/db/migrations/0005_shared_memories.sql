-- 0005_shared_memories — MEMORIA COMPARTIDA entre agentes, por COMPOSICIÓN (Step 2 · B2).
--
-- POR QUÉ: el cilindro Memory del Cuarto (visual, Step 1) hoy sólo proyecta a un
-- shared-memory.json EFÍMERO del workdir de UN run (recipe.memory{shared} = el germen):
-- muere con la corrida, sin dueño, sin autor, sin clave de composición. B2 lo vuelve REAL:
-- un espacio de memoria PERSISTENTE que VARIOS agentes del mismo Cuarto leen/escriben, con
-- pertenencia y autoría claras.
--
-- PERTENENCIA: la Memory pertenece a la COMPOSICIÓN = el Cuarto GUARDADO = UNA fila puppets
-- (config JSONB = recipe+layout; el Núcleo es esa fila, los hijos viven en belt.agent_refs[]).
-- ⇒ composition_id = puppets.id del Cuarto top-level. Dos Cuartos distintos = dos puppet_id
-- distintos = dos memorias AISLADAS. NO es per-agente (eso es A3, agent_memories) ni global.
--
-- AUTORÍA: cada entrada guarda QUIÉN la escribió. author_agent_id es TEXT (no FK): el Núcleo
-- se identifica por su puppet_id (uuid), pero un HIJO delegado NO tiene fila puppets propia —
-- su id estable es su slug (belt_resolver). author_label = nombre para el panel.
--
-- ACCESO = la línea teal: los agentes conectados al cilindro leen al armar contexto y pueden
-- proponer escribir; los NO conectados no la ven. La membresía se resuelve del recipe
-- (recipe.memory.members) en el runtime; esta tabla no la codifica.
--
-- CONCURRENCIA: last-write-wins por created_at (sin CRDT). ESCRITURA = op server-side (como
-- A3): NO pasa por tool-call → NO choca con el gate A2 (el germen MCP quedaba ROJO justo por
-- eso: create_entities pegaba el piso write-world). AISLAMIENTO: FK a puppets(id) ON DELETE
-- CASCADE borra la memoria al borrar el Cuarto; el dueño se resuelve por puppets.owner_id
-- (authz anti-IDOR en el router). CAPS por TIER las impone el runtime (recipe_enforcer), no la
-- receta. El bus entre >1 agente es PREMIUM (candado en runtime).

CREATE TABLE IF NOT EXISTS shared_memories (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  composition_id  UUID NOT NULL REFERENCES puppets(id) ON DELETE CASCADE,  -- el CUARTO (puppet top-level)
  author_agent_id TEXT,                                -- quién escribió: puppet_id (núcleo) | slug (hijo) | user_id
  author_label    TEXT,                                -- nombre para mostrar en el panel ('Núcleo', 'Vos', …)
  source          TEXT NOT NULL DEFAULT 'agent',       -- 'agent' (destilado del run) | 'user' (panel)
  content         TEXT NOT NULL,                        -- la nota compartida, ya compacta
  bytes           BIGINT NOT NULL DEFAULT 0,            -- tamaño de content (contabilidad de caps)
  pinned          BOOLEAN NOT NULL DEFAULT TRUE,        -- entra al contexto de los agentes conectados
  uri             TEXT,                                 -- handle a un cuerpo grande (opcional, artifacts-por-handle)
  meta            JSONB,                                -- proveniencia: {run_id, author_kind, ...}
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- lectura por composición, más-reciente-primero (arma el bloque compartido y el panel).
CREATE INDEX IF NOT EXISTS idx_shared_memories_comp
  ON shared_memories (composition_id, created_at DESC);
