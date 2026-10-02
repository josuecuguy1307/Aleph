# FASE 2 — LOOP EXTERNO §4 (torneo de estrategias + switch nivel-2 §5)

> 2026-06-23. Capa NUEVA encima del loop interno §3 (`loop/`). Módulo
> `platform/inspection/strategy/`. NO edita `contracts.py` ni `loop/*` (solo los lee
> y reusa por import). Los 3 done-bars verdes vivos. Efímero/notas; el código manda.

## Qué es
El loop interno §3 forja un MCP con UNA estrategia (el cerebro adivina endpoints, el
candado filtra). FASE 2 pone ENCIMA un **torneo A→B→C→D con salida temprana** + el
**switch de NIVEL-2** de la tabla §5. El candado §3 (`loop/validator.py·LiveValidator`)
sigue siendo **EL ÁRBITRO en cada peldaño**: FASE 2 elige QUÉ candidatos generar, NO
relaja la validación. **"Rinde" = los candidatos SOBREVIVEN al candado, jamás "devolvió
un doc"** (lo fuerza la property `StrategyResult.yielded`).

| Archivo | Rol |
|---|---|
| `types.py` | contrato CONGELADO: `Rung·Outcome·DiscoverySignal·StrategyResult·Strategy·StrategyContext·CascadeResult` |
| `openapi.py` | peldaño A: sniff (`/openapi.json·/swagger·/spec·.well-known·/graphql`) + parseo Swagger2/OpenAPI3 → `CandidateTool` GET |
| `rungs.py` | A autodescriptivo · B huella→resolver · C convención · D activo→`run_internal_loop` |
| `cascade.py` | orquestador: cascada, salida temprana A/B, switch nivel-2, forja ÚNICA desde la unión |
| `selftest_cascade.py` | GATE vivo — los 3 done-bars + smoke estructural |

## El contrato congelado — `StrategyResult` (para FASE 3)
```
StrategyResult(rung, outcome, candidates, verified, dropped, signals,
               aggregate_failure, family, used_brain, budget, notes)
  .yielded     → outcome∈{YIELDED,PARTIAL} y verified≠∅  (RINDE = sobrevivió el candado)
  .won         → yielded  ó  (familia resuelta+validada viva, peldaño B)
  .stale_count → cuántas cayeron 404 (NOT_FOUND) — la firma del doc stale
Outcome = YIELDED | PARTIAL | REJECTED | EMPTY | SWITCH | SKIPPED
```
`StrategyContext` comparte UN substrate para toda la cascada: **un** `ledger` (cap §6
único, no N por peldaño), **un** `validator` (candado §3, mismo árbitro), guard SSRF
(`guarded_get` corre el guard ANTES de CADA fetch de descubrimiento). `CascadeResult`
trae `winner·early_exit_at·forged·verified(unión)·rungs(rastro)·switches·budget`.

## La cascada (cascade.run_cascade)
- **A rinde COMPLETO** (verificadas, <25% en 404) → **SALIDA TEMPRANA en A**, NO corre B/C/D.
- **A rinde PARCIAL** (≥25% de los endpoints del doc 404ean vivo = doc **STALE**) →
  forja lo vivo + **switch nivel-2** + baja al par C/D por los faltantes.
- **A vacío / todo-404 con señal de doc** (`ALL_404_OPENAPI`) → estrategia equivocada → B.
- **B huella**: deriva el servicio del host → `mcp_resolver.resolve_service`. Si resuelve
  una familia CONFIABLE (y, hosted+cred, la valida viva) → **handoff al resolver**, salida
  temprana. Reusa el resolver de main, no lo reescribe.
- **Par C/D** (fallback, corren juntos y se UNEN): C = convención barata (`/api/v1`, raíz,
  `validate_path`) SIN cerebro; D = `run_internal_loop(forge=False)` CON cerebro + minería
  de frontera. **Economía §6**: si C ya forjó ≥5 tools sin stale, NO se quema el cerebro de D.
- **Forja ÚNICA** al final desde la **unión deduplicada** (dedup por `tool_signature`):
  doc stale + rescate C/D = UN MCP coherente, no tres parciales.

### Switch nivel-2 (la distinción §5 · `rungs._classify_batch`)
La clase §5 **agregada del lote** la calcula el orquestador (no el validador per-tool):
un **404 suelto** = drop interno (`NOT_FOUND`, refine tool); **≥25% en 404** = doc STALE
(`PARTIAL` → baja); **TODO 404 con señal de doc** = `ALL_404_OPENAPI` (`SWITCH_STRATEGY`,
move `switch_to_self_describing`). El validador PUEDE mandar de vuelta abajo en la cascada.

