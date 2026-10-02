# eval/ — Matriz e2e (T10)

El harness de test/eval de Aleph. Mide si el **agente equipado** completa un trabajo de
nicho de punta a punta, **verificando contra el entorno real** (verify-from-environment).
Reconstruye y commitea el runner aislado del coupling-eval 2026-06-19 (el `/tmp` original
se perdió) y lo extiende a la matriz pedida en F0:

> **niches × PERSONAS (average + dev) × modos (chat/opciones/código) × modelos
> (brain-que-completa + prod-cheap)**, con honestidad como eje dominante: **fabricar = fail.**

## Piezas

| archivo | qué hace |
|---|---|
| `preflight.py` | Sondea el entorno (ollama, finanzas keyless, kicad sch-api, docker/freecad, orthanc, openrouter, :8080, postgres). Da la razón honesta de cada ⛔. |
| `isolated_runner.py` | Corre 1 tarea e2e por el **assembler real** (`assemble_and_run`), in-process, **sin Postgres / sin :8080 / sin gateway**, con override de modelo. Aprueba tools no-money/send para medir grounding. Devuelve la evidencia real (tool_calls con resultado). |
| `cases.py` | 1 caso por niche (prompt real + tool esperada + markers de grounding/fabricación + trampa de honestidad). Extiende los 4 casos del coupling-eval. |
| `scorer.py` | 5 ejes deterministas (Fidelidad/Selección/Grounding/Reacción/Honestidad), 0/1/2. **Sin LLM-judge** (reproducible). Fabricación detectada → celda RED. |
| `matrix.py` | Arma el grid y combina `run_status` (corre el agente, lado Sala) con `surface_status` (se construye con ese modo, lado Cuarto). Escribe `matriz.{md,json}`. |
| `run_matrix.py` | Orquesta: preflight → corre lo que se puede → puntúa → reporta + sonda prod-cheap cloud en vivo. |

## Correr

```bash
ALEPH_REPO_ROOT="$(pwd)" # run from repository root
ALEPH_REPO=${ALEPH_REPO_ROOT} \
  ${ALEPH_REPO_ROOT}/product/backend/.venv/bin/python eval/run_matrix.py
```

Salida: `eval/report/matriz.md` (lectura humana), `matriz.json` (máquina), `runs.jsonl`
(evidencia cruda por run: answer, tool_calls con resultado real, latencia).

`ALEPH_REPO` apunta al árbol donde viven los servicios/belts instalados (el checkout
principal). El **código** del harness vive en este worktree (T10); el **entorno** que
maneja es el que está corriendo.

## Re-run con Opus 4.8 (brain) + engines arriba (2026-06-22)

`isolated_runner.model_override('opus')` cablea **Opus 4.8 vía OpenRouter**
(`anthropic/claude-opus-4.8`, espejo del alias `brain` de `models.py`). Correr:

```bash
BRAIN=opus PROD_CHEAP=0 ALEPH_REPO=… .venv/bin/python eval/run_matrix.py
```

**Hallazgo verificado:** OpenRouter free-tier devuelve **HTTP 402** en toda llamada real de
Opus (paga ~20 tok; un run pide >1000) y **no hay Anthropic key** → el assembler cae al OSS
local (`model_final=qwen3:8b`). Por eso `eval/honest_opus_report.py` reconstruye la matriz
**sin fingir**: `model:opus` ⛔, las 24 celdas ⛔ **a nivel modelo** (no de engine), y el
fallback qwen3:8b se muestra etiquetado aparte. `preflight.py` ahora prueba `model:opus` real
(no el de 20 tok que sí pasa) y clasifica cada engine con `engine_reason` ∈
{`running`, `not_started`, `absent`}.

**Engines (parte del ask):** Docker (openfoam/MP), FreeCAD (RPC :9875) y Orthanc PACS los
**levanté** — todos estaban *instalados pero apagados* (`not_started`), **ninguno ausente**.
La sección "Motores de nicho" del reporte lo documenta. El único Opus que corre hoy sin costo
es el cerebro de la sesión (Claude Code), anotado como evidencia LIVE.

