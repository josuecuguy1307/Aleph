-- 0018_chat_turn_idempotency — un submit del composer = un turno persistido.
--
-- `client_turn_id` nace en La Sala y se conserva durante los reintentos. La unicidad
-- por (chat, turno, rol) hace idempotentes tanto `_chat_gate` como la proyección de la
-- respuesta: un doble submit no agrega dos humanos y un replay no agrega dos agentes.

ALTER TABLE chat_messages
  ADD COLUMN IF NOT EXISTS client_turn_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_turn_role
  ON chat_messages (chat_id, client_turn_id, role)
  WHERE client_turn_id IS NOT NULL;
