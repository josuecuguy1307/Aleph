-- 0021 · RESERVA AL TRAER DESDE EL CATÁLOGO PÚBLICO.
--
-- Aviso medido y persistido para una pieza cuyo origen o manifest no se pudo confirmar.
-- No es `estado_interno` (deuda de Aleph, invisible) ni `ultimo_veredicto` (medición viva).
-- JSONB del contrato se representa como TEXT en la tabla `conexiones`, igual que las demás
-- columnas JSON de este registro. NULL conserva por completo las filas existentes.

ALTER TABLE conexiones ADD COLUMN reserva TEXT DEFAULT NULL;
