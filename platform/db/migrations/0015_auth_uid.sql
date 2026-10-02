-- 0015_auth_uid — EL PUENTE DE IDENTIDAD (CONTRACT-AUTH-v2)
--
-- QUÉ RESUELVE: Supabase pasa a ser el proveedor de IDENTIDAD (Google · GitHub ·
-- magic-link · email+password). Nuestro Postgres sigue siendo el dueño del TIER.
-- Hace falta una sola cosa para unirlos: saber qué cuenta nuestra corresponde a qué
-- usuario de Supabase.
--
-- POR QUÉ UNA COLUMNA PUENTE Y NO REESCRIBIR users.id:
--   La alternativa era hacer que `public.users.id` FUERA el `auth.users.id`. Más
--   "limpio" en el papel, pero obliga a reescribir el id en TODAS las tablas que
--   referencian users(id) — puppets, runs, keys, memories, subscriptions, tier_audit,
--   held_actions… Una migración pesada, irreversible, y que ACOPLA nuestro id interno
--   al proveedor de identidad de turno. Es el mismo error que el §4-bis nos hizo evitar
--   con los pagos: si mañana no es Supabase, una columna se cambia; un id reescrito en
--   quince tablas hay que volver a migrarlo.
--   Costo aceptado: un lookup extra por resolución de sesión (JWT.sub → auth_uid →
--   users.id). Es un índice único: microsegundos, y cacheable.
--
-- NO ROMPE NADA DE v1: la columna es NULLABLE. Una cuenta sin `auth_uid` sigue
-- funcionando por el camino Fernet mientras dure la transición.

ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_uid UUID;

-- UNIQUE, no PK: un usuario de Supabase mapea a EXACTAMENTE una cuenta nuestra.
-- Sin esta restricción, dos cuentas podrían reclamar el mismo auth_uid y la resolución
-- de sesión devolvería una u otra según el orden del planner — un bug no determinista
-- en el camino de identidad, que es el peor lugar donde tenerlo.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_auth_uid ON users(auth_uid)
  WHERE auth_uid IS NOT NULL;

COMMENT ON COLUMN users.auth_uid IS
  'auth.users.id de Supabase (CONTRACT-AUTH-v2). NULL = cuenta legacy con sesión '
  'Fernet propia. El tier NUNCA sale de acá: sigue en users.tier, server-side.';
