-- 0010_account_memories — MEMORIA DE CUENTA por owner_id (Sistema 2, ORDEN 2 del MD de memoria).
--
-- POR QUÉ: A3 (agent_memories) es memoria del AGENTE (por puppet_id) y B2 (shared_memories) es del
-- EQUIPO (por composición). Faltaba el Sistema 2: memoria de la CUENTA = hechos sobre LA PERSONA
-- (idioma, preferencias, contexto, cómo reportarle). NACE acá con scope propio: TODO agente del
-- dueño la LEE al armar su framing (para tratar al usuario como quien es, sin re-presentación),
-- cruzando por encima de agentes y composiciones — a diferencia de A3/B2 que están AISLADAS por
-- pieza/Cuarto.
--
-- PERTENENCIA: keyed por owner_id = users(id) (la PERSONA, no un agente ni un Cuarto). El dueño ES
-- el usuario directamente → authz anti-IDOR por _authorize(user_id, ...) en el router (sin la
-- indirección puppet_owner de A3/B2). FK ON DELETE CASCADE: borrar la cuenta borra su memoria.
--
-- FRONTERA DURA (una dirección, MD §Relación): los agentes LEEN la cuenta; lo episódico de un
-- agente JAMÁS sube solo acá; la cuenta JAMÁS inyecta datos de un proyecto en otro. El ASCENSO
-- proyecto→cuenta es SÓLO por propuesta-con-OK del usuario (el gate de propuesta = ORDEN 5 del MD).
-- Por eso en ORDEN 2 NO hay auto-write: esta tabla se puebla vía el gate (orden 5), el panel o la
-- captura explícita del usuario — "se PROPONE, no se guarda sola". La CRUD existe (repo), pero el
-- run NO escribe cuenta automáticamente.
--
-- PROVENANCE (regla dura del MD): cada entrada distingue hecho (el usuario lo dijo) de inferencia
-- (el agente lo dedujo). Las inferencias JAMÁS se tratan como autorización. Va en meta.provenance,
-- default fail-safe = inferencia. AUTORIZACIONES NUNCA PERSISTEN: dinero/envío re-gatea siempre; la
-- memoria de cuenta no puede abrir un gate (defensa en profundidad + assert_invariant en runtime).
--
-- CAPS por TIER: nº de entradas y bytes los impone el runtime (recipe_enforcer.TIER_ACCOUNT_MEMORY_
-- CAPS), NO editable por receta — esta tabla no los codifica. GRANDE→COMPACTO: content ya viene
-- destilado/acotado (lo que entra al framing); cuerpo grande usa uri como handle (artifacts-por-
-- handle), nunca crudo.

CREATE TABLE IF NOT EXISTS account_memories (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- la CUENTA/persona dueña
  source      TEXT NOT NULL DEFAULT 'agent',      -- 'agent' (propuesta destilada, gated orden 5) | 'user' (el usuario lo confirmó/dijo)
  content     TEXT NOT NULL,                       -- el hecho sobre la persona, ya compacto (entra al framing)
  bytes       BIGINT NOT NULL DEFAULT 0,           -- tamaño de content (contabilidad de caps)
  pinned      BOOLEAN NOT NULL DEFAULT TRUE,       -- entra al framing PINEADO de CUALQUIER run del dueño
  uri         TEXT,                                -- handle a un cuerpo grande persistido (opcional)
  meta        JSONB,                               -- {provenance: hecho|inferencia, run_id, ...}
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- lectura por cuenta, más-reciente-primero (arma el bloque pineado de cuenta y el panel).
CREATE INDEX IF NOT EXISTS idx_account_memories_owner
  ON account_memories (owner_id, created_at DESC);
