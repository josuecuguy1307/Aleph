-- 0016_cierra_brecha_esquema — LO QUE LA CADENA DE MIGRACIONES NUNCA TUVO
--
-- CÓMO SE ENCONTRÓ: al cablear el front de v2 (CONTRACT-AUTH-v2), un test contra la
-- base de PRODUCCIÓN reventó con `column "password_hash" of relation "users" does not
-- exist`. El diff completo local↔producción reveló que faltaban 1 columna y 4 tablas.
--
-- LA CAUSA RAÍZ: dos archivos de esquema vivían FUERA de la cadena de migraciones —
-- `platform/db/schema.sql` (que agrega users.password_hash con un ALTER) y
-- `platform/db/billing_schema.sql` (las 4 tablas de billing). En el árbol de desarrollo
-- alguien los corrió a mano alguna vez y quedaron; producción se construyó SÓLO con
-- `migrate.py`, así que nació sin ellos.
--
-- POR QUÉ IMPORTABA MÁS DE LO QUE PARECE:
--   · sin `users.password_hash`, el login por email+password NO EXISTE en producción:
--     `register_user`/`login_user` fallan con un error de SQL, no con un mensaje.
--   · sin las tablas de billing, el corte por presupuesto (billing.preflight, el que
--     P12 acaba de cablear a la sesión) revienta en el camino de TODO run.
--
-- Ninguna de las dos cosas se habría notado en dev, donde las tablas sí están. Se
-- habrían descubierto con el primer usuario real.
--
-- LECCIÓN, escrita acá para que quede junto al remedio: un esquema que no está en una
-- migración NO EXISTE para una base nueva. `schema.sql` y `billing_schema.sql` quedan
-- como documentación/bootstrap local; la cadena de migraciones es la única fuente de
-- verdad de lo que una base tiene.

-- ───────────────────────────────────────────────────────────────────────────
-- 16.1 users.password_hash — el camino email+password
--   scrypt$<salt_hex>$<dk_hex>. NULL = cuenta sin contraseña (OAuth puro o legacy).
--   ⚠️ Ese NULL además es la defensa anti pre-hijacking de v2: sólo una cuenta SIN
--   password_hash puede ser reclamada por un login de proveedor (ver
--   platform/auth/supabase_jwt.resolver_cuenta). O sea que esta columna no es sólo
--   almacenamiento: es parte de una decisión de seguridad.
-- ───────────────────────────────────────────────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- ───────────────────────────────────────────────────────────────────────────
-- 16.2 billing — metering + cap de presupuesto (track T7)
--   OJO, eje distinto del de `subscriptions` (0014): acá se mide GASTO en USD y se
--   corta al que excede; allá se activa el FLAG DE TIER. Dos cosas separadas a
--   propósito; fusionarlas sería el error.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS billing_ledger (
  id           BIGSERIAL PRIMARY KEY,
  user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
  run_id       TEXT,
  model        TEXT,
  tokens_in    INTEGER,
  tokens_out   INTEGER,
  usd          NUMERIC(18,8),          -- NULL = modelo sin tarifa documentada; NO se inventa
  at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_billing_ledger_user ON billing_ledger(user_id);

CREATE TABLE IF NOT EXISTS billing_runs_ingested (
  run_id       TEXT PRIMARY KEY,       -- idempotencia: un run se cobra UNA vez
  user_id      UUID,
  events       INTEGER NOT NULL DEFAULT 0,
  usd_total    NUMERIC(18,8) NOT NULL DEFAULT 0,
  ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_billing_runs_ingested_user ON billing_runs_ingested(user_id);

CREATE TABLE IF NOT EXISTS billing_quota (
  user_id             UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  credits_usd         NUMERIC(18,8) NOT NULL DEFAULT 0,   -- comprado, por encima del tier
  self_limit_usd      NUMERIC(18,8),                      -- tope que el usuario se pone; NULL = sin tope
  stripe_customer_id  TEXT,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS billing_stripe_events (
  event_id   TEXT PRIMARY KEY,         -- idempotencia del webhook de créditos
  type       TEXT,
  user_id    UUID,
  usd        NUMERIC(18,8),
  at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
