-- 0011_account_deletion — BORRADO DE CUENTA con soft-delete (ticket 2 · sprint pre-launch).
--
-- SEMÁNTICA (reports/step-4.5-e2e/aleph-sprint-prelaunch.md §2):
--   • Al pedir el borrado: el ACCESO muere YA (deleted_at NOT NULL bloquea toda sesión en el
--     middleware del backend) pero los DATOS quedan CONGELADOS — reversible re-logueando dentro
--     de la ventana. EXCEPCIÓN: las credenciales OAuth se revocan AL INSTANTE (irreversible;
--     eso no vive acá — es un DELETE inmediato sobre `keys` + revoke HTTP best-effort).
--   • purge_after = fecha EXACTA de la purga total (deleted_at + 30 días). Se PERSISTE (no se
--     recalcula) para que el mail al usuario y el purgador usen LA MISMA fecha, sin drift.
--   • Día 30: purga total cascadeada (app/phase1/account_deletion.py) + test de cero huérfanas.
--
-- REACTIVACIÓN: re-login exitoso dentro de la ventana → ambos campos vuelven a NULL (los datos
-- nunca se tocaron). Un usuario activo tiene deleted_at IS NULL — el default de toda fila.

ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at  TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS purge_after TIMESTAMPTZ;

-- El purgador escanea SOLO cuentas en ventana → índice parcial (las activas no pagan nada).
CREATE INDEX IF NOT EXISTS idx_users_pending_purge
  ON users (purge_after)
  WHERE deleted_at IS NOT NULL;
