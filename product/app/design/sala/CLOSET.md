# CLOSET — Sala de uso (inventario · fuente de verdad)

> Manifiesto único de TODO lo que la Sala usa. Se actualiza con cada pieza nueva.
> Si algo no está acá, no está terminado. · Estado: **v0 (build en curso)** · 2026-06-17
> Etiquetas: **REUSABLE** (sirve a cualquier nicho/superficie) · **PARAMETRIZABLE** (mismo
> motor, valores por nicho) · **INSTANCIA** (concreto de la Sala) · **META** (doc/contrato).

## Estado de gates duros (verificados antes de construir)
- ✅ **WORKDIR** resuelve: `executor.run_puppet_e2e` crea `data/run_outputs/<run_id>` y lo pasa como `PUPPET_WORKDIR` al assembler (`_puppet_run_env`). Probado: el `.xlsx` de S1 aterrizó ahí.
- ✅ **BYOK** inyecta de verdad: `router.run_puppet` arma `credential_broker.make_user_resolver(user_id)` y pasa `byok_resolver` al run → `_resolve_keys` → child_env del belt. Probado: `byok_providers=['gmail']`, fingerprint de la cred coincide (no stub).
- 🔴 **Contrato visual `aleph-workspace.html` AUSENTE del repo** — bloquea la fidelidad pixel. La Sala se construye contra el spec TEXTUAL del directivo hasta que aparezca el mock.

---

## 1. CARPETAS (árbol front + puntos de contacto back)

```
product/app/design/
  Sala.dc.html                 INSTANCIA   Sala actual (962 ln): chat + canvas + gate cableado.
                                            REESCRITURA pendiente al contrato de 4 zonas + 5 tipos.
  sala/                         META        carpeta de la Sala (este CLOSET + assets/skills).
    CLOSET.md                   META        este manifiesto.
    render.js                   REUSABLE    ✅ pipeline de render + canvas polimórfico (slice 1).
                                            markdown(marked)+KaTeX+tablas+citas+sanitización(DOMPurify);
                                            5 renderers (informe/planilla/web/documento/imagen) +
                                            fallback markdown. Agregar tipo = agregar renderer.
    canvas-preview.html         META        ✅ banco de pruebas de los 5 tipos (verificación slice 1).
    sala.html                   INSTANCIA   ✅ shell real (slice 2): 4 zonas (Spine/Biblioteca/Chat/
                                            Canvas) · arranque limpio · loop real (tarea→run→render→
                                            bitácora) · esconde maquinaria · gate de permiso visible
                                            (cableado a /approve) · descarga · responsive/focus/reduced-motion.
                                            Lógica del loop = REUSABLE; el chrome es INSTANCIA.
  support.js                    REUSABLE    runtime de componentes .dc (parse/render/x-import).
  auth.js                       REUSABLE    wrapper de fetch → Bearer de sesión a toda /v1 (anti-IDOR).
  OutputCard.dc.html           REUSABLE    tarjeta de obra (Biblioteca) + descarga autenticada.

puntos de contacto BACK (product/backend/app/phase1/) — todos REUSABLE salvo nota:
  router.py        POST /v1/puppets/run · /recipes/validate · /runs/{id}/approve ·
                   GET/POST/DELETE /users/{u}/rag/{agent} · GET /users/{u}/{runs,outputs} ·
                   GET /outputs/{id}/download · /spaces/{id}/{events,stream}
  executor.py      run_puppet_e2e · approve_held_action · _capture_workdir_outputs
  repo.py          create_output/list_outputs/get_output_owned · held_actions CRUD · keys (BYOK)
  rag_store.py     DOC-RAG por (user,agent) + guard de aislamiento
  recipe_validator.py  valida la receta antes de correr
platform/assembler/recipe_assembler.py   assemble_and_run · _route_chat · _resolve_keys · _load_rag
platform/gates/recipe_enforcer.py        build_enforced_gate (money/send mandatorios §3.5)
platform/ingestor/runner.py              PARAMETRIZABLE ingestor determinista (hoy BCE; param. por fuente)
```

---

## 2. SKILLS (lo que la Sala carga/usa)

