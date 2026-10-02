# BILLING — track T7 (F0)

> **Owner: T7-billing.** Metering por-usuario + cap de presupuesto + Stripe.
> CONSUME el **COST-EVENT (§4.6)** que produce T5/T4 y la **AUTH/SESSION (§4.5)** de T6.
> **NO toca** el gateway de T5 (sólo consume sus cost-events).

## Qué hace
Convierte cada **COST-EVENT** de un run en plata medida y CORTA al usuario que excede su
presupuesto — sin fundir la cuenta (lo frena, no lo deja gastar de más sin techo).

1. **Ledger** (`billing_ledger`): una fila por cost-event (token medido + usd a tarifa
   documentada, o `NULL` si el modelo no tiene tarifa — **no se inventa**; tools locales = $0).
2. **Metering** (`billing.get_meter`): suma del ledger por `user_id` → gastado / cap / restante.
3. **Cap** (`billing.preflight`): si `remaining <= 0` → **corta** (HTTP **402**). El run NO arranca.
4. **Stripe**: comprar presupuesto sube el cap (`add_credit`); webhook firmado e idempotente.

## Archivos (área de T7)
| Archivo | Rol |
|---|---|
| `platform/db/billing_schema.sql` | tablas `billing_ledger`, `billing_runs_ingested`, `billing_quota`, `billing_stripe_events` (aditivo, `IF NOT EXISTS`) |
| `product/backend/app/phase1/billing.py` | lógica pura: ingest idempotente, metering, cap, self-limit, créditos |
| `product/backend/app/phase1/stripe_billing.py` | Checkout + verificación de firma de webhook (degrada honesto sin lib/key) |
| `product/backend/app/phase1/billing_router.py` | slice `/v1/billing/*` (owner-gated §4.5) |
| `product/backend/tests/phase1/test_billing.py` | 16 tests (offline + DB real + HTTP) |

## Costuras (lo que toco fuera de mis archivos, mínimo y marcado `# ── T7-billing ──`)
- `product/backend/app/main.py` — monta `build_billing_router(get_conn=...)` (1 bloque).
- `product/backend/app/phase1/router.py` — hook en `/v1/puppets/run` (+`/run/stream`):
  - **preflight ANTES** del executor → 402 si sobre el cap.
  - **ingest DESPUÉS** del executor → `record_run_cost(out["run_id"], user_id, out["cost_events"])`,
    idempotente por `run_id`. Lee `out.get("cost_events", [])`: vacío hasta que T5 mergee, real al mergear.
- `product/backend/requirements.txt` — `stripe>=9.0` (opcional; degrada honesto si falta).

## Endpoints `/v1/billing/*`
| Método | Ruta | Authz | Qué |
|---|---|---|---|
| GET | `/meter/{user_id}` | owner | gastado / cap / restante / over |
| GET | `/preflight/{user_id}` | owner | **EL CORTE** — 402 si excedió |
| POST | `/limit/{user_id}` | owner | el usuario se pone un tope (autocontrol) |
| POST | `/checkout` | owner | Stripe Checkout (comprar presupuesto) |
| POST | `/webhook/stripe` | firma | acredita el pago (idempotente por event_id) |
| GET | `/stripe-status` | — | diagnóstico (sin secretos) |

## Cap efectivo
`min(base_tier + créditos_comprados, self_limit ?? ∞)`. Base por tier (config en `billing.py`):
`free=$1`, `basico=$25`, `tecnico=$100`. Upgrade de tier se refleja solo; comprar créditos
sube el techo; el self-limit sólo lo BAJA (autocontrol).

## Verificado (DONE-BAR · contra entorno real, no self-report)
- ✅ **Un run incrementa el metered cost**: cost-events en la forma congelada §5 → `get_meter`
  sube exactamente el usd medido (token sí, usd sin-tarifa **no** suma). Idempotente por run_id.
- ✅ **Pasar el cap lo frena**: `POST /v1/puppets/run` de un usuario sobre el cap → **402**
  ANTES de gastar cognición (test sobre el router REAL). `/v1/billing/preflight` también 402.
- ✅ Authz §4.5: `/meter` sin sesión → 401, de otro → 403, dueño → 200.
- ✅ Stripe: degrada honesto sin configurar; mapeo `checkout.session.completed → crédito`;
  webhook sin firma verificable → no acredita.
- 16/16 tests verdes (`tests/phase1/test_billing.py`); app importa; sin regresión en los tests
  de los archivos tocados.

## Honesto (dependencias / follow-ups)
- **Live wire con T5**: la ingesta real desde un run en vivo se activa cuando T5 mergea
  (su assembler emite `record["cost_events"]` y su executor los expone en `out["cost_events"]`).
  El hook ya los lee; en este worktree aislado los runs traen `[]`, así que el incremento se
  verificó alimentando la **forma congelada §5** directo (mismo dato que emite T5).
- **Overspend de UN run en vuelo**: chequeamos ANTES y cobramos DESPUÉS — un run puede pasarse
  por su propio costo; el siguiente queda cortado (metering pre-pago estándar; documentado).
- **Período**: v1 es presupuesto total (créditos). Cap mensual con reset = follow-up.
- `authz` (T6): el router prefiere `app.phase1.authz` y cae a `repo.session_owner` si T6 no
  está mergeado (forward-compatible; ambos son el contrato §4.5).
