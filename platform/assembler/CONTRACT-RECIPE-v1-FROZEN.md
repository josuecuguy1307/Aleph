# CONTRATO RECIPE v1 — ❄️ CONGELADO (F0 · owner T5)

> **Estado: CONGELADO el 2026-06-21 por T5 (assembler + gateway).**
> Confirmado contra el código REAL (PASO 0), no contra una idea. T1 (Cuarto) y T4
> (inspección/eventos) codean contra ESTA forma. **Nadie cambia este contrato sin avisar
> al integrador** (regla F0 §5). Cambios incompatibles ⇒ `schema_version: v2` + migración,
> jamás edición silenciosa de v1.

Este doc es la **única fuente de verdad de la forma de la receta**. Reemplaza como
referencia operativa cualquier resumen informal (incluida la forma idealizada
`{nucleo, blocks}` del brief §4.1, que aquí queda **mapeada** a la receta real).

---

## 0. Qué es la receta y por qué hay UNA sola forma

La receta (`puppets.config`) es el contrato único: el **Cuarto/taller** la produce, el
**assembler** (`platform/assembler/recipe_assembler.py`) la consume, el **run** la ejecuta y
la loggea. Es **nicho-agnóstico**: lo que cambia entre un agente de Finanzas y uno de
Research son los **valores**, no la forma. **Agregar nicho = escribir receta, no recodear.**

Las **piezas del Cuarto son una PROYECCIÓN de esta receta** — no hay grafo paralelo.

---

## 1. La forma CONGELADA (v1 anidada) — confirmada contra el código

```jsonc
{
  "schema_version": "v1",                    // REQUERIDO

  "meta": {                                  // REQUERIDO
    "name": "Agente Finanzas",               //   REQUERIDO — nombre visible (= núcleo.identity)
    "nicho": "finanzas",                     //   REQUERIDO — string libre; selecciona el domain-framing
    "descripcion": "..."                     //   opcional   — 1 línea (= parte de núcleo.objective)
  },

  "model": {                                 // REQUERIDO
    // ── DOS formas de fijar el modelo (se elige UNA; precedencia abajo) ──
    "alias": "brain",                        //   NUEVO/opcional — ALIAS PORTABLE (ver §3). Recomendado.
    "primary": "openai/gpt-oss-120b",        //   opcional si hay alias — id directo (forma histórica)
    "fallback": "llama-3.3-70b-versatile",   //   opcional — a quién escala si primary FALLA (transporte)
    "base_url": "https://api.groq.com/openai/v1", // requerido si NO hay alias — endpoint OpenAI-compat
    "temperature": 0,                        //   REQUERIDO — [0.0, 2.0]
    "max_tokens": 2048,                      //   REQUERIDO — entero > 0
    "max_turns": 8,                          //   REQUERIDO — tope del loop tool-use
    "reporter": {                            //   opcional — 2ª etapa del pipeline (redacta el informe)
      "primary": "...", "base_url": "...", "fallback": "..."
    }
  },

  "belt": {                                  // REQUERIDO
    "belt_ref": "catalog/belts/finanzas.md", //   un belt: slug/ref de catálogo (PORTABLE; runtime → .mcp.json)
    "belt_refs": ["...", "..."],             //   COMPOSICIÓN: varios belts (un Cuarto = varias apps). 1º gana en colisión.
    "agent_refs": ["catalog/agents/research"],// NUEVO/opcional (amendment §6) — refs a OTRAS RECETAS (sub-agentes). SIEMPRE acá, JAMÁS en belt_refs[].
    "tool_filters": {                        //   REQUERIDO no-vacío... SALVO que sólo delegue: con agent_refs[] puede ir {} (§6)
      "excel":    ["apply_formula", "read_data_from_excel"],
      "secedgar": ["get_cik_by_ticker", "get_financials"]
    },
    "tool_aliases": {                        //   opcional: sólo superficie; filtros/gates siguen crudos
      "servidor_a": {"search": "servidor_a__search"},
      "servidor_b": {"search": "servidor_b__search"}
    }
  },

  "framing": {                               // opcional — capa de conducta ENCIMA del framing universal
    "ref": "framing/finanzas.md",            //   archivo de framing
    "inline": null                           //   o texto embebido (= parte de núcleo.objective)
  },

  "rag": {                                   // rag.enabled REQUERIDO (bool)
    "enabled": true,
    "mode": "manual",                        //   REQUERIDO si enabled (manual|auto)
    "dir": "rag/finanzas"                    //   opcional — corpus del nicho
  },

  "keys": {                                  // opcional — BYOK POR REFERENCIA, NUNCA el valor en claro
    "fred":          { "byok_ref": "keys:fred" },
    "alpha_vantage": { "byok_ref": "keys:alpha_vantage" }
  },

  "gates": {                                 // opcional — la receta DECLARA; Security HACE CUMPLIR (§4)
    "money_touch": "needs_ok",               //   off | needs_ok (el motor FUERZA needs_ok aunque digas off)
    "send":        "needs_ok"                //   off | needs_ok (Email/WhatsApp/mensajería)
  },

  "canvas": { /* posiciones/zonas/links del diorama */ }  // opcional — PRESENTACIÓN pura; el motor la IGNORA
}
```

