-- Puppet AI / Aleph — Billing schema (F0 · track T7-billing)
-- ADITIVO sobre schema.sql. Corre DENTRO de la misma base lógica `puppet_ai`.
-- Idempotente (IF NOT EXISTS): se puede aplicar varias veces sin romper.
--
-- T7 = dueño de billing/metering/quota. CONSUME el COST-EVENT (§4.6) que produce
-- T5/T4 y lo convierte en (1) un LEDGER por-call, (2) un metering por-usuario,
-- (3) un cap de presupuesto que CORTA al usuario que se excede (no funde la cuenta).
-- No toca el gateway de T5: sólo consume sus cost-events.
--
-- INVARIANTE: `user_id` scopea TODO (AUTH §4.5). Ninguna fila de costo se lee sin scope.

-- ───────────────────────────────────────────────────────────────────────────
-- 9. billing_ledger — UNA fila por COST-EVENT consumido (§4.6). El registro per-call.
--    Es el libro mayor: el token MEDIDO + el usd a TARIFA documentada (o NULL si el
--    modelo no tiene tarifa — NO se inventa, igual que lo emite T5). Tools locales = $0.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS billing_ledger (
  id                 BIGSERIAL PRIMARY KEY,
  user_id            UUID REFERENCES users(id) ON DELETE CASCADE,  -- NULL = run anónimo (no se factura a nadie)
  run_id             TEXT,                  -- el run que lo originó (TEXT: tolera runs inline sin fila en `runs`)
  seq                INTEGER NOT NULL,      -- orden del evento dentro del run (idempotencia + auditoría)
  kind               TEXT NOT NULL,         -- model | tool
  model              TEXT,                  -- id del modelo (kind=model)
  tool               TEXT,                  -- nombre de la tool (kind=tool)
  server             TEXT,                  -- belt server de la tool (kind=tool)
  prompt_tokens      BIGINT NOT NULL DEFAULT 0,
  completion_tokens  BIGINT NOT NULL DEFAULT 0,
  total_tokens       BIGINT NOT NULL DEFAULT 0,
  usd                NUMERIC(18,8),         -- NULL si el modelo no tiene tarifa documentada (no se inventa)
  tokens_measured    BOOLEAN NOT NULL DEFAULT false,  -- ¿los tokens vinieron del `usage` del proveedor?
  price_source       TEXT,                  -- fuente de la tarifa (auditoría)
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_billing_ledger_user ON billing_ledger(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_ledger_run  ON billing_ledger(run_id);

-- ───────────────────────────────────────────────────────────────────────────
-- 10. billing_runs_ingested — marca de IDEMPOTENCIA por run. Un run se ingesta UNA vez:
--     re-procesar la misma salida (retry, doble-emisión por SSE) NO duplica el cobro.
--     El cost-event de §4.6 no trae id propio → el ligador de idempotencia es el run_id.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS billing_runs_ingested (
  run_id       TEXT PRIMARY KEY,
  user_id      UUID,
  events       INTEGER NOT NULL DEFAULT 0,    -- cuántos cost-events trajo el run
  usd_total    NUMERIC(18,8) NOT NULL DEFAULT 0,
  ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_billing_runs_ingested_user ON billing_runs_ingested(user_id);

-- ───────────────────────────────────────────────────────────────────────────
-- 11. billing_quota — el PRESUPUESTO por usuario, como DELTAS sobre el cap del tier.
--     El cap BASE viene del tier (users.tier → billing.TIER_CAPS_USD) y se computa al leer,
--     así un upgrade de tier se refleja solo. Acá guardamos sólo lo que cambia por usuario:
--       credits_usd    — presupuesto COMPRADO (Stripe top-up) por encima del tier.
--       self_limit_usd — tope que el PROPIO usuario se pone (autocontrol); NULL = sin tope.
--     Cap efectivo = min(base_tier + credits, self_limit ?? ∞). Ver billing.get_cap.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS billing_quota (
  user_id             UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  credits_usd         NUMERIC(18,8) NOT NULL DEFAULT 0,   -- comprado vía Stripe (suma al cap del tier)
  self_limit_usd      NUMERIC(18,8),                      -- tope auto-impuesto (NULL = ninguno)
  stripe_customer_id  TEXT,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ───────────────────────────────────────────────────────────────────────────
-- 12. billing_stripe_events — IDEMPOTENCIA de webhooks de Stripe. Stripe puede reenviar
--     el mismo evento; acreditamos UNA sola vez (PK = event id de Stripe).
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS billing_stripe_events (
  event_id     TEXT PRIMARY KEY,             -- evt_... de Stripe
  type         TEXT,
  user_id      UUID,
  usd          NUMERIC(18,8),
  processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
