-- schema_sqlite.sql — El subset del CLIENTE, en SQLite. [Casa 2 · Fase 2 · paso 2.1]
--
-- Tablas de este archivo: rol CLIENTE.
-- Las que espejan platform/db/migrations/*.sql corren en los dos roles.
-- Las solo-cliente no tienen contraparte en el control plane:
--   conexiones — una conexión MCP solo existe en el escritorio
--
-- Espejo de `schema.sql` (Postgres) para el Aleph que corre en la máquina del usuario.
-- Las 21 tablas de acá NO son una lista escrita a mano: salen de `role.py`
--     tablas_del_cliente() = TABLAS_CLIENTE | TABLAS_LOCALES_SIN_SYNC
--                          | TABLAS_SOLO_CLIENTE | TABLAS_AMBAS
-- que es la frontera EJECUTABLE del paso 2.0. Las 7 tablas de plata y plan
-- (`subscriptions`, `payment_webhook_events`, `tier_audit`, `billing_*`) NO están
-- acá, y esa ausencia es el punto: el cliente no puede tocar lo que no existe.
--
-- ⚠️ POR QUÉ ESTE ARCHIVO ES ASÍ DE EXPLÍCITO — el tipado de SQLite es dinámico y
-- ACEPTA CUALQUIER NOMBRE DE TIPO. Traducir el DDL de Postgres a ojo no da error:
-- da NULL. Medido contra SQLite 3.51.0, con un INSERT que omite el id:
--
--     BIGSERIAL PRIMARY KEY                    -> id = NULL   (se acepta, no autoincrementa)
--     BIGINT PRIMARY KEY                       -> id = NULL   (el "arreglo" obvio falla igual)
--     TEXT PRIMARY KEY                         -> id = NULL   (¡PK no implica NOT NULL!)
--     INTEGER PRIMARY KEY AUTOINCREMENT        -> id = 1      ✅
--     TEXT PRIMARY KEY NOT NULL DEFAULT (uuid) -> id = uuid   ✅
--
-- Las tres trampas son silenciosas. La tercera es la traicionera: en Postgres
-- `PRIMARY KEY` implica `NOT NULL`; en SQLite eso vale SOLO para `INTEGER PRIMARY KEY`
-- (el alias de rowid). Cualquier otro tipo de PK acepta NULL por compatibilidad
-- histórica. Por eso cada PK de acá lleva `NOT NULL` escrito, aunque en Postgres sea
-- redundante.
--
-- ⚠️ Y EL DEFAULT DEL UUID NO ES COSMÉTICO: el código omite el `id` en el INSERT y se
-- apoya en `DEFAULT gen_random_uuid()` (repo.py:259,297,607,685,900,1036,1145,1263,
-- 1616,1759 · chats_repo.py:39 · methods_repo.py:220 · instructions_repo.py:73,237).
-- Sin un default que genere el uuid, esos INSERT no fallan: guardan filas con id NULL.
--
-- MAPEO DE TIPOS (el molde es `knowledge_store._SCHEMA`, que ya lo resolvió):
--     UUID                      -> TEXT           (uuid como string)
--     BIGSERIAL / BIGINT (PK)   -> INTEGER PRIMARY KEY AUTOINCREMENT
--     BIGINT / INTEGER (no PK)  -> INTEGER
--     TIMESTAMPTZ               -> TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
--     JSONB                     -> TEXT
--     BOOLEAN                   -> INTEGER        (0/1; `true`->1, `false`->0)
--     BYTEA                     -> BLOB
--
-- NO SE REPLICAN los 3 índices GIN (D2): `idx_puppets_config_gin`,
-- `idx_instr_belt_gin`, `idx_instr_senal_gin`. En Postgres indexan DENTRO del JSONB;
-- en SQLite degradarían a full scan sin avisar. A volumen de un usuario no duele.
-- (El plan decía 6: son 3 índices distintos, definidos dos veces — en `schema.sql`
-- y en `0001_baseline.sql`. El Postgres vivo tiene 3.)
--
-- ⚠️ REQUIERE `PRAGMA foreign_keys = ON` POR CONEXIÓN. En SQLite los FK vienen
-- APAGADOS por default: sin ese pragma los `ON DELETE CASCADE` de acá son decorativos
-- y el borrado de cuenta deja huérfanos en silencio. Va en la capa de conexión (2.2).

PRAGMA journal_mode = WAL;      -- la cola (2.3) tiene ~9 hilos escritores
PRAGMA foreign_keys = ON;

-- ───────────────────────────────────────────────────────────────────────────
-- 1. users — identidad local
--    OJO: `tier` acá NO es autoritativo (D1). Es caché; la autoridad de plan vive
--    en el plano de control y lo premium re-verifica contra él.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  email         TEXT NOT NULL UNIQUE,
  display_name  TEXT,
  tier          TEXT NOT NULL DEFAULT 'free',
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  password_hash TEXT,
  session_version INTEGER NOT NULL DEFAULT 0,
  deleted_at    TEXT,
  purge_after   TEXT,
  auth_uid      TEXT
);

-- ───────────────────────────────────────────────────────────────────────────
-- 2. puppets — la RECETA vive como JSON parametrizable (`config`)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS puppets (
  id                    TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  owner_id              TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name                  TEXT NOT NULL,
  nicho                 TEXT NOT NULL,
  config                TEXT NOT NULL,
  recipe_schema_version TEXT NOT NULL DEFAULT 'v0',
  version               INTEGER NOT NULL DEFAULT 1,
  status                TEXT NOT NULL DEFAULT 'draft',
  created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 3. runs
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runs (
  id          TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  puppet_id   TEXT REFERENCES puppets(id) ON DELETE SET NULL,
  user_id     TEXT REFERENCES users(id) ON DELETE SET NULL,
  space_id    TEXT,
  intent      TEXT,
  status      TEXT NOT NULL DEFAULT 'running',
  started_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  finished_at TEXT,
  -- MULTIAGENTE (espejo de la migración 0018 · docs/multiagente.md §4). Un salto de cadena
  -- es un run NORMAL enlazado POR CAMPO; todo NULL = run normal. Las DBs YA DESPLEGADAS no
  -- reciben este DDL — reciben el ALTER de `sqlite_db._MIGRACIONES_CLIENTE[2]`. Los dos
  -- caminos tienen que dar la MISMA tabla, y `test_schema_sqlite` lo verifica.
  -- `hop_latency_ms` es INTEGER (ms enteros) y no REAL a propósito: el schema del cliente
  -- sólo admite TEXT|INTEGER|BLOB (ver la cabecera de este archivo).
  parent_run_id  TEXT REFERENCES runs(id) ON DELETE SET NULL,
  hop_index      INTEGER,
  hop_latency_ms INTEGER,
  modo           TEXT
);

-- ───────────────────────────────────────────────────────────────────────────
-- 4. outputs
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outputs (
  id         TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  run_id     TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,
  mime       TEXT,
  uri        TEXT,
  content    TEXT,
  bytes      INTEGER,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 5. historial — BIGSERIAL -> INTEGER PRIMARY KEY AUTOINCREMENT
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS historial (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    TEXT REFERENCES users(id) ON DELETE CASCADE,
  puppet_id  TEXT REFERENCES puppets(id) ON DELETE SET NULL,
  run_id     TEXT REFERENCES runs(id) ON DELETE SET NULL,
  event      TEXT NOT NULL,
  detail     TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 6. keys — BYOK cifrada (Fernet). `ciphertext` es BYTEA -> BLOB.
--    Que viva local ES la tesis: la llave del usuario no pasa por nuestros servidores.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS keys (
  id         TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider   TEXT NOT NULL,
  ciphertext BLOB NOT NULL,
  enc_scheme TEXT NOT NULL DEFAULT 'fernet-v1',
  last4      TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  UNIQUE (user_id, provider)
);

-- ───────────────────────────────────────────────────────────────────────────
-- 7. chats
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chats (
  id         TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  puppet_id  TEXT REFERENCES puppets(id) ON DELETE CASCADE,
  title      TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 8. chat_messages — BIGSERIAL -> INTEGER PRIMARY KEY AUTOINCREMENT
--    `run_id` NO tiene FK en Postgres (verificado en el dump): no se agrega acá.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id    TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  client_turn_id TEXT,
  role       TEXT NOT NULL CHECK (role IN ('user','agent')),
  kind       TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat','obra')),
  content    TEXT NOT NULL,
  space_id   TEXT,
  run_id     TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 9. methods
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS methods (
  id          TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  spec        TEXT NOT NULL,
  bytes       INTEGER NOT NULL DEFAULT 0,
  run_count   INTEGER NOT NULL DEFAULT 0,
  last_run_at TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 10. method_runs — la PK es `run_id`, y NO tiene default en Postgres:
--     el id lo provee el código. Por eso lleva NOT NULL pero no DEFAULT.
--     `puppet_id` NO tiene FK en Postgres (verificado en el dump).
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS method_runs (
  run_id     TEXT PRIMARY KEY NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  method_id  TEXT REFERENCES methods(id) ON DELETE SET NULL,
  user_id    TEXT REFERENCES users(id) ON DELETE CASCADE,
  puppet_id  TEXT,
  space_id   TEXT,
  status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
               'active','waiting_checkpoint','paused_failure','paused_user',
               'scheduled_retry','completed','abandoned','paused_incomplete')),
  state      TEXT NOT NULL,
  control    TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 11. instructions
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS instructions (
  id         TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  puppet_id  TEXT REFERENCES puppets(id) ON DELETE CASCADE,
  source     TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user','agent')),
  content    TEXT NOT NULL,
  bytes      INTEGER NOT NULL DEFAULT 0,
  enabled    INTEGER NOT NULL DEFAULT 1,
  meta       TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 12. agent_memories
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_memories (
  id         TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  puppet_id  TEXT NOT NULL REFERENCES puppets(id) ON DELETE CASCADE,
  source     TEXT NOT NULL DEFAULT 'agent',
  content    TEXT NOT NULL,
  bytes      INTEGER NOT NULL DEFAULT 0,
  pinned     INTEGER NOT NULL DEFAULT 1,
  uri        TEXT,
  meta       TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 13. shared_memories — `composition_id` referencia puppets(id)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS shared_memories (
  id              TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  composition_id  TEXT NOT NULL REFERENCES puppets(id) ON DELETE CASCADE,
  author_agent_id TEXT,
  author_label    TEXT,
  source          TEXT NOT NULL DEFAULT 'agent',
  content         TEXT NOT NULL,
  bytes           INTEGER NOT NULL DEFAULT 0,
  pinned          INTEGER NOT NULL DEFAULT 1,
  uri             TEXT,
  meta            TEXT,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 14. account_memories
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS account_memories (
  id         TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  owner_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source     TEXT NOT NULL DEFAULT 'agent',
  content    TEXT NOT NULL,
  bytes      INTEGER NOT NULL DEFAULT 0,
  pinned     INTEGER NOT NULL DEFAULT 1,
  uri        TEXT,
  meta       TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 15. knowledge_docs — el RAG local (C1). `composition_id` referencia puppets(id).
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_docs (
  id             TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  composition_id TEXT NOT NULL REFERENCES puppets(id) ON DELETE CASCADE,
  doc_name       TEXT NOT NULL,
  mime           TEXT,
  bytes          INTEGER NOT NULL DEFAULT 0,
  sha256         TEXT,
  status         TEXT NOT NULL DEFAULT 'pending',
  error          TEXT,
  embed_provider TEXT,
  embed_model    TEXT,
  embed_dim      INTEGER,
  n_chunks       INTEGER NOT NULL DEFAULT 0,
  meta           TEXT NOT NULL DEFAULT '{}',
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 16. knowledge_chunks
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id             TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  composition_id TEXT NOT NULL REFERENCES puppets(id) ON DELETE CASCADE,
  doc_id         TEXT NOT NULL REFERENCES knowledge_docs(id) ON DELETE CASCADE,
  chunk_ix       INTEGER NOT NULL,
  content        TEXT NOT NULL,
  bytes          INTEGER NOT NULL DEFAULT 0,
  embedding      TEXT,
  meta           TEXT NOT NULL DEFAULT '{}',
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 17. job_queue — la cola durable.
--     El reclamo con `FOR UPDATE SKIP LOCKED` no existe en SQLite: se reemplaza por
--     un guard `AND status='queued'` en el propio UPDATE (paso 2.3, ya probado en
--     spike: 8 workers · 500 jobs · 0 doble-claim). El schema no cambia por eso.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_queue (
  id           TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  kind         TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'queued',
  priority     INTEGER NOT NULL DEFAULT 0,
  payload      TEXT NOT NULL DEFAULT '{}',
  result       TEXT,
  error        TEXT,
  run_id       TEXT REFERENCES runs(id) ON DELETE SET NULL,
  user_id      TEXT REFERENCES users(id) ON DELETE SET NULL,
  attempts     INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 1,
  locked_by    TEXT,
  locked_at    TEXT,
  heartbeat_at TEXT,
  available_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  started_at   TEXT,
  finished_at  TEXT
);

-- ───────────────────────────────────────────────────────────────────────────
-- 18. held_actions — el gate "el agente propone, el humano aprueba"
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS held_actions (
  id            TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),
  run_id        TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  user_id       TEXT REFERENCES users(id) ON DELETE SET NULL,
  recipe        TEXT NOT NULL,
  server        TEXT NOT NULL,
  tool          TEXT NOT NULL,
  args          TEXT NOT NULL,
  level         TEXT,
  status        TEXT NOT NULL DEFAULT 'held',
  result        TEXT,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  decided_at    TEXT,
  agent_path    TEXT,
  via_delegation INTEGER NOT NULL DEFAULT 0,
  depth         INTEGER,
  turn_text     TEXT
);

-- ───────────────────────────────────────────────────────────────────────────
-- 19. instrumentation_logs — BIGSERIAL -> INTEGER PRIMARY KEY AUTOINCREMENT
--     LOCAL Y SIN SYNC (D3). El moat no se alimenta exfiltrando al usuario.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS instrumentation_logs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  intent      TEXT,
  belt        TEXT NOT NULL,
  trayectoria TEXT NOT NULL,
  senal       TEXT,
  costo       TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- ───────────────────────────────────────────────────────────────────────────
-- 20. schema_migrations — infra del runner; existe en las dos bases
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY NOT NULL,
  name       TEXT NOT NULL,
  checksum   TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

-- Shared, atomic inspection admission. Leases expire only after the runner's hard deadline.
CREATE TABLE IF NOT EXISTS inspect_leases (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('start','running','finished','failed','cancelled')),
  finished_at INTEGER,
  pid INTEGER
);
CREATE INDEX IF NOT EXISTS idx_inspect_leases_owner ON inspect_leases(owner_id);
CREATE INDEX IF NOT EXISTS idx_inspect_leases_expiry ON inspect_leases(expires_at);

-- ───────────────────────────────────────────────────────────────────────────
-- 21. conexiones — EL REGISTRO (CONTRACT-CONEXION-v1 §1). SOLO CLIENTE.
--
--     Una fila por ENTIDAD (un servicio conectable), jamás por proceso ni por
--     sesión: guarda CÓMO RECONSTRUIR, nunca un PID, un descriptor ni un
--     `Mcp-Session-Id` (§0 y §1 «Qué NO va en el registro»).
--
--     ⚠️ EL ENTORNO DEL HIJO VIVE EN DOS COLUMNAS, no en una (§2):
--       env_template  {VAR: "${VAR}"}   placeholders → se resuelven contra el llavero
--       env_publico   {VAR: "valor"}    literales PÚBLICOS → viajan tal cual
--     Y LOS HEADERS DE UN SERVER HTTP, igual: headers_template / headers_publico. Un token
--     en un header es tan secreto como en una env var, así que usa el MISMO reparto.
--     Al spawnear se juntan las dos. El caso índice es `secedgar`, que exige
--     SEC_EDGAR_USER_AGENT (el identificador que SEC EDGAR pide para saber quién le
--     pega): público por diseño, y sin él la API rechaza el request. Separarlas en dos
--     columnas mantiene el guard del §2 DURO sobre `env_template` —cualquier literal ahí
--     sigue levantando— y deja lo público DECLARADO en vez de tolerado por excepción.
--
--     ⚠️ PRIMERA TABLA SIN CONTRAPARTE EN POSTGRES. Rompe el espejo a propósito:
--     una conexión MCP solo existe en el escritorio; el control plane no
--     spawnea servidores locales. Por eso vive en `role.TABLAS_SOLO_CLIENTE`,
--     un frozenset propio, y no en `TABLAS_CLIENTE` (que sí espeja).
--
--     Clave: `id` surrogate (el código omite el id en el INSERT) + UNIQUE
--     (user_id, entity_id) — la misma forma que `keys`, por la decisión de
--     alcance por-usuario del §1.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conexiones (
  id                  TEXT PRIMARY KEY NOT NULL DEFAULT (lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),2)||'-'||substr('89ab',1+abs(random()%4),1)||substr(lower(hex(randomblob(2))),2)||'-'||lower(hex(randomblob(6)))),

  -- identidad
  user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  entity_id           TEXT NOT NULL,          -- identificador estable de la entidad
  nombre_visible      TEXT NOT NULL DEFAULT '',
  transporte          TEXT,                   -- 'stdio' | 'http' | NULL = sin determinar

  -- receta (cómo reconstruir)
  command             TEXT,
  args                TEXT,                   -- JSONB -> TEXT: array JSON
  cwd                 TEXT,
  env_template        TEXT,                   -- JSONB -> TEXT: {VAR: "${VAR}"} — NOMBRES, jamás valores (§2)
  env_publico         TEXT,                   -- JSONB -> TEXT: {VAR: "valor"} — literales PÚBLICOS declarados (§2)
  timeout_ms          INTEGER,                -- tope por request, en MILISEGUNDOS
  -- receta del transporte HTTP (v4). Un server HTTP no tiene command/args: tiene endpoint
  -- y headers. Los headers se reparten IGUAL que el entorno (§2) porque un token en un
  -- header es tan secreto como en una env var.
  url                 TEXT,                   -- endpoint del MCP remoto
  headers_template    TEXT,                   -- JSONB -> TEXT: {H: "Bearer ${VAR}"} — referencias
  headers_publico     TEXT,                   -- JSONB -> TEXT: {H: "valor"} — literales públicos
  -- LAS DOS MEDICIONES, SEPARADAS (v5). No son la misma pregunta y por eso no comparten
  -- columna: un 401 es CONEXIÓN VIVA —el mensaje viajó y el servicio contestó— y a la vez
  -- CREDENCIAL RECHAZADA. Guardarlas juntas obliga a elegir cuál de las dos verdades se
  -- pierde. `ultimo_veredicto` sigue siendo el resumen que pinta el semáforo.
  conexion            TEXT,                   -- JSONB -> TEXT: {estado, causa, tool_usada, evidencia, ts}
  credencial          TEXT,                   -- JSONB -> TEXT: {estado, tool_prueba, evidencia, ts}

  -- credencial (referencia, nunca el valor — §2)
  credencial_ref      TEXT,                   -- nombre en el llavero; jamás el secreto
  scopes              TEXT,                   -- JSONB -> TEXT: array JSON
  cuenta              TEXT,

  -- protocolo
  era                 TEXT,                   -- era del protocolo con la que se habló
  version_negociada   TEXT,                   -- lo que devolvió el initialize
  server_info         TEXT,                   -- JSONB -> TEXT: {name, version}

  -- capacidad
  tools_snapshot      TEXT,                   -- JSONB -> TEXT: array JSON. EVIDENCIA, no contrato (§1)
  fingerprint         TEXT,                   -- firma de la configuración probada
  recipe_version      TEXT NOT NULL DEFAULT 'v1',
  -- lo NUESTRO, que el usuario jamás ve (migración cliente 6 · 0020 en el server)
  estado_interno      TEXT,
  bloqueo_interno     TEXT,
  reserva             TEXT DEFAULT NULL,       -- JSONB -> TEXT: aviso medido al traer

  -- estado
  habilitado          INTEGER NOT NULL DEFAULT 1,   -- BOOLEAN -> INTEGER. La lápida (§4). NADIE LO LEE TODAVÍA.
  ultimo_veredicto    TEXT,
  causa               TEXT,
  ultima_verificacion TEXT,

  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),

  UNIQUE (user_id, entity_id)
);

-- ───────────────────────────────────────────────────────────────────────────
-- 22 · `modelos_estado` — EL REGISTRO DE MODELOS (Gate 2 · F4c). SOLO CLIENTE.
-- Lo que hace posible la regla ANTI-YO-YO: sin memoria entre arranques no se puede
-- distinguir «nunca estuvo completa» (→ aduana) de «lo estuvo y hoy falla» (→ local).
-- NO hay columna `estuvo_completa`: se DERIVA de `ultimo_veredicto == 'probado'`, igual
-- que en `conexiones` — un booleano aparte podría desincronizarse del veredicto.
--
-- ══ LA INVARIANTE QUE SOSTIENE EL ANTI-YO-YO ═══════════════════════════════════════
-- `ultimo_veredicto` es MEMORIA («esta pieza ANDUVO alguna vez») y **NO se degrada cuando
-- un re-verify posterior falla**. Las mediciones vivas van a `causa` /
-- `ultima_verificacion` / `evidencia`, que sí se pisan en cada verify.
--
-- Está calcado del molde, donde es explícito: el barrido de arranque de conectores escribe
-- SÓLO `conexion` y `credencial` y jamás toca el veredicto — «escribir sin_medir encima de
-- un verde que sigue siendo cierto sería borrar evidencia buena»
-- (`centro_conexiones.py:1902-1904`).
--
-- Una fila con `ultimo_veredicto='probado'` Y `causa='sin_runtime'` NO es contradicción:
-- es el estado REGRESIÓN (anduvo, hoy falla), y es lo que la mantiene en el LOCAL con su
-- causa operativa en vez de mandarla a la aduana.
--
-- ⚠️ SI ALGO DEGRADA `ultimo_veredicto` A 'roto', EL ANTI-YO-YO MUERE EN SILENCIO: tras el
-- próximo arranque la pieza aparece en la aduana como si nunca hubiera andado. `verify_f4c`
-- prueba el ciclo entero con un PROCESO NUEVO que relee de disco.
-- ⚠️ IDÉNTICO a `_MIGRACION_8_MODELOS_ESTADO` de `sqlite_db.py`.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS modelos_estado (
  user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  modelo_id           TEXT NOT NULL,
  via                 TEXT,
  ultimo_veredicto    TEXT,
  causa               TEXT,
  ultima_verificacion TEXT,
  evidencia           TEXT,
  PRIMARY KEY (user_id, modelo_id)
);
CREATE INDEX IF NOT EXISTS idx_modelos_estado_user
  ON modelos_estado(user_id, ultima_verificacion);

-- ───────────────────────────────────────────────────────────────────────────
-- ÍNDICES — los 28 btree de Postgres. Los 3 GIN quedan fuera a propósito (D2).
-- SQLite soporta índices parciales (WHERE) y orden DESC: se replican tal cual.
-- Los de `conexiones` (21) son propios: esa tabla no existe en Postgres.
-- ───────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_puppets_owner          ON puppets(owner_id);
CREATE INDEX IF NOT EXISTS idx_puppets_nicho          ON puppets(nicho);
CREATE INDEX IF NOT EXISTS idx_runs_puppet            ON runs(puppet_id);
CREATE INDEX IF NOT EXISTS idx_runs_space             ON runs(space_id);
CREATE INDEX IF NOT EXISTS idx_runs_parent            ON runs(parent_run_id, hop_index) WHERE parent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_outputs_run            ON outputs(run_id);
CREATE INDEX IF NOT EXISTS idx_historial_user         ON historial(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chats_owner            ON chats(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat     ON chat_messages(chat_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_turn_role
  ON chat_messages(chat_id, client_turn_id, role) WHERE client_turn_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_methods_owner          ON methods(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_method_runs_method     ON method_runs(method_id);
CREATE INDEX IF NOT EXISTS idx_method_runs_owner      ON method_runs(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_instructions_scope     ON instructions(user_id, puppet_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_memories_puppet  ON agent_memories(puppet_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shared_memories_comp   ON shared_memories(composition_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_account_memories_owner ON account_memories(owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_comp    ON knowledge_docs(composition_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_comp  ON knowledge_chunks(composition_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc   ON knowledge_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_job_queue_status       ON job_queue(status);
CREATE INDEX IF NOT EXISTS idx_job_queue_run          ON job_queue(run_id);
CREATE INDEX IF NOT EXISTS idx_job_queue_user         ON job_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_job_queue_claim        ON job_queue(priority DESC, available_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_job_queue_reclaim      ON job_queue(heartbeat_at) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_held_actions_run       ON held_actions(run_id);
CREATE INDEX IF NOT EXISTS idx_held_actions_status    ON held_actions(status);
CREATE INDEX IF NOT EXISTS idx_instr_run              ON instrumentation_logs(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_auth_uid  ON users(auth_uid) WHERE auth_uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_pending_purge    ON users(purge_after) WHERE deleted_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conexiones_owner       ON conexiones(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_conexiones_habilitado  ON conexiones(user_id) WHERE habilitado = 1;
