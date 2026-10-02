-- 0017_billing_columnas_reales — corrige lo que la 0016 dejó mal
--
-- QUÉ PASÓ: la 0016 cerró la brecha de esquema que producción tenía, pero al escribir
-- `billing_ledger` lo hice de memoria en vez de copiar la definición real de
-- `platform/db/billing_schema.sql`. Resultado: la tabla existía pero con 10 columnas
-- de menos y un `billing_stripe_events` con `at` en lugar de `processed_at`. Lo detectó
-- el diff local↔producción que se corrió DESPUÉS de aplicar la 0016 — que es
-- exactamente para lo que se corre un diff después de migrar, y no antes.
--
-- POR QUÉ NO SE EDITA LA 0016: el runner valida por checksum. Editar una migración ya
-- aplicada produce DRIFT y rompe la garantía de que "misma versión = mismo esquema en
-- todas las bases". Se corrige hacia adelante, siempre.
--
-- ADITIVA E IDEMPOTENTE: en la base de DESARROLLO estas columnas ya existen (nacieron
-- de billing_schema.sql), así que los ADD COLUMN IF NOT EXISTS son no-ops ahí. En
-- producción completan la tabla, que está vacía.

-- ── billing_ledger: las columnas del contrato de COST-EVENT (§4.6) ────────────
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS seq               INTEGER;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS kind              TEXT;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS tool              TEXT;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS server            TEXT;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS prompt_tokens     BIGINT NOT NULL DEFAULT 0;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS completion_tokens BIGINT NOT NULL DEFAULT 0;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS total_tokens      BIGINT NOT NULL DEFAULT 0;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS tokens_measured   BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS price_source      TEXT;
ALTER TABLE billing_ledger ADD COLUMN IF NOT EXISTS created_at        TIMESTAMPTZ NOT NULL DEFAULT now();

-- `tokens_in`/`tokens_out`/`at` fueron invención de la 0016 y no existen en el esquema
-- real; se dejan si están (vacías, sin lectores) en vez de dropear columnas — un DROP
-- en una migración es irreversible y acá no compra nada.

-- ── billing_stripe_events: el nombre real de la marca de tiempo ───────────────
ALTER TABLE billing_stripe_events ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ NOT NULL DEFAULT now();