## DONE-BARS (verify-from-environment · vivos · 2026-06-23)
Targets PÚBLICOS (el guard SSRF niega loopback/privadas → no hay self-test contra localhost).

1. **openapi → sale en A** · `httpbin.org` (sirve `/spec.json`, GETs keyless). **✅ VERDE**:
   A → `yielded`, **12 tools forjadas**, `early_exit=A`, NO corrió C/D, **sin cerebro**, 17.6s.
   (El candado hasta atrapó 1 entrada del doc genuinamente stale → drop, no se forjó.)
2. **sin doc ni huella → C/D forja igual** · `PokéAPI` (sin auto-descripción, sin familia
   confiable). **✅ VERDE**: A sin doc forjable; **B RECHAZÓ** el MCP comunitario
   `io.github.cyanheads/pokeapi-mcp-server` (0.55<0.80, sin namespace verificado →
   anti-impostor); C(3)+**D cerebro(24)** = **27 tools**, `winner=D`, brain=True, 166s.
3. **OpenAPI STALE (mitad 404) → switch → C/D recupera** · `httpbin` doc INCOMPLETO
   (cap a 4 reales) + 2 paths bogus que 404ean vivo. **✅ VERDE**: A → `partial`
   (1 vivo, `stale_count=2`) → **switch nivel-2 registrado** → D cerebro recuperó los
   endpoints no-documentados → unión **A(1)+C(1)+D(13)=15 tools**; los bogus NO entraron
   al MCP. 148s.

**¿Hubo throttle? NO** — #2/#3 corrieron `max_rounds=3` completos, `degraded=False`,
~46k synth-tokens c/u (overhead del shim), sin rate-limit. El cerebro = wrapper Claude
Code (shim `:8923`, `PUPPET_BRAIN_SHIM=1`), mismo cupo Max. A/B/C **sin cerebro** (baratos).

## Cómo correr
```bash
# A (sin cerebro):
product/backend/.venv/bin/python platform/inspection/strategy/selftest_cascade.py openapi
# C/D (cerebro · shim :8923):
PUPPET_BRAIN_SHIM=1 product/backend/.venv/bin/python \
  platform/inspection/strategy/selftest_cascade.py nodoc        # PokéAPI
PUPPET_BRAIN_SHIM=1 product/backend/.venv/bin/python \
  platform/inspection/strategy/selftest_cascade.py stale        # httpbin doc stale
# smoke estructural (sin red):
product/backend/.venv/bin/python platform/inspection/strategy/selftest_cascade.py smoke
```

## Gotchas (no obvios)
- **`types.py` sombrea la stdlib `types`** cuando se corre un script DESDE `strategy/`
  (Python pone `strategy/` en `sys.path[0]`). El nombre lo fija la directiva → el
  selftest **borra su propio dir de `sys.path` antes de importar la stdlib** (shadow-fix
  arriba del archivo). En producción el backend corre desde la raíz de platform →
  `strategy/` nunca es `sys.path[0]` y el problema no existe. Importá siempre como
  `from inspection.strategy.types import …` (nunca `from strategy...`).
- **El guard SSRF NO está en `LiveHTTP`** (corre solo en `session.acquire` sobre el
  base_url). Los sniffs de A tocan OTRAS rutas (raíz del host, `/openapi.json`) → el
  guard se corre explícito en `ctx.guarded_get` / `ctx.guard.check` ANTES de cada fetch.
- **GraphQL**: se DETECTA (señal) pero NO se forja — el candado vivo §3 es GET-only; una
  query/mutation GraphQL es POST a un único endpoint con body, fuera de su alcance. Honesto.
- **Path params sin ejemplo**: NO se rellenan con un id inventado → el candado los dropea
  `BAD_SHAPE` (400-like), no 404. Inventar un id daría 404 y FINGIRÍA staleness donde no la
  hay (rompería el switch nivel-2). Solo se llena con example/default/enum REAL del doc.
- **Budget §6 único**: D recibe un `Budget` REMANENTE (`max_live_calls/seconds/tokens` menos
  lo gastado en A/B/C); al cerrar, lo que D gastó se pliega al ledger compartido. Un techo,
  no cuatro.

## Pendiente / handoff
- Peldaño B (huella) se ejercitó vía `resolve_service` (resolución + rechazo anti-impostor
  vivos en #2). El equip-vivo de una familia HOSTED queda como el GREEN propio del resolver
  (ver memoria `resolver-coverage-probes`); B no arranca subprocesos npx/docker en el torneo.
- El **moat por-huella §8** (capturar la estrategia ganadora indexada por huella para no
  re-cruzar la misma API) NO es de este task. `StrategyResult.family`/`signals` ya llevan lo
  necesario para alimentarlo en FASE 3.
- `StrategyResult` **CONGELADO** — FASE 3 puede depender de su forma.
