-- 0013_method_paused_incomplete.sql — ticket 10: estado RETOMABLE 'paused_incomplete'.
--
-- Un método-dirigido que pausa por ESPERA DE ACCIÓN HUMANA (un paso manual/no-verificable,
-- ej. "traer el flightcase al taller") o que simplemente no llegó a terminar quedaba sellado
-- 'abandoned' por method_harness.finish(). Dos daños:
--   (a) 'abandoned' es una lectura ENGAÑOSA para el deep-recall posterior ("¿cómo fue la
--       inspección del martes?" veía "abandonada" un método que corrió y pausó legítimo);
--   (b) 'abandoned' NO está en _RESUMABLE → resume/remedy devolvían 409 (dead-end): el run
--       quedaba inalcanzable por CUALQUIER camino de retoma (grafo o Sala).
--
-- Se agrega el valor 'paused_incomplete' al CHECK. El arnés lo sella en su rama de cierre
-- (antes 'abandoned') y lo suma a _RESUMABLE (arnés + methods_router) → el método retoma
-- desde el paso pausado por continuación server-side. 'abandoned' se conserva SOLO para su
-- uso intencional (claim_continuation: sellar el run VIEJO al reclamar una continuación).
ALTER TABLE method_runs DROP CONSTRAINT IF EXISTS method_runs_status_check;
ALTER TABLE method_runs ADD CONSTRAINT method_runs_status_check
  CHECK (status IN ('active', 'waiting_checkpoint', 'paused_failure', 'paused_user',
                    'scheduled_retry', 'completed', 'abandoned', 'paused_incomplete'));