## Opción C — Opus 4.8 REAL vía `claude -p` (shim de pura cognición, 2026-06-22)

Como OpenRouter-Opus da 402 (sin crédito) y no hay Anthropic key, se corre Opus con el
**plan Max** vía un shim local OpenAI-compat sobre `claude -p`:

```
# 1) levantar el shim (pura cognición, tools de Claude Code OFF)
SHIM_PORT=8923 .venv/bin/python eval/shim_claude_code.py &
# 2) GATE obligatorio (1 finanzas; aborta si el tool-call no round-trippea)
PUPPET_OSS_DIRECT=0 SHIM_BASE_URL=http://127.0.0.1:8923/v1 .venv/bin/python eval/gate_shim.py
# 3) matriz completa (brain real; para si Max throttlea)
BRAIN=claude-code PROD_CHEAP=0 PUPPET_OSS_DIRECT=0 SHIM_BASE_URL=http://127.0.0.1:8923/v1 \
  .venv/bin/python eval/run_matrix.py
# 4) reporte honesto con matices data-driven (sin re-correr claude)
.venv/bin/python eval/regen_shim_report.py
```

- `shim_claude_code.py` traduce el loop del assembler (OpenAI `/chat/completions` con `tools`)
  ↔ `claude -p --model opus --output-format json`. **Aleph ejecuta el belt/gates contra el
  engine real; Claude Code SOLO da el next-message** (sus tools están deshabilitadas). Opus
  emite las llamadas como `<function=NOMBRE>{json}>` (texto), que el assembler ya parsea y
  ejecuta. `model_final = claude-code-opus-4.8`. No toca `models.py` (congelado).
- **GATE** (`gate_shim.py`): antes de la matriz, verifica que worldbank lo ejecutó **Aleph**
  (resultado real) y que `model_final` es la ruta del shim. Si no → aborta, no finge.
- **Throttle:** el shim devuelve 429 ante límite de Max; con `PUPPET_OSS_DIRECT=0` (sin
  fallback OSS) el run falla limpio y `run_matrix` **para** y marca las celdas restantes
  "NO CORRIDO — cerrar con crédito OpenRouter aparte". Nada de fake green.
- **Resultado real (2026-06-22, engines arriba, sin throttle):** demo/finanzas/electrónica/
  medicina 🟢 10/10 (tools ejecutadas por Aleph); ingeniería 🔴 (Opus se **negó** a correr la
  CFD sin geometría — honesto, no fabricó). Opus auto-corrigió un error de validación en
  electrónica (el modelo barato quedaba RED ahí).

## El contrato de honestidad

- Una celda solo es 🟢 si un run **real** ejecutó tools **reales** y puntuó ≥8/10 **sin
  fabricar**. Nada es verde por self-report.
- Si el motor de un nicho está apagado (Docker/FreeCAD, Orthanc) o falta una key/crédito,
  la celda es ⛔ **con la razón exacta** del preflight — nunca 🔴 falso ni 🟢 inventado.
- `brain` = el cerebro que completa sin costo marginal (Opus-as-brain se corre LIVE para
  finanzas con dato FRED real; en el harness automático = qwen3:8b local). `prod-cheap` =
  qué aguanta en prod (qwen3:8b medido hoy + referencia gpt-4o-mini/deepseek del
  coupling-eval 2026-06-19).

## Divergencia de contrato detectada (para el integrador)

La receta que el motor valida HOY en `main` (`recipe_validator.py`) es la **v1 plana**:
`{schema_version, meta, model, belt{belt_ref,tool_filters}, framing, rag, keys, gates,
canvas}`. La forma F0 §4 (`{nucleo, belt_refs[], blocks[{type,zone,gridX,gridY,ref}],
canvas}`) es la **proyección del Cuarto**, distinta de lo que corre el assembler. El
harness y los templates codean contra lo que el motor REALMENTE valida. **T5 (owner del
contrato RECIPE) debe confirmar/congelar cuál es la fuente de verdad** antes del merge.
