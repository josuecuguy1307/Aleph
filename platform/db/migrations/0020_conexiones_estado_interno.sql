-- 0020 · ESTADO INTERNO DE UNA CONEXIÓN · el usuario jamás ve nuestra deuda.
--
-- ORDEN DE PERSONA USUARIA (2026-08-04): la sección «Nos toca a nosotros» desaparece de la UI entera.
-- Una pieza que no se puede traer por un hueco NUESTRO —una receta con un placeholder sin
-- expandir, una ficha que contradice a su belt— no es un servicio del usuario a medias: es
-- trabajo nuestro pendiente. Mostrárselo le entrega una deuda que no contrajo y sobre la
-- que no puede hacer absolutamente nada.
--
-- POR QUÉ UNA COLUMNA Y NO UN BORRADO. Su data sirve: cuando el paso 2.5 sepa re-ingerirlas
-- bien, la receta, el belt y lo medido ya están. Borrarlas obligaría a redescubrirlas.
-- (El residuo puro —una entidad sin ficha ni belt real, basura de un experimento— sí se
-- borra: no hay nada que re-ingerir.)
--
-- POR QUÉ NO SE REUSÓ UNA COLUMNA EXISTENTE. `habilitado` es el PERMISO del usuario (la
-- lápida) y `ultimo_veredicto` es lo que midió el MOTOR. Meter acá un estado nuestro
-- confundiría tres cosas que caducan por motivos distintos, y la primera consecuencia sería
-- que despejar la deuda se vería como si el usuario hubiera desconectado algo.
--
--   estado_interno    NULL = normal (la abrumadora mayoría) · 'pendiente_ingesta' = no
--                     viaja a ninguna superficie de usuario; vive en el censo.
--   bloqueo_interno   el nombre del bloqueo, para que el censo lo reporte sin re-derivarlo
--                     (`receta_con_placeholder` · `ficha_contradice_belt` · …).
--
-- Aditiva y con default NULL: ninguna fila existente cambia de comportamiento.

ALTER TABLE conexiones ADD COLUMN estado_interno TEXT;
ALTER TABLE conexiones ADD COLUMN bloqueo_interno TEXT;

-- Índice parcial: la lectura caliente es «dame las que NO están retenidas», y sin esto
-- cada carga de pantalla escanea la tabla entera para descartar dos filas.
CREATE INDEX IF NOT EXISTS idx_conexiones_estado_interno
  ON conexiones (user_id, estado_interno);
