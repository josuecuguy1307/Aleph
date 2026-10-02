-- 0004_held_action_provenance — PROVENANCE del árbol de delegación en held_actions (Step 2 · B1).
--
-- POR QUÉ: con la delegación agente→agente (B1), una acción de alta consecuencia RETENIDA por el
-- gate puede originarse dentro de un SUB-AGENTE y subir (hoist) al top-level para ser aprobable por
-- HTTP. El runtime ya calcula `agent_path` (raíz→hoja: qué sub-agente pidió el OK), `via_delegation`
-- (si vino de un hijo) y `depth`, pero esos datos vivían SÓLO en la respuesta efímera del run — un
-- re-read del DB (recarga de la página de aprobaciones, o un listado de pendientes tras reinicio)
-- perdía a QUÉ sub-agente atribuir la acción. La INVARIANTE de dinero (la held sigue gateada y
-- aprobable, re-armada desde `recipe`) NUNCA dependió de esto; el impacto era de auditoría/UX, no de
-- privilegio. Esta migración persiste la proveniencia para que el árbol sobreviva a un round-trip.
--
-- IDEMPOTENTE: ADD COLUMN IF NOT EXISTS — re-correr no rompe una base que ya la tenga.

ALTER TABLE held_actions ADD COLUMN IF NOT EXISTS agent_path     JSONB;
ALTER TABLE held_actions ADD COLUMN IF NOT EXISTS via_delegation BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE held_actions ADD COLUMN IF NOT EXISTS depth          INTEGER;
