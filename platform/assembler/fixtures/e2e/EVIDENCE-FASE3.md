# EVIDENCIA — Fase 3 (la de verdad): UN agente armado llega VIVO a la sala

**Fecha:** 2026-06-15 · **Scope:** SOLO función (backend + costura). Nada visual/cosmético.
**Deliverable cumplido:** un agente real, **guardado → instanciado → corrido → su OUTPUT
en la sala** (artefacto + bitácora poblada), flujo completo por HTTP — no un screenshot de
un formulario.

## El agente elegido (camino corto, 100% alcanzable)
**"Cierre mensual"** — belt `excel` (real, `uvx excel-mcp-server`), sin money/send.
Receta: `platform/assembler/fixtures/e2e/cierre.recipe.json`.
(EDGAR/10-K se descartó: `uvx sec-edgar-mcp` **no bootea** acá — `INIT FAILED`.)

## El flujo COMPLETO, por los endpoints de :8080 (real, no mock)
1. **LOGIN** `POST /v1/auth/login` → user `a10a47d2…` (200).
2. **SAVE** `POST /v1/puppets` → puppet `f85341ee…` (**201**). ← **arregla el SAVE 404**:
   el 404 era el front llamando al `/agents` viejo; el endpoint canónico `/v1/puppets`
   persiste de verdad (validador anidado + Postgres).
3. **RUN** `POST /v1/puppets/run` por `puppet_id` + `space_id` → **201, ok=True,
   gate_enforced=True, moat il.id=57**, 39.2s, 4 tools EJECUTADAS (`create_workbook`
   ×2 [1 error real + retry] · `write_data_to_excel` · `read_data_from_excel`).
4. **OUTPUT VIVO EN LA SALA** `http://localhost:8090/sala.html?space=cierre-live-001`:
   - **artefacto** = la planilla REAL `cierre_mayo.xlsx` (Ventas 50.000/54.200,
     Marketing 12.000/11.350, Operaciones 8000/8900) — reconstruida del tool-call real.
   - **bitácora** = los 4 pasos reales, **incluido el error+retry de verdad**
     ("Invalid filename: must be an absolute path…" → retry OK). Un mock no muestra eso.
   - screenshot: `product/workshop/screenshots/sala-live/sala-cierre-live.png`.

## La COSTURA construida (backend, mi carril)
- `recipe_assembler.assemble_and_run(on_event=…)`: emite un evento del espacio por cada
  tool-call **con args/result COMPLETOS** (sin trim) + un `final` con la respuesta.
- `executor.run_puppet_e2e(on_event=…)`: passthrough.
- `router /v1/puppets/run`: arma el `on_event` → persiste a `events.jsonl[space_id]` vía
  `EventLog` (persist-before-emit, id monotónico) + **política fase-verificación**: las
  tools curadas SEGURAS auto-ejecutan; **money/send SIEMPRE caen a needs_ok** (invariante
  §3.5 intacta; el approve humano por HTTP para money es el follow-up).
- `router GET /v1/spaces/{id}/events`: snapshot del espacio (lo que la sala lee).
- `sala.html`: wiring de datos `?space=<id>` → lee el run real (sin tocar el look).

## Persistencia verificada
- Postgres: `runs` 5221a599 status=done + `instrumentation_logs` id=57 (moat ligado por run_id).
- Disco: `/tmp/cierre_mayo.xlsx` (5376 bytes) — el artefacto real.
- `events.jsonl[cierre-live-001]`: 5 eventos (4 tool_call + 1 final), servidos por el snapshot.

## Deuda / follow-ups (NO ahora — listados, sin maquillar)
1. **Camino money**: cablear el approve humano por HTTP para money/send (deuda #1). Hoy
   money/send se gatean y NO se ejecutan (correcto); falta el canal de OK del usuario.
2. **Belt desde poderes sueltos** (armar de cero, `belt_ref=null`): el backend aún no
   ensambla un belt desde conectores arbitrarios — lo difícil.
3. **Crecer el catálogo de conectores** (web, mail, calendario, archivos) — Curation/Tool-belt.
4. **Política safe-auto-approve**: hoy el endpoint auto-aprueba tools curadas no-money/send
   (necesario porque el gate fail-closa todo lo no-lectura). Conviene que el belt declare
   sus tools seguras como `auto-ejecuta` (base_matrix por belt) en vez de auto-aprobar en el
   endpoint — revisar con Security antes de prod.
5. **Live streaming real-time**: hoy el snapshot puebla la sala post-run; el SSE
   (`/v1/spaces/{id}/stream`) ya existe para streaming en vivo paso-a-paso (cablear en la sala).
6. **404 favicon** en la sala (cosmético, auto-request del browser).