**Top-keys permitidas (nicho-agnóstico):** `schema_version, meta, model, belt, framing, rag,
keys, gates, canvas`. Inventar una top-key fuera de este set = ERROR de validación
(`recipe_validator.py`). Lo específico de un nicho vive en los **valores**, jamás en la forma.

**Requeridos (validados):** `schema_version`, `meta.{name,nicho}`,
`model.{temperature,max_tokens,max_turns}` + (`model.alias` **o** `model.{primary,base_url}`),
`belt.{(belt_ref|belt_refs),tool_filters}`, `rag.enabled` (+`rag.mode` si enabled).
`belt.tool_filters` es no-vacío **salvo** que la receta sólo delegue (`belt.agent_refs[]`
presente → `tool_filters` puede ir `{}`; ver §6). `belt.agent_refs[]` es OPCIONAL y aditivo.

---

## 2. La PROYECCIÓN del Cuarto (§4.1 del brief) ⇄ la receta real

El brief describe el contrato como `{ nucleo, belt_refs, blocks, canvas }`. Eso es la **vista
del Cuarto** (cómo se piensan las piezas), y **mapea 1:1** sobre la receta congelada:

| Vista del Cuarto (§4.1) | Dónde vive en la receta v1 | Owner |
|---|---|---|
| `nucleo.model` | `model.alias` (o `model.primary`+`base_url`) | T5 |
| `nucleo.identity` | `meta.name` | — |
| `nucleo.objective` | `meta.descripcion` + `framing.inline`/`ref` | — |
| `belt_refs: []` | `belt.belt_refs[]` (o `belt.belt_ref` para uno) | T4 (composición) |
| `blocks: [{type, zone, gridX, gridY, ref}]` | **proyección** de los átomos colocados (`_meta.cards` de los belts) → `belt.tool_filters` (type=tool), `gates` (type=gate), `keys`/conexión (type=conexion), `rag`/framing (type=contexto) | T1 + atoms_router |
| `canvas` | `recipe.canvas` (presentación; el motor la ignora) | T1 |

**Los `blocks` NO son un campo nuevo de la receta.** Son la proyección que ya implementa
`product/backend/app/phase1/atoms_router.py` (`GET /v1/atoms/catalog`): agrega las
`_meta.cards` de los belts, les infiere la **zona** (C3: lee=Fuentes · procesa=Mesa ·
saca/gate=Entrega) reusando el enforcer, y el Cuarto, al colocar átomos, arma
`belt.belt_refs[]` (unión de los `belt_ref` de los átomos) + `tool_filters` (el subset).

> **Para T1:** un `block` colocado en el diorama proyecta a (a) su `belt_ref` → `belt.belt_refs[]`,
> (b) sus `tools` → `belt.tool_filters[server]`, (c) su `zone` (inferida, no la inventes), (d) su
> posición → `canvas`. Núcleo/gate/conexión/contexto son tipos de block que mapean a las claves
> de arriba. **No agregues `nucleo`/`blocks` como top-keys de la receta** — romperían la
> validación nicho-agnóstica. La receta guardada es la forma del §1; el diorama se rehidrata
> desde `canvas` + la proyección de `belt`/`gates`/`keys`.

