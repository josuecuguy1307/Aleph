-- 0019_multiagente_saltos — el SALTO de una cadena multiagente, enlazado POR CAMPO.
--
-- Spec: docs/multiagente.md §4.
--
-- ── LA DECISIÓN, Y POR QUÉ ES ASÍ ────────────────────────────────────────────
-- Un run multiagente NO estrena un ciclo de vida. Cada salto de la cadena es un run
-- NORMAL: nace por `repo.create_run`, late en `run_lifecycle._VIVOS`, muere por
-- `repo.finish_run`, y el reaper del boot lo cubre igual que a cualquier otro. Lo único
-- que agrega el multiagente es el ENLACE: cuatro columnas NULABLES sobre `runs`.
--
-- Un `ALTER TABLE ... ADD COLUMN` nulable no puede regresionar a nadie: toda fila
-- existente queda con NULL, y NULL significa exactamente lo que significaba antes de esta
-- migración — "run normal, sin padre, sin modo". Cero backfill, cero re-interpretación de
-- datos viejos. Ésa es la razón de que el enlace sea un CAMPO y no una tabla de aristas:
-- una tabla nueva habría exigido que algo la escribiera dentro del ciclo de vida del run,
-- que es justo lo que no se toca.
--
-- ── LAS CUATRO COLUMNAS ──────────────────────────────────────────────────────
--   parent_run_id   el run del PADRE (el globo). NULL = run normal.
--   hop_index       la posición del salto en la cadena, 0-based. NULL = no es un salto.
--   hop_latency_ms  LA LATENCIA MEDIDA de ese salto. Es el primer dato PROPIO que el
--                   diseño pide: la referencia de industria es 1–3 s/salto y el número
--                   nuestro sale de acá, medido con perf_counter, no citado.
--   modo            el contrato de ejecución del run PADRE (cadena|orquesta|oficina|
--                   abanico). NULL = run normal. Es lo que hace identificable a un padre
--                   sin tener que salir a contar hijos.
--
-- `hop_latency_ms` va en MILISEGUNDOS ENTEROS a propósito: es el tipo que sobrevive el
-- mapeo Postgres→SQLite sin volverse REAL (el schema del cliente sólo admite
-- TEXT|INTEGER|BLOB, y `test_schema_sqlite.py` lo verifica tabla por tabla). Un `double`
-- acá obligaría a divergir los dos dialectos por una precisión que nadie usa.
--
-- ON DELETE SET NULL, no CASCADE: si se borra el padre, los saltos son runs REALES que
-- ocurrieron y cuyo costo se facturó — se quedan huérfanos y honestos, no se evaporan.

ALTER TABLE runs ADD COLUMN IF NOT EXISTS parent_run_id  UUID REFERENCES runs(id) ON DELETE SET NULL;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS hop_index      INTEGER;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS hop_latency_ms BIGINT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS modo           TEXT;

-- La consulta que va a existir es "dame los saltos de este padre, en orden". Índice
-- PARCIAL: los runs normales (parent_run_id IS NULL, que son y van a seguir siendo la
-- inmensa mayoría) no pagan ni un byte de índice.
CREATE INDEX IF NOT EXISTS idx_runs_parent
  ON runs (parent_run_id, hop_index)
  WHERE parent_run_id IS NOT NULL;
