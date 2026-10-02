-- 0003_agent_memories — MEMORIA DEL AGENTE por-agent_id, persistente ENTRE runs (Step 2 · A3).
--
-- POR QUÉ: hoy nada persiste lo que un agente aprendió de una corrida a la otra. El
-- shared-memory.json (recipe.memory{shared} = B2) vive en el workdir EFÍMERO de UN run
-- (mkdtemp por run) → memoria de la cadena de ese run, no del agente entre sesiones. Y el
-- toggle "recuerda entre corridas" del Cuarto estaba mal-cableado a rag.enabled. Esta tabla
-- da memoria REAL por AGENTE (puppet_id): el agente destila aprendizajes al cierre del run y
-- el usuario escribe/edita/borra directo desde el panel de su pieza — lo que se ve = lo que hay.
--
-- SCOPE: memoria POR agente (keyed por puppet_id). La COMPARTIDA entre agentes es B2, NO esto.
-- AISLAMIENTO: el FK a puppets(id) ON DELETE CASCADE borra la memoria al borrar el agente; el
-- dueño se resuelve por puppets.owner_id (authz anti-IDOR en el router). Un agente NO ve la
-- memoria de otro.
-- CAPS: el nº de entradas y bytes por agente los IMPONE el runtime por TIER (frontera en
-- recipe_enforcer.TIER_MEMORY_CAPS), NO editable por receta — esta tabla no los codifica.
-- GRANDE→COMPACTO: `content` guarda la memoria ya destilada/acotada; para un cuerpo grande se
-- usa el idiom outputs (uri como handle + bytes), nunca crudo al framing (artifacts-por-handle).

CREATE TABLE IF NOT EXISTS agent_memories (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  puppet_id   UUID NOT NULL REFERENCES puppets(id) ON DELETE CASCADE,  -- el AGENTE dueño (agent_id)
  source      TEXT NOT NULL DEFAULT 'agent',      -- 'agent' (destilado del run) | 'user' (panel)
  content     TEXT NOT NULL,                       -- la memoria, ya compacta (lo que entra al framing)
  bytes       BIGINT NOT NULL DEFAULT 0,           -- tamaño de content (contabilidad de caps)
  pinned      BOOLEAN NOT NULL DEFAULT TRUE,       -- entra al framing PINEADO del próximo run
  uri         TEXT,                                -- handle a un cuerpo grande persistido (opcional)
  meta        JSONB,                               -- proveniencia: {run_id, ...}
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- lectura por agente, más-reciente-primero (arma el bloque pineado y el panel).
CREATE INDEX IF NOT EXISTS idx_agent_memories_puppet
  ON agent_memories (puppet_id, created_at DESC);
