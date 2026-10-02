-- 0014_subscriptions — EL PUENTE PAGO → TIER (Step 5 · Casa 1 · P1)
--
-- QUÉ CIERRA: hasta esta migración NINGUNA ruta de producción escribía `users.tier`
--   (auditado en STEP5-AUDIT-0.md §0.2: los únicos call-sites de repo.set_tier eran
--   qa/* y tests). La muralla premium existía y estaba certificada, pero no había
--   puerta: la única vía a premium era un UPDATE manual sobre la DB. Acá nace la puerta.
--
-- DOCTRINA (heredada de MURALLA-PREMIUM.md, no se relaja):
--   · `users.tier` sigue siendo LA fuente de verdad que leen los muros. Estas tablas
--     NO son consultadas por ningún gate: son el LIBRO CONTABLE que decide qué se
--     escribe en users.tier. Un gate que empiece a leer `subscriptions` está roto.
--   · Fail-closed: ante duda, free. Un estado de suscripción desconocido NO asciende.
--   · El tier se DERIVA del estado (platform/payments/effects.apply_tier_effect),
--     jamás se copia de lo que diga el procesador.
--
-- PROCESSOR-AGNOSTIC (§4-bis de la directiva): ninguna columna nombra a Dodo. `processor`
--   es texto libre y `external_id` es el id del lado de ellos. Cambiar de procesador es
--   insertar con otro `processor`, no migrar el schema.

-- ───────────────────────────────────────────────────────────────────────────
-- 14.1 subscriptions — el estado de la relación comercial con UNA cuenta.
--   Una fila por (processor, external_id). Una cuenta puede tener varias filas a lo
--   largo del tiempo (canceló y volvió, o compró lifetime además del mensual): el tier
--   efectivo se deriva del CONJUNTO de sus filas, no de una sola. Por eso NO hay UNIQUE
--   sobre account_id.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  processor           TEXT NOT NULL,              -- 'dodo' | 'paddle' | … (nunca un enum: los procesadores cambian)
  external_id         TEXT NOT NULL,              -- subscription_id del procesador; para one-time, el payment_id
  plan                TEXT NOT NULL,              -- 'monthly' | 'annual' | 'lifetime'
  status              TEXT NOT NULL,              -- vocabulario PROPIO: alta|renovada|en_gracia|terminal|baja
                                                  -- (traducido por el adaptador; NUNCA el string crudo del procesador)
  current_period_end  TIMESTAMPTZ,                -- fin del período pagado. NULL para lifetime (no vence).
  grace_until         TIMESTAMPTZ,                -- hasta cuándo se tolera un cobro fallido RECUPERABLE (on_hold).
  last_event_at       TIMESTAMPTZ,                -- timestamp del PAYLOAD del último evento aplicado.
                                                  -- ⚠ Es el reloj anti-desorden: un evento más viejo que esto se DESCARTA.
                                                  -- Los webhooks no llegan en orden (regla 4 del §2).
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- La identidad de una suscripción es (procesador, su id). El upsert del webhook depende
-- de este UNIQUE: sin él, un reintento crearía una fila nueva en vez de actualizar.
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_processor_external
  ON subscriptions(processor, external_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_account ON subscriptions(account_id);
-- El job de reconciliación (P5) barre por acá: lo no-terminal es lo que puede derivar.
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);

-- ───────────────────────────────────────────────────────────────────────────
-- 14.2 payment_webhook_events — LA IDEMPOTENCIA, y es la PK, no un chequeo en código.
--
--   La clave es el header `webhook-id` (Standard Webhooks), NO un campo del body:
--   verificado sobre un evento REAL en test_mode (reports/step5/P0-evento-crudo.json →
--   webhook-id = msg_3GmDw79XKEe61LJJWv8VMCKcQKl). El body NO trae id de evento.
--
--   Dodo reintenta 8 veces con backoff hasta ~28h si no recibe 2xx: el MISMO evento
--   llega repetido. `INSERT ... ON CONFLICT DO NOTHING RETURNING` decide en el motor
--   si este proceso es el primero; si no devuelve fila, ya se procesó y se ACKea igual.
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payment_webhook_events (
  webhook_id    TEXT PRIMARY KEY,                 -- el header `webhook-id`. LA llave de idempotencia.
  processor     TEXT NOT NULL,
  event_type    TEXT NOT NULL,                    -- string crudo del procesador (para forense; NO se interpreta acá)
  payload       JSONB NOT NULL,                   -- el evento tal cual llegó, ya verificado por firma
  event_at      TIMESTAMPTZ,                      -- timestamp del PAYLOAD (para ordenar), no de llegada
  received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at  TIMESTAMPTZ,                      -- NULL = aceptado pero todavía no aplicado (ACK rápido + background)
  outcome       TEXT                              -- 'applied' | 'ignored_unknown' | 'stale' | 'error:<motivo>'
);
CREATE INDEX IF NOT EXISTS idx_pwe_unprocessed ON payment_webhook_events(received_at)
  WHERE processed_at IS NULL;   -- la cola del worker: lo aceptado que todavía no se aplicó

-- ───────────────────────────────────────────────────────────────────────────
-- 14.3 tier_audit — POR QUÉ una cuenta tiene el tier que tiene.
--   `users.tier` es un solo campo mutable: sin esto, un ascenso indebido no tiene rastro.
--   Toda escritura de tier pasa por acá (repo.set_tier endurecido).
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tier_audit (
  id           BIGSERIAL PRIMARY KEY,
  account_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tier_before  TEXT,
  tier_after   TEXT NOT NULL,
  reason       TEXT NOT NULL,                     -- 'webhook:<tipo>' | 'reconciliation' | 'manual:<quien>' | 'test'
  webhook_id   TEXT,                              -- si vino de un evento, cuál (traza completa pago→tier)
  at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tier_audit_account ON tier_audit(account_id, at DESC);