---

## 3. Modelo por ALIAS (NUEVO · aditivo · "cambiar de modelo = 1 línea")

Fuente: `platform/assembler/models.py` (owner T5). La receta puede referenciar un **alias
portable** en `model.alias` en vez de hornear `primary`+`base_url` del proveedor.

**Precedencia (resuelta en `models.resolve_recipe_model`):**
```
env PUPPET_BRAIN=<alias>   >   model.alias   >   model.primary + model.base_url (histórico)
```

Tres palancas de **1 línea**, de global a local:
1. `PUPPET_BRAIN=<alias>` (env) — fuerza el cerebro de TODOS los runs (ops; ideal para e2e).
2. `models.DEFAULT_BRAIN` — a qué apunta el alias `brain`.
3. `models.ALIASES['<alias>']` — redefine modelo/endpoint/fallback de un alias.

**Aliases congelados (v1):** `brain` (cerebro e2e = Opus 4.8 vía OpenRouter, fallback OSS),
`oss` (gpt-oss-120b Groq), `premium` (llama-3.3-70b Groq), `constructor-code`,
`explorer-reason` (qwen3-32b), `vision` (gemini-2.5-flash), `oss-direct` (ollama local).

**Cerebro = Opus 4.8 real, robusto y con fallback VISIBLE (C6, 2026-06-21):** dos caminos a
Opus real, por env: PROD = OpenRouter con crédito (default congelado); DEV = shim local
OpenAI-compat en `:8923` (`brain_shim.py`) con `PUPPET_BRAIN_SHIM=1` (Opus real sin crédito).
Si el brain no responde (OpenRouter 402 / shim caído), el cascade cae a `oss` (Groq) y, en
última instancia, al OSS-directo (ollama) — el run **completa igual**, PERO la caída **ya no es
silenciosa**: se surfacea como `record["degraded"]` + un cost-event con `degraded:true` + un
aviso `{type:"notice", kind:"degraded"}` en el stream (ver §5). El default sin env = este
contrato congelado, byte por byte (tests `test_models` 1.1–1.4 verdes). Verificado en vivo.

**BACK-COMPAT:** una receta sin `alias` y sin `PUPPET_BRAIN` corre EXACTAMENTE como antes
(id directo horneado). El alias es 100% aditivo (45/45 tests del assembler en verde).

---

## 4. Invariantes NO-NEGOCIABLES (no cambian en v1)

1. **Nicho-agnóstico** — prohibido top-keys de un solo nicho (§1).
2. **BYOK por referencia** — `keys.<p>.byok_ref` (prefijo `keys:`). Un valor en claro = ERROR duro.
3. **Gates: la receta DECLARA, Security HACE CUMPLIR** — el motor FUERZA `money_touch`/`send` a
   `needs_ok` aunque la receta los omita o los ponga `off`. La receta puede AGREGAR gates
   (más estrictos), NUNCA quitar un mandatorio. Sin gate mandatorio construible ⇒ **fail-closed**
   (no se levanta el puppet). Implementado en `platform/gates/recipe_enforcer.py`, en el PATH del run.
4. **`tool_filters` = SOLO el subset curado** — el assembler cabla solo lo listado, nunca los 200.
   Si dos servidores de una entidad exponen el mismo nombre, `tool_aliases` publica
   `<servidor>__<tool>` para **todos** los colisionantes. El mapa se persiste en la receta:
   es único y estable aunque uno de los servidores caiga. Gates y `tool_filters` siguen
   usando el nombre crudo y el runtime conserva `{server, raw_name}` en la evidencia.
5. **`canvas` es presentación** — el motor la ignora; solo rehidrata el diorama.

---

## 5. COST-EVENT (§4.6) — producido por T5/T4, consumido por T7/T8