| Skill | Para qué | Estado | Reuso |
|---|---|---|---|
| render markdown | toda salida del agente → html (invariante "render, no raw") | ✅ `sala/render.js` | REUSABLE |
| render KaTeX | `$...$`/`$$...$$` → math | ✅ `sala/render.js` | REUSABLE |
| render tablas (tabular-nums) | tablas con números alineados | ✅ `sala/render.js` | REUSABLE |
| citas clickeables | `[n]`/links → ancla navegable + sección Fuentes | ✅ `sala/render.js` | REUSABLE |
| sanitización (DOMPurify) | render, no ejecución de HTML arbitrario (no script/iframe inyectado) | ✅ `sala/render.js` | REUSABLE |
| canvas dispatch polimórfico | switch por `artifact.type` → renderer; desconocido→markdown | ✅ `sala/render.js` | REUSABLE |
| exporter (descarga obra) | obra → archivo bajable | ✅ existe (`/outputs/{id}/download` + OutputCard.dl) | REUSABLE |
| bitácora → changelog humano | cada turno = línea en lenguaje de usuario, clickeable | ✅ `sala.html` (v0; refina con edición incremental, slice 3) | REUSABLE |
| auditoría anti-maquinaria | filtro: ningún JSON/path/tool-call/diff/terminal a la UI | ✅ `sala.html` (verificado: 0 leaks) | REUSABLE |
| gate de permiso visible | held_actions → tarjeta de OK → POST /approve | ✅ `sala.html` (backend approve ya probado) | REUSABLE |
| planilla hydration (xlsx→grilla) | fetch autenticado del .xlsx + SheetJS → rows/cols (hoja de datos) | ✅ `sala.html:hydratePlanilla` | REUSABLE |
| render-on-change engine | debounce + última-versión-válida + "armando…" + preservar scroll entre swaps | ✅ `sala.html:setBuilding/doRenderNow` | REUSABLE |
| **streaming token-por-token** | la obra se ESCRIBE letra a letra (SSE) en el canvas mientras se genera; throttle ~110ms, scroll preservado | ✅ `sala.html:streamObra/liveRender/submitStream` ← `POST /v1/puppets/run/stream` | REUSABLE |
| **ruteo charla/obra por COGNICIÓN** | la cognición declara turn 'chat'|'obra'; chat→chat (canvas intacto), obra→produce/edita; forma solo fallback | ✅ `sala.html:classifyTurn/routeTurn` ← `POST /v1/classify-turn` (`stream_chat.classify_turn`, llama-3.3-70b) | REUSABLE |
| **render limpio (mata leaks)** | saca rutas `/Users/`, `【tool†…】`, trace `›▶▶`, plan crudo del canvas; markdown+KaTeX | ✅ `render.js:stripLeaks` (informe/documento) · chat reusa `SalaRender.clean` | REUSABLE |
| **resize horizontal (gutters)** | columnas Biblioteca/Chat redimensionables al arrastrar (grip visible estilo splitter); persiste; dbl-click resetea | ✅ `sala.html` (`.gutter` + vars `--libW`/`--chatW` + localStorage) | REUSABLE |
| **mensaje de obra = voz del LLM** | línea natural generada que acompaña la obra (no frase fija); reemplaza "armé la obra"/eco del input | ✅ `sala.html:closeObra/obraCaption` ← `POST /v1/obra-caption` (`stream_chat.obra_caption`) | REUSABLE |
| **chip de obra (puntero al canvas)** | tarjeta sutil en el chat [icono·título·"ver →"] + subtítulo de acción real (de tool_calls); linkea al canvas | ✅ `sala.html:pushObraCard/realAction` | REUSABLE |
| **@ — traé tu mundo al chat** (Abuso 1) | popover con Tus cosas (obras+docs RAG) + Conectores (belt REAL con estado) → pills removibles → lo enganchado entra al run | ✅ `sala.html:atOpen/atRender/atPick/contextFromPills` ← `GET /v1/belts/cards` + `GET …/rag/{k}/{name}` | REUSABLE |
| @conector sin conectar → connect-wizard | dispara `Conectar.dc.html?c=<x>&return=…`; al volver, `resumePendingAttach` engancha solo | ✅ `sala.html:atConnect/resumePendingAttach` + `Conectar.dc.html` (botón volver) | REUSABLE |
| **chips de acción que EJECUTAN** (Abuso 2) | tras cada respuesta, chips REALES por contenido+tipo (gráfico solo si hay números; resumen si es larga) — NO lista fija; tap = submit (ejecuta) | ✅ `sala.html:suggestChips/setSugs` | REUSABLE |
| **gráfico real en la obra** | bloque ```chart {spec json} → SVG real (bar/line, ejes, leyenda); el chip "agregar gráfico" lo dispara | ✅ `render.js:buildChartSVG/renderCharts` (en informe+documento) | REUSABLE |
| **📎 adjuntar → RAG** (discreto) | archivo de texto → memoria del agente (reusa `rag_store`) → usable con @ y por el run | ✅ `sala.html:clipBtn/fileIn` → `POST …/rag/{k}` | REUSABLE |
| **🎙️ voz → texto** (discreto) | graba (MediaRecorder) → Groq Whisper → texto al input | ✅ `sala.html:micToggle/transcribeBlob` ← `POST /v1/transcribe` + `transcribe.py` | REUSABLE |
| **⚡ potencia → modelo del run** (discreto) | picker Veloz/Estándar/Tu-API → fija el `model.primary` del run (inline) | ✅ `sala.html:POWER/applyPower/powPick` | REUSABLE |
| **⚡ Tu API → BYOK-LLM** | el run corre con la KEY del usuario (su API), no la cognición incluida; `model.byok_ref` resuelto por el broker | ✅ stream: `stream_chat` (adapter OpenAI **y** Anthropic) · run: `recipe_assembler` inyecta la key BYOK; `sala.html:applyPower/BYOK_PROV` | REUSABLE |
| **falla recuperable (error + ↻ reintentar)** | la falla NUNCA deja la obra rota: restaura la última versión válida (o el arranque limpio, header incluido) + tarjeta de error humana con ↻ Reintentar (re-corre el MISMO pedido) y Editar | ✅ `sala.html:failTurn/restoreCanvas/errorCard/resetCanvasHeader` + `dispatch` (submit→dispatch para reintentar sin re-pintar la burbuja) | REUSABLE |

---

## 3. FUNCIONES DEL HARNESS ENGINEERING (las que la Sala invoca)

| Función / endpoint | Firma (resumen) | Qué hace | Reuso |
|---|---|---|---|
| **Ruteo de cognición** `recipe_assembler._route_chat` | `(messages, tools, base_url, primary, fallback, api_key, …) → (resp, model)` | OSS-first real: primary→fallback→OSS-directo; NUNCA cuelga. Modelos reales del harness (Groq gpt-oss-120b, llama-3.3-70b, …). | REUSABLE |
| `recipe_assembler._resolve_cognition_key` | `(repo_root) → str` | bearer de cognición de `infra/.env` (LITELLM_KEY→GROQ_API_KEY). | REUSABLE |
| **Inyección de conectores / BYOK** `credential_broker.make_user_resolver` | `(user_id, *, get_conn) → (byok_ref)→cleartext` | resolver ligado al user; la key cifrada del user → child_env del belt. **Aislamiento por user.** | REUSABLE |
| `recipe_assembler._resolve_keys` + `_provider_env_vars` | `(recipe.keys, byok_resolver) → {provider:val}` → env vars | cablea la cred al subprocess del MCP (la key llega al PUNTO DE USO, no solo se guarda). | REUSABLE |
| **WORKDIR** `recipe_assembler._puppet_run_env` | `(repo_root, child_env) → env` | setea `PUPPET_WORKDIR` (estable por run, vía executor) + `PUPPET_BELTS`. | REUSABLE |
| **Ingestor** `platform/ingestor/runner.run` | `(fuente/config) → datums con provenance` | ingestión determinista con procedencia (param. por nicho; hoy BCE/World Bank). | PARAMETRIZABLE |
| **Store del artefacto** `executor._capture_workdir_outputs` | `(conn, run_id, workdir) → [outputs kind=file]` | captura los archivos que el run produjo como obra. | REUSABLE |
| `repo.create_output/list_outputs/get_output_owned` | `(conn, …)` | persiste/lista/recupera la obra (Biblioteca) con authz por dueño. | REUSABLE |
| `GET /v1/outputs/{id}/download` | `→ FileResponse` | descarga autenticada + anti-traversal. | REUSABLE |
| **Gates de permiso** `recipe_enforcer.build_enforced_gate` + `gate.evaluate` | `(recipe) → gate; (server,tool,args)→decision` | money/send SIEMPRE needs_ok (§3.5); el agente propone, el humano aprueba. | REUSABLE |
| approve-by-HTTP `executor.approve_held_action` + `repo.claim_held_action` + `POST /v1/runs/{id}/approve` | `(approval_id, ok, user_id)` | el OK del dueño ejecuta la acción retenida; **exactamente-una-vez** (claim-before-execute, sin doble-gasto). | REUSABLE |
| **RAG / memoria** `rag_store.{save,list,delete}_doc` + `recipe_assembler._load_rag` | `(user,agent,…)` / `(rag_dir)→ctx` | docs por-agente → `rag.dir` → contexto al modelo. Aislado por user. | REUSABLE |
| **Run E2E** `executor.run_puppet_e2e` + `POST /v1/puppets/run` | `(recipe, prompt, user_id, …) → run record` | corre el agente equipado por el path de prod (enforcer en el camino). | REUSABLE |
| **Streaming token-por-token** `stream_chat.stream_answer` + `POST /v1/puppets/run/stream` | `(recipe, prompt) → SSE {token}*,{done}` | ✅ ADITIVO: chat directo de TEXTO en streaming (sin tools/gate → fiel). Reusa framing+RAG+key del assembler; misma carga de receta + guard DOC-RAG + validación que el run completo. Las obras con tools/acciones siguen por `/run` (con gate). | REUSABLE |
| **Proxy SSE passthrough** `product/app/serve.py` | dev-server | ✅ pasa `text/event-stream` sin bufferear (escribe cada línea + fuerza cierre de conexión) + threading; un proxy que bufferea mata el "se arma en vivo". | dev-only |
| **Belt → conectores (vista usuario)** `GET /v1/belts/cards?ref=&user_id=` | `→ {cards:[{connector,label,tools,state,badge}]}` | ✅ data-driven: lee `_meta.cards` del belt REAL + estado por-user (ready/connected/connectable contra `keys`). El @ lo consume; lo que se muestra == lo que el agente recibe. | REUSABLE |
| **Doc de memoria (contenido)** `GET /v1/users/{uid}/rag/{agent_key}/{name}` + `rag_store.read_doc` | `→ {name, content}` | ✅ texto de UN doc para enganchar @doc al contexto; authz por dueño + anti-traversal. | REUSABLE |
| **Connect-wizard** `GET /v1/connectors` · `POST /v1/connectors/{name}/connect` + `Conectar.dc.html` | `(creds, user_id) → connected[_unverified]` | ✅ EXISTENTE, reusado por @conector: guarda la BYOK cifrada; el @ sin-conectar cae acá y vuelve. | REUSABLE |
| **Transcripción** `transcribe.py` + `POST /v1/transcribe` | `(audio_b64) → {text}` | ✅ ADITIVO: Groq Whisper (whisper-large-v3) con la key de cognición; multipart por stdlib. | REUSABLE |
| **Motor de edición incremental** `sala.html:buildEditPrompt` | `(instruction) → prompt` | ✅ turno de seguimiento envía (tarea original + obra actual + historial reciente, resumido si crece) → el agente edita PRESERVANDO el resto, no regenera. Motor (run) SIN cambios. Invariante #3. | REUSABLE (lógica) |
| **Pipeline de render** `SalaRender.renderArtifact` | `(el, artifact) → render in el` | ✅ markdown+KaTeX+tablas+citas+sanitización; despacha por type (5 + fallback). Invariante #2/#5. | REUSABLE (`sala/render.js`) |
| **Type routing** `sala.html:resolveType` + `recipe.meta.output_type` | `(out) → type` | ✅ DETERMINÍSTICO: el productor declara `meta.output_type`; la Sala rutea al renderer. Sniff por extensión solo como fallback-puente; desconocido→informe. | REUSABLE (lógica) · PARAMETRIZABLE (la declaración la pone cada recipe/nicho) |

---

## Gap → roadmap de slices (build multi-tanda)
1. ✅ **Render pipeline** (markdown+KaTeX+tablas+citas+sanitización) + canvas dispatch polimórfico (5 tipos + fallback). HECHO y verificado (`sala/render.js` · `canvas-preview.html`: 12/12 checks, cero crudo).
2. ✅ **Shell 4 zonas + arranque limpio + loop real** (tarea→run→render→bitácora) + gate visible + descarga. HECHO (`sala.html`, verificado por Playwright contra backend real: arranque limpio · obra renderada · Biblioteca · bitácora · 0 maquinaria filtrada).
3. ✅ **Edición incremental** (turno = tarea original + obra actual + historial → cambio que PRESERVA el resto) + **bitácora humana** que refleja el cambio. HECHO y verificado (Playwright: turno 2 conservó el marcador único + sumó la sección nueva; bitácora "Agregué…").
4. ✅ **Type routing determinístico** (productor declara `meta.output_type` → la Sala rutea al renderer; sniff fallback; desconocido→informe). HECHO y verificado (Playwright por la Sala: puppet planilla→grilla · web→iframe · imagen→`<img>`; ninguno cayó al fallback). Upstream: Cuarto declara por nicho (finanzas→planilla, cowork→documento, research/programacion→informe).
5. ✅ **Pasada por nicho (finanzas → planilla con datos reales)** — puppet finanzas (worldbank_series→build_workbook) por la Sala: rutea a planilla, **hidrata el .xlsx producido** (fetch autenticado + SheetJS, elige la hoja de datos) → grilla con el **PIB real de Ecuador + procedencia por celda** (no el fallback, no números inventados). HECHO y verificado. Refinamiento: pestañas por hoja del xlsx.
6. ✅ **Render-on-change EN VIVO** (directivo "canvas en vivo"): motor con **debounce + última-versión-válida** (nunca un estado roto: la obra previa se mantiene mientras el agente trabaja) + **badge "armando…"** + **scroll preservado entre swaps**. HECHO y verificado (Playwright). Bonus: arreglé el scroll independiente por columna (min-height:0).
6b. ✅ **Streaming token-por-token** (la obra se ESCRIBE letra a letra DENTRO del turno): backend ADITIVO `stream_chat.stream_answer` + `POST /v1/puppets/run/stream` (SSE) — chat directo de texto, sin tools/gate (fiel), reusando framing+RAG+key del assembler. Frontend `streamObra` (fetch+ReadableStream) → `liveRender` (throttle ~110ms) → render-on-change. **Alcance honesto:** solo agente **inline** + tipos de **texto** (informe/documento); los puppets equipados y obras con archivos/tools van por `/run` (correcto > vivo — el streaming directo no llamaría tools). Verificado por la SPA (Playwright): produce en vivo (8 largos intermedios, badge visible→oculto, markdown real) + edita en vivo preservando el cuerpo (1806→2184 chars, conclusión sumada, bitácora) + sin regresión en finanzas/planilla. Fix de fondo: el proxy dev bufferaba el SSE → lo hice passthrough con cierre forzado de conexión.
7. **Fidelidad visual** (track paralelo, no bloquea): el shell está al spec textual; **falta `aleph-workspace.html`** en el repo. Se ajusta cuando aparezca el mock.
8. **Quality floor** (responsive · foco teclado · reduced-motion) — ✅ ya en `sala.html`.
9. ✅ **CHAT v2 · Abuso 1 — @ traé tu mundo al chat**: popover (Tus cosas = obras+docs RAG · Conectores = belt REAL con estado) → pills removibles → lo enganchado entra al run. Data REAL, cero hardcode. Reusa `GET /v1/belts/cards` (declaré `_meta.cards` en belt-finanzas-data + belt-calc), RAG (`read_doc`), y el connect-wizard EXISTENTE. **Probado a efecto-real (Playwright):** @doc canary A/B (sin pill no sabe el código, con pill sí) · @obra (contenido real viaja al run) · @worldbank (`worldbank_series` EJECUTADO, Ecuador 9 obs, planilla PIB real) · @alphavantage sin conectar → Conectar → al conectar la pill se auto-engancha.
10. ✅ **CHAT v2 · Abuso 2 — chips de acción que EJECUTAN**: tras cada respuesta, chips REALES por contenido+tipo (`suggestChips`: el de gráfico solo aparece si la obra tiene números; resumen si es larga; por tipo planilla/informe) — **NO una lista fija**. Tap = **submit** (ejecuta, no rellena). El chip "agregar gráfico" → el agente emite un bloque ```chart → `render.js` lo dibuja como **SVG real** (bar/line). **Probado (Playwright):** sin números no ofrece gráfico · con números sí · tap → gráfico de línea REAL en la obra (0 bloques crudos) · cero errores.
11. ✅ **CHAT v2 · Discretos (📎 · 🎙️ · ⚡)** — cada uno a efecto-real (Playwright): **📎** archivo de texto → memoria RAG del agente (canary `OBELISCO-4490` en el doc) + pill auto-enganchada · **🎙️** audio REAL (TTS) → `POST /v1/transcribe` (Groq Whisper) → transcripción exacta en el composer · **⚡** A/B del modelo del run: default `gpt-oss-120b` → Veloz `gpt-oss-20b` (cambió de verdad). Reusan `rag_store`, la cognición (Whisper) y los modelos del Cuarto.
12. ✅ **CHAT v2 · ⚡ Tu API → BYOK-LLM (run-side, ⚡ cerrado del todo)** — el run corre con la KEY del usuario (su propia API), no la cognición incluida. **Streaming** (`stream_chat`): resuelve `model.byok_ref` por el broker del user → usa SU key; adapter **OpenAI-compatible Y Anthropic** (Claude no es OpenAI-compatible: `/v1/messages` + `x-api-key`). **Run path** (`recipe_assembler`): inyecta la key BYOK (OpenAI-compatible; Anthropic-con-tools fuera, el loop usa el schema de tool-calling OpenAI). Front: `applyPower` setea `model.{primary,base_url,byok_ref}` del proveedor conectado. **Probado a efecto-real (Playwright + backend A/B):** key válida → corre (49/43 tokens) · key **bogus → 401** (prueba que el run usa TU key, no la cognición, que sí funciona) · por la SPA: ⚡ Tu API detecta el proveedor → el request lleva `byok_ref:keys:groq` + base_url del proveedor → obra producida. **Honesto:** el adapter de Anthropic está implementado pero NO verificado en vivo (no tengo key de Anthropic); el path OpenAI-compatible sí (Groq como BYOK). ⚡ aplica al agente inline; los puppets fijan su modelo en el Cuarto. **CHAT v2 COMPLETO.**

