# RECETA — Schema del `config.json` (el contrato taller ↔ assembler ↔ run)

## PUNTOS CLAVE
- La **receta** es el contrato único: el **taller** la produce, el **assembler** la consume, el **run** la ejecuta y la loggea. Un solo schema parametrizable; **agregar nicho = escribir receta, no recodear**.
- Es **nicho-agnóstico**: ninguna clave es de un nicho. Lo que cambia entre Tutor STEM y Agente Finanzas son los **valores**, no la forma.
- Mapea 1:1 a la columna `puppets.config` (JSONB) de la DB de Fase 0. Lo valida el Workshop contra este schema antes de guardar.
- **BYOK por referencia, nunca por valor**: la receta apunta a `keys` (cifradas at-rest); la clave en claro jamás vive en la receta.
- **Decisión:** ✅ **APROBADA el 2026-06-15 — A + A + C** (`decision-2026-06-15-001-recipe-schema`): forma **anidada v1** · belt por **`belt_ref` de catálogo** · **gates declarados en la receta**. Fase 1 (Frontend/AI-ML/Product) DESBLOQUEADA.

---

## 1. Para qué existe
Para que el **taller** (UX de persona usuaria-usuario), el **assembler** (la fábrica) y el **run**
(instrumentación) compartan un contrato estable y versionable, la receta se define como un
schema **v1 anidado y explícito** — separa niveles (modelo / belt / framing / rag / keys /
gates) y mantiene la receta **portable** (no acopla paths del host).

## 2. El schema v1 — APROBADO (anidado · `belt_ref` · gates en receta)

```jsonc
{
  "schema_version": "v1",            // string; el Workshop valida contra esta versión

  "meta": {
    "name": "Agente Finanzas",       // requerido — nombre visible del puppet
    "nicho": "finanzas",             // requerido — string libre (cowork|research|programacion|educacion|finanzas|...)
    "descripcion": "..."             // opcional — qué hace este agente (1 línea)
  },

  "model": {
    "primary": "gpt-oss-120b",       // requerido — alias LiteLLM o id directo (OSS-first)
    "fallback": "llama-3.3-70b",     // opcional — a quién escala si primary falla la tarea
    "base_url": "http://127.0.0.1:4000/v1",  // requerido — el gateway LiteLLM
    "temperature": 0,                // requerido — [0.0, 2.0]
    "max_tokens": 2048,              // requerido — entero positivo
    "max_turns": 8                   // requerido — tope del loop tool-use
  },

  "belt": {
    "belt_ref": "catalog/belts/finanzas.md",   // requerido — slug de catálogo; el runtime lo resuelve al .mcp.json (PORTABLE, decisión B)
    "agent_refs": ["catalog/agents/research"],  // opcional (amendment 2026-06-26) — refs a OTRAS RECETAS (sub-agentes). SIEMPRE acá, NUNCA en belt_refs[]
    "tool_filters": {                           // requerido no-vacío... salvo que sólo delegue (agent_refs presente → puede ir {})
      "excel": ["apply_formula", "read_data_from_excel"],
      "secedgar": ["get_cik_by_ticker", "get_financials"]
    },
    "tool_aliases": {                           // opcional; alias final estable por server/tool cruda
      "a": {"search": "a__search"},
      "b": {"search": "b__search"}
    }
  },

  "framing": {
    "ref": "framing/finanzas.md",    // opcional — archivo de framing (system prompt)
    "inline": null                   // alternativa: framing embebido como string
  },

  "rag": {
    "enabled": true,                 // requerido (bool)
    "mode": "manual",                // requerido si enabled=true (manual|auto)
    "dir": "rag/finanzas"            // opcional — corpus del nicho
  },

  "keys": {                          // opcional — BYOK POR REFERENCIA, nunca el valor
    "fred":  { "byok_ref": "keys:fred" },          // resuelve contra la tabla keys (cifrada)
    "alpha_vantage": { "byok_ref": "keys:alpha_vantage" }
  },

  "gates": {                         // opcional — la receta DECLARA; Security HACE CUMPLIR (ver §3.5)
    "money_touch": "needs_ok",       // off | needs_ok
    "send":        "needs_ok"        // off | needs_ok (Email/WhatsApp/mensajería)
  }
}
```

