-- 0024_legacy_session_version — revocación de sesiones Fernet legacy.
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS session_version BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN users.session_version IS
  'Generación de sesiones Fernet; cambia al rotar contraseña o cerrar sesión.';