13. ✅ **Falla recuperable (done-bar "error legible + retry")** — la obra NUNCA queda en un estado roto y la falla se recupera de un toque. **Bug encontrado y arreglado:** en una tarea NUEVA que fallaba, el canvas quedaba colgado para siempre en el placeholder "Armando tu obra…" (`setBuilding(false)` ocultaba el badge pero no restauraba el canvas) y el chat moría en un texto "Probá de nuevo" sin acción. Ahora `failTurn` → `restoreCanvas` (última versión válida o arranque limpio, **header incluido** — antes quedaba "…· armando…" colgado, también en el path de pregunta-de-aclaración) + `errorCard` con **↻ Reintentar** (re-corre el MISMO pedido vía `dispatch`, sin re-pintar la burbuja del usuario) y **Editar el pedido** (devuelve el texto al composer). Cubre los 3 paths de falla del loop activo: `routeObra` (catch + respuesta vacía), `runChat` (catch) y `classifyTurn` colgado. **Verificado (Playwright, backend real :8080):** run abortado → tarjeta de error + canvas limpio (NO spinner colgado) + título reseteado → click Reintentar → la obra ("El susurro del mar") se renderiza y aterriza en la Biblioteca. Screenshots: `sala-recover-1-failed.png` / `-2-recovered.png`.

> Nota render-on-change: el loop "fuente→renderer→canvas" es idéntico para todo tipo; agregar un tipo = agregar un renderer (probado: 5 tipos + fallback, loop sin tocar). El modo "sesión operada (computer use)" NO está en el default (no implementado) — iría detrás de gate por nicho.
