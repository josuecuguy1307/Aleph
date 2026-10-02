-- 0008_held_turn_text — el "porque Y" de la card de aprobación (Ola UX-UNIVERSAL · B4).
--
-- POR QUÉ: la card del gate mostraba QUÉ va a hacer la tool (copy de regla) pero no la
-- INTENCIÓN del turno que pidió la acción. Ese texto (msg.content del cerebro, el turno
-- exacto que emitió el tool_call) ya viaja ahora en el evento gate_waiting y en la held
-- del record (recipe_assembler); esta columna lo hace DURABLE: un re-read post-reinicio
-- (recarga de página, listado de pendientes) conserva el porqué junto a la acción.
-- Acotado a 400 chars en origen; puede ser NULL (modelos text-call sin prosa).

ALTER TABLE held_actions ADD COLUMN IF NOT EXISTS turn_text TEXT;