## 3. Reglas del contrato
1. **Requeridos:** `schema_version`, `meta.name`, `meta.nicho`, `model.{primary,base_url,temperature,max_tokens,max_turns}`, `belt.belt_ref`, `belt.tool_filters`. `rag.enabled` requerido; `rag.mode` requerido si `enabled`.
2. **Nicho-agnóstico:** prohibido agregar una clave que solo sirva a un nicho. Lo específico vive en los **valores** (`nicho`, `tool_filters`, `framing`, `rag.dir`), nunca en la forma.
3. **`tool_filters` = solo el subset curado** (no los 200 conectores). El assembler cabla SOLO lo listado. Se valida que cada server exista en el belt resuelto y que los tools existan en el surface sondado (lógica base en `config_validator.py`, a extender para forma anidada + `belt_ref`).
4. **BYOK por referencia:** `keys.<provider>.byok_ref` apunta a la tabla `keys` (cifrada Fernet at-rest, Fase 0). El valor en claro **nunca** entra a la receta ni a `puppets.config`.
5. **INVARIANTE DE SEGURIDAD (no-negociable, orden del founder 2026-06-15) — la receta DECLARA, Security HACE CUMPLIR:**
   - El **motor fuerza** los gates mandatorios (`money_touch`, `send`) **aunque la receta los omita o los ponga en `off`**. La omisión NO desactiva un gate mandatorio.
   - La receta puede **AGREGAR** gates (más estrictos), **NUNCA quitar** los mandatorios.
   - El `belt_ref` + `tool_filters` NO bastan para saltar un gate: si una tool toca plata o manda, el gate aplica por clasificación de la tool en Security, no por lo que diga la receta.
   - El **send-gate debe existir ANTES** de cablear Email/WhatsApp/mensajería (regla del plan; ver Fase 1 Security).
6. **Versionado:** `schema_version` permite migrar sin romper recetas viejas. Cambios incompatibles ⇒ `v2` + migración, no edición silenciosa de `v1`.
7. **AGENTE ANIDADO — `belt.agent_refs[]` (amendment ADITIVA-v1, 2026-06-26):** además de `belt_refs[]` (tools), la receta puede traer `belt.agent_refs[]` = lista de slugs STRING que apuntan a **otras recetas** (sub-agentes). Reglas: (a) un agente va SIEMPRE en `agent_refs`, **JAMÁS** en `belt_refs[]` (tipar `belt_refs[i]` a objeto HARD-FALLA, a propósito); (b) `tool_filters` puede ir `{}` **sólo si** hay `agent_refs[]` (padre que sólo delega); sin `agent_refs`, sigue requerido no-vacío; (c) no se toca el set de top-keys ni la forma de `belt_refs[]`. Aditivo igual que `model.alias`: se queda en v1, una receta sin `agent_refs` valida idéntico. El resolver devuelve `ResolvedAgent{type:"agent", recipe}` vs `ResolvedBelt{type:"tool"}`. La **ejecución/delegación** es un paso aparte (ver contrato §6 + rama `delegacion-spike`).

## 4. Cómo lo usan los tres lados
- **Taller (Frontend):** edita una receta y la valida contra este schema antes de `guardar`. Una sola UX universal; la cirugía de params opera sobre estas claves. Muestra los gates declarados (los mandatorios siempre, aunque la receta no los liste).
- **Assembler (AI/ML/Runtime):** consume la receta, resuelve `belt_ref` → `.mcp.json`, cabla el subset del belt, resuelve `byok_ref` contra `keys`, monta el espacio y corre el loop. Parametrizable: 2 recetas de nichos distintos sin tocar código.
- **Run / instrumentación (DB):** al correr, se guarda un **snapshot de la receta** en `instrumentation_logs.belt` (campo 2 del moat), ligado por `run_id`.
- **Security:** intercepta el loop y fuerza los gates mandatorios por clasificación de tool — independiente de lo que declare la receta (§3.5).

## 5. La decisión (A+A+C aprobada)
| # | Decisión | Elegida |
|---|---|---|
| **A** | Forma del config | **Anidada v1** (model/belt/framing/rag/keys/gates) |
| **B** | Cómo apunta al belt | **`belt_ref` de catálogo** (portable; runtime resuelve al `.mcp.json`) |
| **C** | Gates en la receta | **Declararlos** — con la INVARIANTE §3.5 (Security los hace cumplir) |

## 6. Estado y bloqueo
- ✅ **APROBADO A+A+C** — `org/founder/decisiones/decision-2026-06-15-001-recipe-schema.md` (respondido). Eventos `founder_item` + `founder_respuesta` emitidos.
- **Fase 1 DESBLOQUEADA**: Frontend, AI/ML y Product arrancan con este contrato.
- **Trabajo que habilita esto:** AI/ML construye el resolver `belt_ref`→`.mcp.json` y el assembler que consume la forma anidada; Backend/Frontend extienden `config_validator.py` a la forma anidada; Security implementa la invariante §3.5.
- DB + tabla de tools de Fase 0 ya cerradas (no dependían).

> v1 — 2026-06-15 — FASE 0 · levantado y APROBADO (A+A+C) el mismo día. Alineado con `platform/assembler/config-stem.json` (forma vieja, a migrar a anidada) + `product/backend/app/config_validator.py` + `platform/db/schema.sql` (`puppets.config`).
