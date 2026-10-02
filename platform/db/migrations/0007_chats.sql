-- 0007_chats — HISTORIAL Y RETOMAR de la Sala (Ola UX-UNIVERSAL · A1/A2/A3/A6).
--
-- POR QUÉ: hoy la Sala NO tiene conversaciones persistentes: cada turno-obra acuña un
-- space_id fresco (los eventos quedan huérfanos por turno en data/espacios/), la charla
-- pura ni siquiera persiste (burbujas solo-DOM), y el backend recibe un `prompt` suelto
-- sin memoria de turnos previos. Un "como te decía…" se pierde. Esta migración crea el
-- REGISTRO REAL de la conversación: la unidad que el usuario lista, retoma y busca.
--
-- QUÉ ES UN CHAT: una conversación de la Sala con UNA composición (puppet guardado) o
-- con el agente inline (puppet_id NULL). Sus mensajes son los turnos reales: texto del
-- usuario y respuesta del agente. Los turnos-OBRA además guardan su space_id (→ el
-- events.jsonl del run: la narrativa/evidencia se re-proyecta de ahí, no se duplica acá)
-- y su run_id (→ runs/instrumentation, el moat). ARTIFACTS-POR-HANDLE intacta: content
-- es SIEMPRE texto (prompt/answer); jamás bytes de artifacts.
--
-- PERTENENCIA (anti-IDOR): el chat pertenece a la CUENTA (user_id) y se scope-a por
-- composición (puppet_id). Composición B no ve los chats de A: el router verifica
-- session.owner == chats.user_id en cada acceso (mismo patrón _mem_gate de A3).
--
-- REHIDRATACIÓN: al correr un turno con chat_id, el backend arma un bloque de historial
-- (budget acotado, más-reciente-primero) y lo antepone al prompt QUE VA AL CEREBRO;
-- runs.intent conserva el prompt crudo. Cero cambios en el assembler.

CREATE TABLE IF NOT EXISTS chats (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  puppet_id   UUID REFERENCES puppets(id) ON DELETE CASCADE,  -- NULL = agente inline de la Sala
  title       TEXT NOT NULL DEFAULT '',                        -- primer mensaje [:80]; editable
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id          BIGSERIAL PRIMARY KEY,
  chat_id     UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('user','agent')),
  kind        TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat','obra')),
  content     TEXT NOT NULL,          -- texto real del turno (prompt del user / answer del agente)
  space_id    TEXT,                   -- turnos obra: liga al events.jsonl del run (narrativa/evidencia)
  run_id      UUID,                   -- turnos obra: liga a runs/instrumentation (sin FK: runs puede podarse)
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- lista de chats por cuenta/composición, más recientes primero
CREATE INDEX IF NOT EXISTS idx_chats_owner ON chats (user_id, updated_at DESC);
-- rehidratación y paginado dentro de un hilo
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages (chat_id, id);
