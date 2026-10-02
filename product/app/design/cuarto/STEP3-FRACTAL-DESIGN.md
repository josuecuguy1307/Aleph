# STEP 3 · EL FRACTAL — Diseño cerrado + build spec

> Contrato técnico de diseño y build, independiente del árbol local.
> Este doc sobrevive cualquier `reinicio de contexto`. Es el contrato de build; el gate §7 del spec juzga.
> Diseño reconciliado con la implementación; los gates verifican el contrato.

---

## 0. REENCUADRE (lo que el ground truth cambió del spec)

El spec dice "STEP 3 ← ACÁ" como si empezara de cero. **NO.** `main` ya tiene **D1 construido,
mergeado y verificado**:

- Recinto = matrioshka real: `drawRecintos(t)` (`cuarto.render.js:1837`) pinta muro (footPoly),
  color por tipo, halo elíptico iso que **late** a `sin(t*3+phase)`, mini-Aleph (`makeNucleo({mini})`)
  que respira, chip `"<label> · agente"`, y stack de hasta 4 cards colapsado (`drawRecintoStack:1875`).
- **Decisión §3.1 (muro-vivo vs inerte) YA RESUELTA y medible**: agente → violeta `0xb389ff` + halo
  que late + mini-Aleph + chip; cajón → slate `0x8893a7`, sin halo/core/chip. Predicado único
  `isAgentPiece(b)=b.atom==='agente'||b.nucleo` (`render:403`) **idéntico** a `_isAgentPiece`
  (`projection.js:32`). Todo el frame se snapshotea en `n._draw` y se lee por `api.recintoDraw()`
  (`render:2056`) → contrato verificable, no pixeles.
- 3 harnesses verdes: `verify_recinto_{modelo,render,interaccion}.mjs` (modelo/occupancy, muro+halo,
  colapsar/drag/adopt/auto-expand). Corridos en vivo desde el worktree = VERDE.
- Costura de proyección `agent_refs[]` (`2228488`), B1/B2/C1 mergeados.

**Por lo tanto el delta real de Step 3 = D2 + D3 + D4 + D5** (D1 ✅). Y hay **dos huecos
load-bearing** que el spec asumió resueltos y NO lo están (ver §2, §3).

---

## 1. PERTENENCIA — la verdad del runtime que el muro DEBE mostrar (cierra §2 crítico)

**El hijo delegado NO es su propia composición.** Corre IN-PROCESS como sub-run del
`assemble_and_run` del padre (`recipe_assembler.py:1812-1814`; `delegation._run_one_child:486-515`).
El muro-frontera (D4) debe dibujar TRES capas, sin mentir:

| Capa | Qué | De qué lado del muro | Evidencia |
|---|---|---|---|
| **AISLADO** (el muro lo promete) | gate propio de la receta hija, `approve=None` (NO hereda el OK del padre, RIEL#1); workdir propio `sub-<turn>-<idx>-<slug>` (RIEL#4); BYOK scopeado a lo que la hija declara (D7); modelo propio o heredado (D6) | **DENTRO** del hijo | `recipe_assembler.py:1289`, `delegation.py:483,491,476,481` |
| **COMPARTIDO** (dibujar CRUZANDO el muro) | deadline absoluto del padre (RIEL#3); techo de tier `_caps_ceiling`; **bus de memoria B2** (mismo archivo/path, si el hijo es miembro — la línea teal decide); germen efímero del server de memoria | **atraviesa** el muro | `delegation.py:498,501,507-514`; `recipe_assembler.py:1456-1458,1828-1830` |
| **NO EXISTE para el hijo** (el muro NO debe pintarlo como suyo) | memoria privada A3, corpus RAG C1 propios — gated a `_depth==0`, ni se pasan en delegación; sólo el executor los resuelve para el top-level | — | `recipe_assembler.py:1432,1475`; `executor.py:584-650` |

**Qué CRUZA de vuelta al cerebro del padre:** SÓLO el resultado estructurado
`bridge_child_result` → `{sub_agente, ok, resultado, truncado, error}` (string, `delegation.py:186-197`).
**Qué NO cruza:** tool_calls/mensajes/workdir/gate_decisions del hijo → quedan como LOG en
`record['sub_runs']` (`child_log_view`, `delegation.py:200-217`), JAMÁS entran al contexto del padre.
**Burbujean al HUMANO/DB (no al cerebro):** held_actions gated del hijo (aprobar por HTTP,
`recipe_assembler.py:2112-2147`) + aporte destilado al bus compartido (`shared_distilled:1842`).

**REGLA DE ORO DEL MURO (anti-grift):** el hijo corre con `on_event=None` (`delegation.py:492`).
Sus pasos internos NO se streamean. D4 SÓLO puede encender el recinto con los **eventos
estructurales que emite el PADRE** + el resultado bridged. **Prometer un feed vivo tool-por-tool
del interior del hijo sería MENTIR.**

---

## 2. LOS DOS HUECOS QUE EL SPEC ASUMIÓ CERRADOS (y no lo están)

### HUECO A — Tres identidades sin unificar (bloquea D3 real)
- **puppet UUID** = "My agent" guardado en DB (`puppets.id`, server-minted). ES el `composition_id`
  de B2/C1.
- **slug** = `basename(agent_ref)` sin `.config.json` (`belt_resolver._slug_from_agent_ref`). Lo que
  usa `memory.members` y `shared_memories.author_agent_id`.
- **path canónico** = `Path(recipe_path).resolve()`. Lo que compara la detección de ciclos runtime.

`agent_ref` HOY **sólo resuelve a un archivo en disco** (`catalog/agents/<slug>.config.json`;
existen 2 fixtures: `research-sub`, `qa-sum-sub`). **No existe puente UUID→agent_ref.** Colocar un
"My agent" guardado como pieza sin tender ese puente → `agent_ref` que no resuelve → el run lo
**omite en silencio** (`delegation.py`: "un agent_ref que no resuelve NO tumba el run: se omite") →
la pieza-agente desaparece del comportamiento. **Asesino silencioso.**

**El gate §7 EXIGE cerrar esto**: "Guardo un agente B → en el Cuarto de A lo coloco como pieza →
entro a B → edito adentro → salgo → B guardó su cambio". Sin puente de identidad, B no se puede
referenciar por su identidad real ni "guardar su cambio".

### HUECO B — Cero navegación de escena (D2 se construye de cero)
Hay cámara plana 2.5D (`cam={x,y,scale,rot}`, `zoomAt`, `fitAll`, `rotateBy`, `applyCam`
instantáneo — `api.cam:2144`). **NO hay**: stack de escenas, push-in animado, breadcrumb, "entrar".
Grep de `sceneStack|pushScene|enterRecinto|breadcrumb|semantic-zoom` = 0 hits.
`loadPuppet` (`pixi.html:2478`) es **destructivo** — borra toda la escena
(`placedTiles().forEach(removeTile):2498`). Reusarlo para "entrar" **destruiría al padre**.

---

## 3. LAS 3 DECISIONES DE DISEÑO (§3 del spec) — CERRADAS

### §3.1 Muro-con-vida vs muro-inerte → **YA RESUELTO** (ver §0). Cero trabajo nuevo.

### §3.3 El glifo de pieza-mundo → **DECISIÓN**
Hoy el recinto-agente comunica "contiene algo" con muro+halo+mini-Aleph+chip, pero **no anuncia
"abrible / entrá a mi mundo"** (cursor = `grab`, no hay chevron/ícono). **Decisión:**
- Añadir un **glifo `layers`/portal** en la esquina del muro del recinto-agente (NO del cajón —
  un cajón no es un mundo). Micro-ícono iso (3 láminas apiladas) con el mismo material del diorama
  (violeta `0xb389ff`, mismo stroke que el muro). Aparece SÓLO en recinto-agente (`hasNucleo`).
- **Affordance de entrada** = doble-click sobre el recinto O botón "Entrar" del panel D5 (NO el
  single-click, que ya está tomado por `toggleCollapse`/inspector en `tileDragUp:825-836`).
- El glifo **pulsa suave** cuando el recinto está corriendo (D4) — reusa el canal de halo.
- Se dibuja en `drawRecintos` condicionado a `agent && !collapsed?` (decidir en build: visible
  colapsado también, como promesa de "hay mundo adentro").

### §3.2 El zoom semántico → **DECISIÓN (mecánica exacta de D2)**
Navegación de ESCENA, no modal. Se construye un **stack de escenas** liviano sobre la cámara existente:
1. **Trigger** (dbl-click recinto-agente / botón Entrar del panel): tomar `node.data.agent_ref`.
2. **Snapshot del padre**: `sceneStack.push({ placedById, occupancy, model, cam:{...}, scene, agentRef, label })`
   (copia inmutable — el record del padre NO se muta, coherente con "padre INTACTO").
3. **Push-in de cámara**: tween sobre `cam.{x,y,scale}` hacia `recintoCenter(n)` (`render:340`) +
   bounding `footScreen(recintoFootRect(n))`, ~380ms ease-out, en el ticker (`:1901`).
   **GUARDAR/deshabilitar `fitAll` mientras dura** (flag `__inChild`) o `grow/rotate/resize` snapean
   la cámara de vuelta (gotcha R2).
4. **Cargar la receta del HIJO en el MISMO motor**: `fetch` de la config del hijo por `agent_ref`
   (partir `loadPuppet:2483-2488` en su fetch reusable) → `recipeToTiles(childRecipe, ATOMS.list)`
   → montar en un **child-world container** hijo de `cameraRoot` (`:132`), NO borrar el padre.
   El world del padre queda vivo, oculto (`setHidden`) detrás.
   **Trampa (gotcha R2):** `recipeToTiles` rehidrata al agente como recinto VACÍO (`tools:[]`);
   los hijos reales del sub-agente viven en SU config, no proyectados en el padre → hay que
   fetchear la config del hijo, no basta expandir. **Y pasar SIEMPRE `ATOMS.list`** o el `belt_ref`
   de las tools se pierde (round-trip lossy sin catálogo).
5. **Breadcrumb**: barra `Cuarto raíz › agente A › agente B` siempre visible, clickeable (salta
   N niveles = pop hasta ese índice). Deriva del `sceneStack` (profundidad = `stack.length`).
6. **Salir** (pull-back / breadcrumb / Esc): pop del stack → restaurar `placedById/occupancy/model/cam`
   del padre byte-idéntico → descartar el child-world → re-habilitar `fitAll`. **Invariante gate §7.2:
   modelo del padre == snapshot (byte-idéntico).**
7. **Tope de profundidad**: `MAX_DEPTH_UI = 5` (runtime es `MAX_DEPTH=3`; el UI puede navegar recetas
   guardadas más profundo que lo que un run permite, pero honesto: al topar, mensaje
   "este mundo va más hondo de lo que un run puede ejecutar (máx 3 niveles de delegación)" — NO crash).

---

## 4. EL DELTA A CONSTRUIR — orden por dependencia

> Regla de oro transversal: **cero grafo paralelo.** Todo sale de la receta real. `isAgentPiece`
> (render) ≡ `_isAgentPiece` (projection) — NUNCA divergir (un agent_ref en belt_refs = muerte
> silenciosa). Disciplina de REGRESIÓN en cada harness: "escena sin recintos = modelo byte-idéntico".

### D2 · Zoom semántico + breadcrumb  ← PRIMERO (no depende de identidad)
Construir el stack de escenas + push-in + child-world + breadcrumb + salir-intacto + tope (§3.2).
- **Seams**: `cam` tween en ticker (`render:1901`) + `api.cam.pushInto(recintoId)` nuevo usando
  `recintoCenter:340`/`footScreen:337`; child-world container bajo `cameraRoot:132`; partir
  `loadPuppet:2478` (reusar su fetch+rehidratación, NO su `removeTile`-de-todo); breadcrumb DOM en
  `pixi.html`; flag `__inChild` que congela `fitAll`.
- **Glifo portal** (§3.3) en `drawRecintos` + trigger dbl-click en `tileDragUp:825-836`.
- **Harness** `verify_fractal_zoom.mjs` (puerto 8103): entrar 1 nivel → child-world montado +
  padre oculto + cam movida; salir → `relationModel()` padre == snapshot byte-idéntico; entrar/salir
  N niveles (breadcrumb correcto en 3, salto de nivel); tope honesto (no crash).

### D3 · Agente-como-pieza (colocar/exportar) + ciclos  ← el PUENTE de identidad (§2·A) — CERRADO por recon backend

> **Directiva de una línea (recon D3, con evidencia file:line):** exporter idempotente keyed por UUID
> (side-effect de `create_puppet`/`update_config` en `router.py:~518`/`~546`) que escribe
> `{**config, "schema_version":"v1"}` **menos `canvas`** a `catalog/agents/agent-<puppet_id>.config.json`;
> el saved-agent colocado lleva `agent_ref="catalog/agents/agent-<uuid>.config.json"` en **AMBOS**
> `belt.agent_refs[]` y el bloque `canvas` `atom==='agente'`; el `enter()` de D2 resuelve la receta del
> hijo por UUID vía `GET /v1/users/{id}/puppets` (map client-side), y el runtime resuelve el MISMO
> archivo por el candidato #3 existente. **CERO cambios a `belt_resolver.py`, `delegation.py` ni el validador.**

**Ground truth confirmado (gap real):** `resolve_agent_ref` es FILESYSTEM-ONLY, nunca toca la DB —
prueba candidatos: ref-como-path si `.json` (`belt_resolver.py:310-311`), `catalog/agents/<slug>.json`
(`:312`), `catalog/agents/<slug>.config.json` (`:313`), ref-como-path si no-`.json` (`:314-315`); cada
uno exige `exists()+is_file()` (`:319`). NO hay writer a `catalog/agents/` en ningún lado (grep vacío).
NO hay `GET /v1/puppets/{id}`; sí `GET /v1/users/{user_id}/puppets` (list con config completa,
`router.py:485`, owner-gated). Precedente sancionado del patrón "mirror del resolver":
`emit.py:324-349` ya espeja el orden de candidatos.

1. **Bridge = EXPORT (opción a), NO branch-DB (b).** Razón: `belt_resolver.py` es stdlib puro, sin red
   ni side-effects (docstring `:23`); `resolve_agent_refs(refs, repo_root)` sólo recibe un path
   (`delegation.py:121`), no tiene cómo recibir una conexión DB. Export = 0 cambios al resolver/
   delegation/validador; el candidato #3 (`:313`) ya resuelve el archivo exportado byte-idéntico a los
   2 fixtures. **Seam:** helper NUEVO `app/phase1/agent_catalog.py` (NO inline en router, NO en repo.py
   — la capa DB queda pura); llamado tras `repo.create_puppet` (`router.py:515-522`, ya con UUID minted)
   y en `update_puppet_config` (`:546`). Escritura atómica (tmp + `os.replace`).
2. **Slug del UUID, NO del nombre.** filename `catalog/agents/agent-<uuid>.config.json` →
   `_slug_from_agent_ref` (`belt_resolver.py:252-258`) → `agent-<uuid>` (round-trip por candidato #3).
   El UUID es único/inmutable/filename-safe. **Nombre-derivado = asesino silencioso** (dos "My agent" →
   mismo archivo → el 2º pisa al 1º → el padre corre la receta EQUIVOCADA sin error). Este slug es el
   mismo que usa `delegation.resolve_child_model_cfg` (`:280`) y `_sub_workdir` (`:411`) → estable.
3. **Transform de export (NO copia cruda):** `{**config, "schema_version":"v1"}` menos `canvas`.
   (a) **Forzar `schema_version:"v1"`** — la columna default es `v0` (`schema.sql:39`) pero el resolver
   hard-checkea `recipe.schema_version=="v1"` (`belt_resolver.py:276`); v0/faltante → hijo silenciosamente
   NO-resoluble. (b) **Drop `canvas`** — presentation-only, el motor la ignora (`recipe_validator.py:48-50`);
   es exactamente lo que el cycle-walk lee del editor vivo, no del archivo hijo → child recipes lean.
   (c) `keys` queda byok_ref-only (ya lo es; re-scoped en runtime `delegation.py:222-248`). Resto
   (`meta/model/belt/framing/rag/gates/autonomy/memory`) copia verbatim. Ya pasó `validate_recipe` al
   guardar (`router.py:509`).
4. **UI colocar**: la fila de "Mis agentes" (`pixi.html:2446-2472`, hoy sólo navega ?puppet=id) gana
   un botón "colocar como pieza" → `cuarto.placeTile({atom:'agente', nucleo:true,
   agent_ref:'catalog/agents/agent-<uuid>.config.json', label:name, child_model, ...}, gx, gy)`.
   `placeTile` ya acepta piezas-agente. El ref va a AMBOS destinos (belt.agent_refs[] al proyectar +
   el bloque canvas atom='agente', como `emit.py:292`).
5. **`enter()` de D2 retrieval (real path):** parsear UUID del ref (`slug.removeprefix("agent-")`) y
   buscar la config en el map de `GET /v1/users/{id}/puppets` (`router.py:485`, config completa de todos
   los agentes del owner) — **CERO backend nuevo**. (Opcional follow-up: `GET /v1/puppets/{id}` reusando
   `repo.get_puppet:303`.) El runtime (enter→run) resuelve el mismo archivo de disco por candidato #3.
6. **Guardia de ciclo en AUTORÍA (mirror EXACTO del runtime):** identidad runtime =
   `canonical_fingerprint = str(Path(recipe_path).resolve())` (`delegation.py:173-181`), membership en
   `agent_stack` chequeada en `:458`, `MAX_DEPTH=3` (`:57`). **Como el export hace slug↔UUID↔path una
   BIYECCIÓN, comparar UUIDs client-side == comparar canonical paths server-side** (esta igualdad es lo
   que cierra HUECO A — y sólo vale con el slug-UUID de #2). Walk (pre-save):
   `seen={parentUuid}; queue=childUuidsOf(draft)` donde `childUuidsOf(config)` = union de
   `belt.agent_refs[]` + `canvas.blocks(atom==='agente').agent_ref`, cada uno `refToUuid` (mirror de
   `_slug_from_agent_ref`); si `uuid in seen` → CYCLE (A→A o A→B→A). El `GET /v1/users/{id}/puppets`
   materializa todo el grafo del owner en memoria → `fetchConfig(uuid)` es lookup, sin round-trips.
7. **Exportar el Cuarto como pieza**: es el mismo exporter de #1 disparado al Guardar — el Cuarto
   guardado ya queda como `catalog/agents/agent-<uuid>.config.json` referenciable por otros padres.
8. **Cajón nunca genera agent_ref** — assert DIRECTO en harness (hoy sólo indirecto): cajón
   placeRecinto-con-hijos pasado por `canvasToRecipe` → `agent_refs==[]` + hijos en `belt_refs`.

**Asesinos silenciosos (E del recon) a cubrir:** (1) export no-escrito/stale → re-exportar en
create Y update, idempotente por UUID; (2) `schema_version!="v1"` → normalizar; (3) slug de nombre →
usar UUID; (4) path absoluto en agent_ref → 422 LOUD al guardar (mantener repo-relativo); (5) ciclo
runtime devuelve record `{ok:false}` que el padre consume como tool-result normal (sin fallo duro) →
por eso el ciclo se caza en PLACEMENT, no en runtime; (6) belt_ref del hijo no-resoluble → hijo corre
pero no hace nada (sibling, colocar agentes cuyos belts corran).

- **Harness** `verify_fractal_colocar.mjs` (8104): colocar agente-pieza → save → load → estructura
  idéntica (agent_refs intactos, jamás en belt_refs); ciclo A→B→A → rechazo honesto en placement;
  cajón → cero agent_ref + tools suben por unión; export escribe `catalog/agents/agent-<uuid>.config.json`
  con `schema_version:"v1"` sin `canvas` (assert del archivo real).

### D4 · READINESS (contrato de entorno aislado)
- Preparar una base de datos y un venv propios para el harness.
- Elegir puertos libres; no reutilizar ni reiniciar sesiones o servicios de otros usuarios.
- Levantar backend del árbol inspeccionado, fijar FORGE_E2E_BASE y realizar teardown sólo del proceso propio.
- La delegación real requiere claves de prueba configuradas explícitamente fuera del repo; no recuperar archivos de otras sesiones.

### D4 · ARQUITECTURA DE HONESTIDAD (ground truth vivo — decide la forma de D4)
El anti-grift es el alma del proyecto ("datos reales ejecutados"). Dos niveles de "real", NO confundir:
- **`verify_delegation_real.py` = motor REAL + cerebro FakeBrain** (monkeypatch de `_route_chat` con guión
  determinista de tool_calls). Emite eventos ESTRUCTURALES REALES por el motor genuino: `sub_agent_started`/
  `sub_agent_finished`, `tool_calls` reales, bridge real, gate/workdir reales. PERO `model_final="fake-brain"`.
  **Esto NO es grift** — los eventos que encienden el recinto salen del motor real, no de animación in-page.
  Lo único guionado es el token-output del LLM. Es el patrón para probar que el muro se enciende con eventos
  REALES del run.
- **Cerebro REAL** requiere modelo y API key explícitos de un entorno de prueba aislado.
  Registrar model_final y degraded reales; no usar configuración ni crédito de otra sesión.

**Forma honesta de D4:**
1. **Front wiring (real, determinista):** el recinto del hijo se enciende con `sub_agent_started` (key=slug),
   se apaga / pasa a "espera tu OK" con `sub_agent_finished` (status ok|error|gate, held>0). Muestra lo que
   CRUZA (result bridged) vs lo que NO (log sub_runs). Indicador anti-grift "no es el cerebro" keyed en el
   campo `degraded` (probar la DISCRIMINACIÓN: feed degraded=null → verde; degraded poblado → banner). Bus B2
   cruzando el muro; A3/RAG C1 NO dentro del hijo (§1).
2. **Harness backend-real (`verify_fractal_frontera.mjs` o .py):** driva una delegación REAL por el patrón
   FakeBrain-sobre-motor-real (como verify_delegation_real.py), captura los eventos ESTRUCTURALES REALES, y
   asserta: sub_agent_started/finished emitidos por el motor real, tool_calls>0 reales, el result cruzó al
   padre, el log sub_runs NO cruzó al cerebro del padre (RIEL#5). El recinto se enciende desde eventos
   genuinos, jamás gateHold in-page (§7e = grift).
3. **Assertion de cerebro-REAL (model_final=claude-opus-4.8, degraded=null):** INTENTAR si el brain_shim +
   key están disponibles (levantar shim en su puerto, backend propio en puerto LIBRE ≠8080/8090/8091). Si NO
   disponible → documentar HONESTO como env-blocked (needs Anthropic key), NO fabricar. **PROHIBIDO:** afirmar
   opus cuando es fake-brain; encender el muro con animación/gateHold sin run real detrás.

### D4 · Muro-frontera VIVO con SSE REAL  ← necesita run real (patrón forge, backend)
Encender el recinto del hijo con los **eventos estructurales del padre** (§1):
- `sub_agent_started` (`recipe_assembler.py:1801`, key=`slug`) → enciende el recinto (halo→event-driven,
  glifo pulsa).
- `sub_agent_finished` (`:1875`, `status ok|error|gate`, `held>0`) → apaga / "espera tu OK" si held.
- `event.result` = lo que CRUZA (bridge JSON). `record['sub_runs'][i]` = LOG (lo que NO cruza) →
  panel D5.
- Anti-grift: `model_final` + `degraded` de eventos cost/final (`:1570/738/759/2096`); indicador
  "no es el cerebro" con `notice/degraded` (`:769`). Key-ear en `degraded`, NO en "un modelo respondió".
- Bus B2 dibujado CRUZANDO el muro (cilindro compartido), memoria A3/RAG C1 **NO** dentro del hijo.
- **Cablear al canal existente**: `consumeLive`/`gateHold`/`gateRelease` (`api:2131-2145`), `gateState`
  Map (`:1118`), plomería SSE real `cuarto.live.js:32-47` (`EventSource`+`openSSERetry`).
- **Harness** `verify_fractal_frontera.mjs` (backend real, patrón `forge_equip_e2e.mjs` — NO stub
  /v1, `FORGE_E2E_BASE`): run padre→delega→recinto hijo se enciende con SSE REAL; anti-grift verde
  (`model_final=claude-opus-4.8`, `degraded=null`, `tool_calls>0`). **Ojo**: `run_forge_equip_verify.sh`
  NO existe en disco → escribir el orquestador (levantar backend :puerto + serve.py + `FORGE_E2E_BASE`).

### D5 · Panel del recinto  ← usa datos de D3 (identidad) + D4 (estado vivo)
Click en recinto-agente (sin entrar) → panel: nombre, modelo, piezas count
(`blocks.filter(atom!=='agente').length`, patrón `pixi.html:2460`), memoria propia sí/no
(GET `/v1/puppets/{id}/memories` — sólo top-level UUID). Acciones: **Entrar** (→D2 push-in),
**Desacoplar** (→`emancipate`/`removeTile` del agent_ref, `render:1023/1085`), **Ver en My agents**
(→`loadPuppet` NO destructivo). Colgar del inspector existente (`onPropClick:833`).

---

## 5. FRONTERA FREE|PREMIUM (hacer visible, NO cambiar) — cierra §5

Es un MIX (NO "delegar = premium"):
- **DURO (402 + upsell)**: SÓLO el **bus de memoria compartida** entre >1 agente —
  `recipe_assembler.py:1201-1215` (`shared_bus_denied`, `upsell{feature:'shared_memory_bus',
  min_tier:'basico'}`), espejo `executor.py:626-628`, tabla `recipe_enforcer.py:415-418`.
- **SOFT (throttle + aviso honesto, NO refusal)**: **paralelismo** de sub-agentes —
  `max_parallel` free=1/basico=3/tecnico=10, `delegation_serialized` (`recipe_assembler.py:1782-1788`).
- **La delegación NO está gateada**: free PUEDE delegar (serializado a 1 hijo).
- Step 3 muestra ambos SIN cambiarlos. Ojo: con `_caps_ceiling=None` (CLI/tests) AMBOS se apagan
  (`recipe_assembler.py:1201` exige `is not None`) — no inferir "no hay gate" de esos harness.

---

## 6. HARNESS — molde committeable (§6.4)

Calcado de los 5 verifies verdes: `.mjs` ESM + Playwright/Chromium headless; `python3 -m http.server
<PORT>` cwd=`product/app/design` (para que `../theme.js` resuelva); puerto ÚNICO ≠ 8091
(libres: 8103+); `page.route('**/v1/**')→'[]'` (D2/D3/D5 sin backend); `waitForFunction(window.__cuarto
&& window.Projection)`; assertions por `page.evaluate()` sobre el api real + snapshots read-only
(`recintoDraw`/`recintoState`/`relationModel`/`cam.*`); `page.mouse` para interacción real;
`waitForFunction` poll (NO `waitForTimeout` — headless throttlea rAF); `finally{ server.kill('SIGKILL') }`;
`process.exit(fails?1:0)`. D4 usa la variante **backend real** (sin stub, `FORGE_E2E_BASE`).
Worktree ya tiene symlink `node_modules→puppet-ai/node_modules` (load-bearing) + Chromium global.

**Ejes del gate §7 a cubrir:** round-trip fractal (colocar→save→load idéntico, agent_refs jamás en
belt_refs) · entrar/salir N niveles → padre byte-idéntico · ciclo A→B→A → rechazo honesto · tope de
profundidad → mensaje honesto no crash · cajón NUNCA agent_ref · run padre→hijo → recinto se enciende
con SSE REAL (anti-grift verde).

---

## 7. RIESGOS (para el review adversarial §6.5)

- **(a) Fuga de referencia**: agent_ref que cae a belt_refs → motor lo carga como belt y muere en
  silencio. NUNCA divergir `isAgentPiece` render≡projection. Filtro `toolish` excluye agentes.
- **(b) Profundidad como DoS**: recursión de render/proyección al entrar N niveles / receta con
  ciclo no detectado en autoría. Tope UI + guardia de ciclo mirror del runtime.
- **(c) Pertenencia (grift inverso)**: el visual NO debe prometer aislamiento que el runtime no da
  (memoria A3/RAG del hijo NO existe en delegación) NI mostrar compartido lo aislado (gate/workdir
  del hijo). Ver §1.
- **(d) Estado del padre corrompido al volver**: el snapshot del sceneStack debe ser inmutable y la
  restauración byte-idéntica. Congelar `fitAll` mientras `__inChild`.
- **(e) Anti-grift D4**: encender el muro con `gateHold` in-page (como el test E actual) sería grift.
  D4 exige SSE REAL de un run. Key-ear en `degraded`, no en "respondió un modelo".

---

## 8. ESTADO DE BUILD (checklist vivo)

- [x] Ground truth vivo (§2 spec) — workflow 5 readers + reconciliación
- [x] Diseño cerrado (este doc) — 3 decisiones + pertenencia
- [x] **D2 · zoom semántico** — VERDE VERIFICADO (corrido por Supervisor, exit 0). `verify_fractal_zoom.mjs` (8103). Assert load-bearing: modelo del padre byte-idéntico al salir ✓ (NO tautológico: enter monta 2 piezas del hijo + oculta padre + mueve cámara). fitAll-guard + tope depth ✓. 3 recinto verifies sin regresión.
- [x] **D3 · puente identidad + colocar/exportar + ciclos** — VERDE VERIFICADO. `agent_catalog.py` (exporter UUID-keyed, atómico, {**config,v1}−canvas) + side-effect en router.py create/update (repo_root=parents[4]). Front: cuartoPlaceAgent + cycle-guard BFS (self+multi-hop, visited=DAG-safe) + refToUuid + fetch real vía GET /v1/users/{id}/puppets. pytest 8/8; `verify_fractal_colocar.mjs` (8104) VERDE (round-trip, cajón-never-agent_ref, ciclo A→B→A rechazado en placement). 4 regresiones verdes. UX: botón "＋ colocar" en Mis agentes (aditivo, junto a "abrir" destructivo). Draft sin guardar = sentinel `__cuarto_draft__`.
- [x] **D4 · muro-frontera + anti-grift** — VERDE VERIFICADO (Supervisor). El recinto enciende desde eventos REALES del motor (FakeBrain-sobre-motor-real, in-process; `verify_frontera_d4.py` regenera el dump vivo: clean=6/held=9/degraded=7). `verify_fractal_frontera.mjs` (8105): muro dark PRE-evento (§7e), enciende running/held/error por SLUG, `degraded` FLIPEA en el campo real, bus B2 cruza sólo si hay pieza memoria+miembro (FIX C), cero A3/RAG privado fabricado. **NIVEL DE VERIFICACIÓN (honesto, corregido por review §9·D):** **Nivel 1 = eventos REALES del motor, replayed por la api** ✅ probado. El dispatch SSE de PRODUCCIÓN (`consumeLive`) ahora comparte UNA sola fn `__cuartoApplyFrontierEvent` con el replay (FIX D) → un typo en el acople rompe AMBOS y lo caza `verify_b1_consent.mjs` (SSE real por consumeLive) ✅. **SSE-real-full end-to-end (EventSource→backend vivo) = NO montado** (needs backend en puerto libre + `run_forge_equip_verify.sh` ausente). model_final=fake-brain/qwen (explícito NO opus); real-opus ENV-BLOCKED (sin ANTHROPIC key; shim de otra sesión NO hijackeado). RIEL#5 intacto.
- [x] **D5 · panel del recinto** — VERDE VERIFICADO. `verify_fractal_panel.mjs` (8106) 22/22: click abre panel (cajón NO), identidad node-derived (nombre/modelo/piezas/uuid/memoria), 3 acciones (Entrar→enter, Desacoplar→removeTile sin borrar de DB, Ver→?puppet=uuid). ownMemory/pieceCount degradan a "—" sin backend (honesto).
- [x] **REVIEW ADVERSARIAL (§9) + FIXES** — VERDE VERIFICADO. 16 hallazgos confirmados; los 6 blockers/should-fix (A HIGH espacial, B re-entrancy, C busCrosses, D consumeLive coverage, E puente e2e, F export swallow) + 2 trivials CERRADOS y re-verificados por Supervisor. Suite completa post-fix: 3 pytests (8+3+3) + D4 motor-real + 8 harnesses front = TODO exit 0. **FIX A no-tautológico probado** (revert-test: el assert espacial va ROJO en pre-fix mientras relationModel queda verde). Ver §9 para el estado por-hallazgo.
- [ ] Review adversarial (background)
- [ ] Merge --no-ff con tree-identity a main

### Reproducir el verde (desde el worktree)
```
cd ${ALEPH_REPO_ROOT:?set repository root}
python3 -m pytest product/backend/app/phase1/test_agent_catalog.py -q          # D3 exporter: 8 passed
cd product/app/design/cuarto
node verify_fractal_zoom.mjs        # D2  → VERDE exit 0
node verify_fractal_colocar.mjs     # D3  → VERDE exit 0
node verify_recinto_modelo.mjs && node verify_recinto_render.mjs && node verify_recinto_interaccion.mjs   # D1 regresión
```
(node_modules es symlink→puppet-ai; Chromium global; python3 sirve http.server por harness en puertos 8097-8104.)

### Pendiente para el MERGE (deuda honesta, no bloquea D4/D5)
- El side-effect router create/update→export_agent: el efecto DB→archivo real sólo corre contra Postgres vivo, PERO el puente exporter→resolver ahora tiene test e2e (`test_agent_catalog_bridge_e2e.py`: export_agent→resolve_agent_ref carga + slug byte-agreement) y `bridge_pending` señala export fallido (FIX E/F). Lo que NO está montado: una corrida HTTP viva create_puppet→delegate end-to-end (needs backend en puerto libre). [corregido: el claim previo "D4 ejercita create→export→resolve→delegate completo" era FALSO — D4 usa fixtures que bypassean router+exporter].
- Cross-owner refs: `GET /v1/users/{id}/puppets` sólo trae agentes del OWNER; si B referencia un agente de OTRO dueño, el walk no lo trae → posible sub-detección de ciclo. Revisar en review adversarial.
- `cuarto.render.js` quedó `M` en git desde D2 (además de pixi.html/projection.js/recipe.js sin cambio). Al mergear: `git add` SOLO los archivos de Step 3 (regla g), jamás -A.

> GESTIÓN DE CONTEXTO: checkpoint + reinicio de contexto a ~70k. Este doc + los harnesses viven en el worktree.

---

## 9. REVIEW ADVERSARIAL (§6.5) — hallazgos confirmados + triaje

Workflow multi-agente (6 ejes → find → skeptic-refuta cada uno → sobreviven). 19 crudos → 16 confirmados/parciales (3 refutados).

> **ESTADO: los 6 blockers/should-fix (A·B·C·D·E·F) + 2 trivials → CERRADOS y re-verificados** (fix pass + Supervisor corrió la suite completa post-fix, todo exit 0; FIX A probado no-tautológico por revert-test). Los DEFER/LOW quedan documentados abajo (backstopped/cosmético). Detalle de cada fix en el reporte del fix pass; resumen por-hallazgo: A=guard de crecimiento keyed en fractalStack + spatialSnapshot asertado · B=lock _enterInFlight + re-validación post-await · C=busCrosses derivado de model.relationships('comparte') · D=fn compartida __cuartoApplyFrontierEvent (consumeLive+replay una sola) cubierta por verify_b1_consent · E=test e2e create_puppet-row→export_agent→resolve_agent_ref + slug byte-agreement · F=bridge_pending en respuesta create/update · trivials=runDegraded rename + .gitignore.

### MUST-FIX (merge-blockers)
- **A · FUGA ESPACIAL (HIGH, bug vivo real).** `cuarto.render.js` enter/exit (snapshot 1599-1602 / restore 1627-1640) NO snapshotea N/grid.cols/rows, scene.zones, scene.tiles/floorNodes. Agregar una pieza desde la paleta ESTANDO dentro de un hijo → `placeTile` sin celda → `growToN` (2180/497-504, sin guard de fractalStack) crece el grid COMPARTIDO; al salir el padre queda con grid crecido + floor huérfano + zones drifted. `relationModel()` no serializa gx/gy ni grid → el assert byte-idéntico es CIEGO. También `growZone`/`freeCell` (_pushRight 463-468). Reachable por el afford primario "agregar tool al sub-agente". **FALSIFICA el invariante load-bearing de D2.** Fix: (c) bloquear/escopar crecimiento (placeTile-sin-celda, growZone, freeCell) mientras fractalStack.length>0, O (a) snapshot+restore de N/grid/zones/floor. + añadir caso de harness edit-then-exit con snapshot ESPACIAL (no sólo relationModel) — cierra también los asserts tautológicos I/K.
- **D · "SSE real VERIFICADO" OVERSTATED (anti-grift).** `consumeLive` (dispatch SSE de producción, cuarto.pixi.html ~2950/2960/2969/2972) NO lo ejercita NINGÚN harness D4 — sólo la copia paralela `__cuartoReplayEvent`. Un typo en el acople de campos (e.status/e.held/e.result/e.slug/e.degraded/e.model) shipea verde. Fix: rutear `verify_fractal_frontera.mjs` por `consumeLive` (no la copia duplicada) — así las dos no divergen — Y corregir el claim del doc a "Nivel 1: eventos REALES replayed por la api; SSE real = pendiente".
- **E · router→exporter→resolver SIN test e2e + claim falso.** Ningún test alimenta output del exporter por `belt_resolver.resolve_agent_ref`; D4 usa fixtures hand-written que bypassean router Y exporter. Slugs concuerdan HOY byte-a-byte (sin defecto vivo) pero drift → AgentResolutionError silencioso. Fix: 1 test de integración (row shape real de create_puppet → `agent_catalog.export_agent` → `resolve_agent_ref('catalog/agents/agent-<uuid>.config.json')` carga) + corregir el claim del doc ("import/parse-verified only", NO "create→export→resolve→delegate completo").

### SHOULD-FIX (barato, alto valor — contrato anti-grift)
- **B · enterRecinto RE-ENTRANCY (MEDIUM).** cap chequeado (1581) ANTES del `await` fetch (1588), push del frame (1611) DESPUÉS, sin lock → N enters en un RTT bypassean MAX_DEPTH_UI + corrompen el stack (phantom levels). Dormant bajo stub (fetch=null), vivo contra backend real. Fix: flag in-flight al tope de enterRecinto (return {ok:false,reason:'busy'}), o snapshot+push ANTES del await + re-validar node tras el await.
- **C · busCrosses GRIFT-INVERSO (MEDIUM).** `render.js:2053` `busCrosses: agent ? (sharesMemory!==false) : false` → true en TODO recinto-agente aunque NO haya pieza memoria (default cuartoPlaceAgent no pone memoria). Contradice el cable teal (rebuildModel 1218-1228) y projection.js:133 (runtime no comparte sin bloque memoria). No pinta pixel (sólo el contrato medible recintoDraw().busCrosses + assert tautológico del harness). Fix: derivar de `model.relationships.some(r=>r.kind==='comparte' && r.to===n.id)` → el campo medible y el cable no pueden discrepar. Corregir el assert del harness (escena SIN memoria → busCrosses false).
- **F · export swallow SILENCIOSO en deploy read-only (MEDIUM).** router.py:236-239 catch-all + log; DB commit + 201. En container read-only (topología mainstream) TODO export falla silencioso → agente colocado permanentemente NO-delegable (asesino silencioso; delegation.py omite ref no-resuelto sin ruido). Self-heal sólo en re-save. Fix: flag `bridge_pending` en la respuesta create/update, o barrido de reconciliación.

### DEFER/DOCUMENT (low, backstopped o cosmético)
- Cross-owner cycle-guard (LOW, self-admitted §8, runtime backstop soft cycle_detected + MAX_DEPTH=3) — documentar en UX que refs cross-owner se validan sólo en runtime.
- Per-recinto `degraded` mislabel (render.js:2052, LOW) — sin consumidor vivo; drop del _draw o renombrar `runDegraded`.
- fitAll congelado → cámara stale tras cambio de inset de panel dentro del hijo (LOW, cosmético self-healing) — en exit re-fit en vez de tween a cam stale.
- error→red-tint sin evento de motor capturado (LOW) — front mapping SÍ cubierto (mjs:190); falta fixture de hijo-que-falla para capturar status='error' real.
- `.gitignore` sin `catalog/agents/agent-*.config.json` + `.agent-*.tmp` (LOW, guardado por regla g) — agregar reglas.
- Checklist §8 stale — actualizar tras re-verify.

### Verde honesto (skeptics REFUTARON): predicados isAgentPiece≡_isAgentPiece byte-idénticos (sin fuga a belt_refs); cycle-guard BFS NO infinite-loopea (visited); exitTo(bad idx) clamped; exporter atómico + no escribe en catalog real en tests; router side-effect no rompe el save; el DATO de D4 es real (verify_frontera_d4 regenera el dump byte-idéntico, motor real, model_final honesto ≠opus, degraded flipea en el campo real). El alma anti-grift de D4 (Nivel 1) es GENUINA.

> Estado durable acá: D1✅(main) D2/D3/D4/D5 construidos+verde-por-harness. REVIEW encontró A(HIGH)+D/E(overclaim)+B/C/F(should) → FIX antes de merge. Luego re-verify + merge --no-ff.