Cada run emite **un cost-event por cada call** (modelo y tool), ya scopeado:
```jsonc
{ "type":"cost", "kind":"model"|"tool", "user_id":"...", "run_id":"...",
  "model": "openai/gpt-oss-120b" | null, "tool": "mul" | null, "tier": "primary",
  "degraded": false,                                            // C6: aditivo
  "tokens": {"prompt":562,"completion":119,"total":681}, "tokens_measured": true,
  "usd": 0.0001557, "price_source": "groq.com/pricing ..." }
```
- Token = **medido** (campo `usage` del proveedor). usd = **tarifa documentada** (`models.PRICES`);
  si el modelo no tiene tarifa, `usd: null` — **no se inventa**. Tools locales = `usd: 0.0`.
- Salen en `record["cost_events"]` (assembler) y por `on_event` (SSE de T4 → billing T7/T8).
  El executor (`run_puppet_e2e`) los pasa scopeados a `user_id`/`run_id` y los expone en su salida.
- **FALLBACK VISIBLE (C6, aditivo):** `degraded:true` marca el cost-event de una call que
  respondió en un tier de red de seguridad (`fallback`/`oss-direct`) en vez del cerebro pedido.
  Además, la PRIMERA degradación del run emite un evento de transparencia (NO es cost, no entra
  al ledger de billing): `{ "type":"notice", "kind":"degraded", "intended_model", "intended_alias",
  "actual_model", "tier", "message" }`; y el run lleva el resumen durable `record["degraded"]`
  (expuesto como `out["degraded"]` por el executor). Campos 100% aditivos — back-compat total.

---

## 6. AGENTE ANIDADO — `belt.agent_refs[]` (amendment ADITIVA-v1 · 2026-06-26)

> Mismo patrón aditivo que `model.alias` (§3): **se queda en v1, NO salta a v2.** Una receta
> v1 SIN `agent_refs` valida y corre EXACTAMENTE como antes (cero cambio de comportamiento).
> Este amendment cubre **sólo el esquema + resolución + validación**; la EJECUCIÓN/delegación
> es un paso aparte (no toca este contrato). Verificado contra el código real
> (`recipe_validator.py`, `belt_resolver.py`) + regresión v1 (15/15 validador, 5/5 assembler,
> 21/21 enforcer, 8 recetas v1 reales idénticas).

**Qué es.** Hasta hoy una capacidad de la receta era SIEMPRE una **tool** (un belt MCP, vía
`belt.belt_refs[]`). El amendment agrega un segundo tipo de capacidad: el **sub-agente**. Una
`belt.agent_refs[]` es una lista de refs a **OTRAS RECETAS COMPLETAS** (cada una un agente con
su propio Núcleo, su belt, sus tools). El padre **delega** en el sub-agente (paso 2), no inlinea
sus tools.

```jsonc
"belt": {
  "belt_refs": ["catalog/belts/finanzas.md"],     // capacidades TOOL (igual que siempre)
  "agent_refs": ["catalog/agents/research"],       // capacidades AGENTE (refs a recetas hijas)
  "tool_filters": { "excel": ["apply_formula"] }   // puede ir {} si SÓLO delega (ver abajo)
}
```

**Reglas (no-negociables de este amendment):**
1. **Un agente va SIEMPRE en `agent_refs[]`, JAMÁS en `belt_refs[]`.** Regla load-bearing:
   `belt_refs[i]` sigue siendo un **string** (slug). Tipar un elemento de `belt_refs[]` a un
   objeto `{ref,type}` **HARD-FALLA** la validación a propósito — ese camino queda cerrado. La
   separación por clave paralela es lo que mantiene a los lectores viejos seguros (ignoran
   `agent_refs` que no entienden; sus `belt_refs[]` siguen siendo tools puras).
2. **`agent_refs[]` = lista de slugs STRING** (mismo tipo y reglas que `belt_refs[]`: no vacío,
   portable, sin paths absolutos del host). NO objetos.
3. **`tool_filters` puede ir vacío `{}` SÓLO si hay `agent_refs[]`** (un padre que sólo delega,
   sin tools propias). Sin `agent_refs`, `tool_filters` sigue REQUERIDO no-vacío (regla v1
   intacta). Es la única relajación de una regla existente, y está acotada al caso nuevo.
4. **No se toca `_ALLOWED_TOP_KEYS`** (`agent_refs` es sub-key de `belt`, no top-key) ni la forma
   de `belt_refs[]`. Cero top-keys nuevas.

