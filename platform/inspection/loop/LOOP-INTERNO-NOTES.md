# LOOP INTERNO §3 — el motor que forja un MCP desde URL+key crudas (TMDB vivo)

> 2026-06-22. Implementa `platform/inspection/contracts.py` (§0 verify-from-environment,
> §3 loop interno, §5 tabla de fallas, §6 convergencia+budget). **GATE VERDE 5/5 contra
> TMDB v3 vivo.** Efímero/notas; el código es el producto.

## Qué es
De **lo único crudo** — `base_url + api_key` (Forma 1, token en query, read-only) — el motor
descubre, verifica contra el software vivo y FORJA un MCP real **desde cero** (gap #1: nada
de config muerto ni catálogo pre-armado). Las 5 capas del contrato, encarnadas:

| Capa | Archivo | Rol |
|---|---|---|
| 0 SSRF | `guard.py` | resuelve DNS, bloquea loopback/privadas/link-local/metadata · fail-closed |
| 1 Sesión | `session.py` | Forma 1 token-en-query · **valida la key viva** (`/configuration`) + la cifra (Fernet) |
| 2 Observador | `observer.py` | 1ra vuelta **pasiva** (raíz+`/configuration`), luego **activa** (pega un endpoint de la frontera, mira la cruda) |
| 3 Sintetizador | `synth.py` | **Opus 4.8 real** vía shim (`PUPPET_BRAIN_SHIM=1`, :8923) · recibe CONFIRMED+obs+FAILED · `degraded:true` honesto si cae |
| 4 Validador | `validator.py` | **EL CANDADO** · llama CADA candidata viva · 2xx+forma→VERIFIED+mina FRONTIER · falla→§5 `from_symptom`→FAILED+move |
| 5 Emisor | `emit.py` + `forged_mcp_server.py` | VERIFIED→MCP equipable (`.mcp.json` + spec) · key por **vault** (placeholder en el manifest) |
| §6 motor | `engine.py` | convergencia + budget + **log del working set por vuelta** |
| — | `run_tmdb.py` · `selftest_loop_internal.py` | runner vivo + GATE VERDE |

## Cómo correr (vivo)
```bash
set -a; . infra/.env; set +a                 # GROQ_API_KEY (para el synth OSS del gate)
export TMDB_API_KEY=<api_key_v3>             # la key v3 (query param), de persona usuaria en sesión
export PUPPET_BRAIN_SHIM=1                    # apunta el alias 'brain' al shim :8923 (Opus real)
# demo end-to-end (working set vuelta a vuelta + MCP forjado):
product/backend/.venv/bin/python platform/inspection/loop/run_tmdb.py
# GATE VERDE (verify-from-environment):
product/backend/.venv/bin/python platform/inspection/loop/selftest_loop_internal.py
# smoke estructural (sin red, sin key): los imports + guard + §5 + parseo + server forjado
```

## GATE VERDE 5/5 (vivo, TMDB)
1. **converge a N tools VERIFICADAS** — 39 tools de lectura (GET), de URL+key crudas.
2. **cada una REALMENTE llamada** — `verified_by=200-OK+schema-match` + `sample_response` vivo.
3. **el candado §5 dropea alucinaciones en vivo** — lock self-test determinístico: el Validador
   real contra 3 endpoints inexistentes (`/movie/{id}/box_office`, `/awards`, `/person/{id}/awards`)
   → **404 vivo → NOT_FOUND → dropeadas, 0 a VERIFIED**. (No finge un PASS: prueba un RECHAZO real.)
4. **MCP forjado DESDE CERO** — `belt-tmdb-live.mcp.json` + `tmdb-live.forge.json`, 37–39 tools,
   key cifrada en `credentials.enc` (Fernet), **nunca en claro** en el manifest (cred_ref placeholder).
   Probado: el server forjado ejecuta vivo (`get_movie_details(550)` → Fight Club, 1999, 200).
5. **budget cap respetado** (rounds/calls/tokens/tiempo) **+ `degraded:true` honesto** con el cerebro caído.

## Hallazgos / gotchas (no obvios)
- **Cloudflare banea el UA `Python-urllib`** (Groq/OpenRouter detrás de CF → 403). El synth manda
  UA de navegador. El shim de Opus es localhost → no lo necesita. (Mismo gotcha que el nota Smithery.)
- **Opus alucina TMDB ≈ 0%** — conoce la API al dedillo, así que en la trayectoria con Opus el
  candado no tuvo nada que tirar (MCP 100% real, cero desperdicio). Cuando Opus SÍ cae es por
  endpoints **auth-scoped** (p.ej. `/movie/{id}/account_states` → 401/403 FORBIDDEN, exige sesión).
  Por eso la condición #3 es un **lock self-test determinístico** (no depende de que un cerebro
  alucine), con el drop orgánico como contexto. El candado vale MÁS sobre APIs que el modelo NO
  conoce — ahí la tasa de alucinación es alta y el candado es esencial.
