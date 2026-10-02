-- 0006_knowledge — CONOCIMIENTO del agente (RAG · átomo Conocimiento), por COMPOSICIÓN (Step 2 · C1).
--
-- POR QUÉ: el átomo 'contexto' del Cuarto ("lo que el agente sabe") hoy sólo tiene el
-- germen DOC-RAG v0 (rag_store.py: archivos .md/.txt sueltos por (user_id, agent_key),
-- concatenados ENTEROS al system_content). Eso no escala ni recupera lo relevante: mete
-- todo el documento siempre. C1 lo vuelve REAL: un CORPUS persistente, troceado (chunks)
-- e INDEXADO por embeddings, del cual el agente recupera SÓLO lo pertinente al pedido.
--
-- ÍNDICE $0 / LOCAL-FIRST: NO usamos pgvector ni sqlite-vec (ausentes/frágiles en el venv).
-- El embedding se guarda como ARRAY de floats en JSONB y el ranking es coseno en Python puro
-- (stdlib math) sobre los chunks de la composición. El corpus vive en el Postgres LOCAL =
-- el disco del propio usuario (modo self_hosted, default) → nunca sale de su máquina, misma
-- garantía que "un archivo en disco". El MISMO esquema se re-usa en modo 'hosted' (futuro
-- multi-tenant): ahí Aleph corre la DB y paga el storage, y el cap por MB/tier lo impone el
-- runtime (recipe_enforcer, TIER_RAG_CAPS); en self_hosted NO hay cap (no-op).
--
-- PERTENENCIA: el corpus pertenece a la COMPOSICIÓN = el Cuarto GUARDADO = UNA fila puppets
-- (config JSONB = recipe+layout; el Núcleo es esa fila). ⇒ composition_id = puppets.id del
-- Cuarto top-level. Dos Cuartos distintos = dos corpus AISLADOS. composition_id va en AMBAS
-- tablas (denormalizado en chunks) para poder escanear + aislar el ranking por composición
-- sin JOIN. AISLAMIENTO: FK a puppets(id) ON DELETE CASCADE borra docs y chunks al borrar el
-- Cuarto; el dueño se resuelve por puppets.owner_id (authz anti-IDOR en el router).
--
-- ESCRITURA = op server-side (como A3/B2): ingestar/indexar NO pasa por tool-call del agente
-- → NO choca con el gate A2 (el germen MCP quedaba ROJO justo por eso: el write pegaba el
-- piso write-world). El contenido recuperado es material de referencia NO confiable (APUNTES):
-- el runtime lo enmarca como tal y los gates de dinero/envío siguen SIEMPRE vigentes.
--
-- CLAVE BYOK: el embedding SIEMPRE se hace con la clave del usuario (vault Fernet, resuelta
-- server-side, jamás en respuesta HTTP). Sin clave → status='error_no_key' (error honesto),
-- nunca un skip silencioso ni la clave de Aleph.
--
-- DRIFT DE MODELO: embed_provider/embed_model/embed_dim se persisten por documento para
-- rechazar/saltar un mismatch de dimensión query↔chunk en tiempo de recuperación.

CREATE TABLE IF NOT EXISTS knowledge_docs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  composition_id  UUID NOT NULL REFERENCES puppets(id) ON DELETE CASCADE,  -- el CUARTO (puppet top-level)
  doc_name        TEXT NOT NULL,                            -- nombre del documento
  mime            TEXT,                                     -- txt/md/docx/pdf
  bytes           BIGINT NOT NULL DEFAULT 0,                -- tamaño del contenido extraído (caps)
  sha256          TEXT,                                     -- hash de contenido (dedup/proveniencia)
  status          TEXT NOT NULL DEFAULT 'pending',          -- pending|indexed|error_no_key|error
  error           TEXT,                                     -- razón honesta cuando status=error*
  embed_provider  TEXT,                                     -- proveedor de embeddings usado (drift guard)
  embed_model     TEXT,                                     -- modelo de embeddings usado (drift guard)
  embed_dim       INT,                                      -- dimensión del vector (drift guard)
  n_chunks        INT NOT NULL DEFAULT 0,                   -- cantidad de chunks indexados
  meta            JSONB NOT NULL DEFAULT '{}'::jsonb,       -- proveniencia extra
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- lectura por composición, más-reciente-primero (arma el panel y el listado de docs).
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_comp
  ON knowledge_docs (composition_id, created_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  composition_id  UUID NOT NULL REFERENCES puppets(id) ON DELETE CASCADE,  -- denormalizado: scan + aislamiento
  doc_id          UUID NOT NULL REFERENCES knowledge_docs(id) ON DELETE CASCADE,
  chunk_ix        INT NOT NULL,                             -- índice del chunk dentro del doc
  content         TEXT NOT NULL,                            -- el trozo de texto
  bytes           BIGINT NOT NULL DEFAULT 0,                -- tamaño del chunk (caps)
  embedding       JSONB,                                    -- array de floats; coseno en Python puro (NO pgvector)
  meta            JSONB NOT NULL DEFAULT '{}'::jsonb,       -- {doc_name, chunk_ix, char_start, sha256}
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- escaneo por composición (recuperación: carga los chunks del Cuarto para el ranking coseno).
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_comp
  ON knowledge_chunks (composition_id);

-- por documento (borrado en cascada / listado por doc).
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc
  ON knowledge_chunks (doc_id);