**Resolución (paso 1, ya implementado — `belt_resolver.py`):**
- `belt_refs[i]` → `resolve_belt_ref` → `ResolvedBelt{type:"tool", mcp_json_path, servers}` (idéntico a hoy).
- `agent_refs[i]` → `resolve_agent_ref` → `ResolvedAgent{type:"agent", recipe_path, recipe}` (carga
  la receta hija + check estructural ligero v1; **NO ejecuta ni delega**). El discriminador `type`
  permite al paso 2 ramificar (delegar vs cablear MCP). La validación PROFUNDA del hijo y la
  delegación son el paso 2.

**Seguridad (recordatorio para el paso 2, fuera de scope acá):** cada sub-run debe construir su
PROPIO gate desde la receta del hijo (`recipe_enforcer.build_enforced_gate`) — los mandatorios
money/send se fuerzan por hijo, el hijo no hereda el OK del padre. Demostrado en el spike
`delegacion-spike` (5 rieles verdes); ver esa rama.

---

## 7. CEREBRO POR SUSCRIPCIÓN — `model.brain_provider` (amendment ADITIVA-v1 · 2026-07-09)

> Sub-key OPCIONAL dentro de `model` (NO top-key nueva; `_ALLOWED_TOP_KEYS` intacta). Una receta
> v1 SIN `brain_provider` valida y corre EXACTAMENTE como antes (cero cambio de comportamiento).

```jsonc
"model": {
  "primary": "claude-code-cli",            // ids del server cli_brain: claude-code-cli | codex-cli
  "base_url": "http://127.0.0.1:8926/v1",  // el server local BYO-CLI (PUPPET_CLI_BRAIN_BASE_URL)
  "alias": "claude_cli",                   // alias del registro (models.py) — portable
  "brain_provider": "claude_cli",          // NUEVO/opcional: claude_cli | codex_cli | byok | managed
  "fallback": null                         // sin fallback horneado: la red oss-direct actúa NARRADA
}
```

Reglas:
1. **Enum cerrado**: `claude_cli | codex_cli | byok | managed`. Otro valor → 422 (validador).
   Ausente → byte-idéntico a v1 (default histórico).
2. **`claude_cli` / `codex_cli`** rutean como ALIAS del registro (`models.py::ALIASES`) hacia el
   server local `cli_brain` (:8926), que spawnea el CLI YA AUTENTICADO del usuario con las tools
   del CLI OFF (pura cognición) y reporta el **model_final REAL** que el CLI usó. La precedencia
   de 1-línea NO cambia: `env PUPPET_BRAIN > brain_provider(cli) > model.alias > primary+base_url`.
3. **`byok` / `managed`** son DECLARATIVOS (el ruteo sigue por `byok_ref`/alias como siempre);
   sirven al badge/copy para distinguir el claim de costo (BYO-CLI ≠ BYOK: suscripción ≠ key).
4. **Anti-grift**: `brain_provider` viaja en el record y en los eventos `final`/`closed`
   (campos aditivos). La familia del badge suma el término DECLARADO: provider CLI declarado ∧
   model_final coherente (claude_cli → `claude-*`, codex_cli → `gpt-*`/`codex*`/`o<N>*`).
5. **Aleph JAMÁS ve/guarda/toca tokens de la suscripción** — la única interacción con el auth de
   cada CLI es su comando de estado (`claude auth status` / `codex login status`, D2).
6. **Rate-limit de la ventana** (distinto de API): el server cli_brain clasifica → HTTP 429
   `{"error":{"type":"throttled","brain_provider",...}}` → el runtime emite
   `brain_window_exhausted` (narrado con nombre de provider + reset) y el cascade sigue visible
   (`degraded`), jamás false green ni muerte silenciosa.

---

_v1 — ❄️ CONGELADO 2026-06-21 por T5; amendment §6 (agent_refs, aditiva-v1) 2026-06-26;
amendment §7 (model.brain_provider BYO-CLI, aditiva-v1) 2026-07-09. Base:
`RECIPE-SCHEMA.md` (APROBADO A+A+C 2026-06-15) + código real (`recipe_assembler.py`,
`recipe_validator.py`, `belt_resolver.py`, `atoms_router.py`, `models.py`)._