- **Forja desde el entorno vivo:** lo único hardcodeado es `base_url+api_key`. Las tools salen de
  lo que Opus propone + lo que el candado verifica contra TMDB; la frontera la minan los reads
  (paginación + sub-recursos por id, genérico, no TMDB-específico).
- `oss-weak` (llama-3.1-8b) se agregó a `assembler/models.py` como synth débil para ejercitar el
  candado; resultó poco fiable (JSON inválido a veces) → el gate usa el self-test determinístico.

## Generalización a Alpha Vantage (2026-06-23) — MISMO engine, solo PERILLAS
El loop corrió contra **Alpha Vantage** sin tocar el motor: `run_alphavantage.py` +
`selftest_loop_alphavantage.py` pasan perillas a `run_internal_loop` (`AV_KNOBS`). AV es
estructuralmente MUY distinta a TMDB y forzó 4 generalizaciones GENÉRICAS (todas no-op para TMDB):

- **Despacho-por-query** (todo va a `/query`, la op la nombra `function`): `dispatch_param="function"`
  → `tool_signature(cand, dispatch_param)` = `endpoint#function=X` (sin esto, todas las tools
  colisionarían en el dedup por compartir endpoint `/query`). TMDB: `dispatch_param=None` → firma=endpoint.
- **Error EN BANDA** (AV devuelve HTTP 200 + `{"Error Message"|"Information"|"Note": …}` para errores):
  `classify_soft_envelope` (compartido validador↔sesión) **por CONTENIDO** — "does not exist"/"invalid"
  → `error`→404 (la alucinación cae acá); "rate limit"/"per day"/"premium"/"subscribe" → `notice`→
  transitorio (NO alucinación, la función puede existir). Sin esto un 200+error se verificaría como tool.
- **Throttle 1 req/seg**: `min_interval=1.3` (LiveHTTP pacing) o TODO vuelve rate-limited y nada verifica.
  La sesión también es content-aware: un throttle en la validación = key VÁLIDA (acepta), no auth-fail.
- **Retry del cerebro**: el synth reintenta 3× con backoff antes de declarar `degraded` (un blip
  transitorio del shim no debe matar el run; una caída sostenida agota los reintentos y degrada igual).

**Resultado vivo (run real):** 12 funciones REALES verificadas + MCP forjado (GLOBAL_QUOTE,
TIME_SERIES_*, OVERVIEW, INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW, EARNINGS, CURRENCY_EXCHANGE_RATE,
SYMBOL_SEARCH, NEWS_SENTIMENT, INSIDER_TRANSACTIONS). Forja+vault+dispatch+clasificador OK.

**Hallazgo honesto (refuta la hipótesis):** se esperaba que Opus alucinara AV (la conoce "menos");
**alucinó CERO** — propuso 16 functions, las 16 reales. El set de functions de AV es chico y
bien-documentado → Opus lo sabe igual que TMDB. Los 4 "drops" del run NO fueron alucinaciones: eran
funciones REALES (`TIME_SERIES_INTRADAY/MONTHLY`, `DIVIDENDS`, `ETF_PROFILE`) enmascaradas por la
**quota diaria de AV (25/día)** que se agotó a mitad del run. NO se maquillan como alucinaciones.

**Caveats AV (gotchas duros):**
- **Quota 25 req/día** (free tier): se agota rapidísimo (1 run ≈ 15-20 calls). Una vez agotada,
  TODA respuesta (incl. functions reales y bogus) es `{"Information": "...25 requests per day..."}`
  → `notice`/transitorio → enmascara todo. El gate corre el **lock self-test PRIMERO** (quota fresca)
  para que las bogus reciban "does not exist"→NOT_FOUND antes de gastar la quota. Re-correr tras el reset.
- El **lock determinístico** quedó DIFERIDO el 2026-06-23 (quota agotada por los runs); su mecanismo
  está probado offline (classify) + por la sonda viva inicial (FOOBAR_NOTREAL → "does not exist").
- **budget per-call**: el cap §6 ahora se enforça por-call en el validador (`ledger.can_make_call()`),
  no solo por-vuelta (antes un batch de validación sobrepasaba el cap: 18 vs 11).

## Pendiente
- Loop EXTERNO (§4 Strategy, torneo de estrategias) y el moat por-huella (§8) NO son de este task
  (que es el loop INTERNO §3). Quedan como continuación.
- AV gate 100% verde vivo: re-correr `selftest_loop_alphavantage.py` con quota fresca (reset diario)
  o una 2da key — el lock-first cerrará la condición #3 limpio. Los fixes ya están en el código.
- Rama actual `probe-caso-d-stripe`; nada commiteado aún (synth_belts está gitignored).
