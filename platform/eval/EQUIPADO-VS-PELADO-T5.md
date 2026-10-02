# EQUIPADO vs PELADO — T5 (Varianza presupuesto-vs-real, convención F/U)

> Corrida CARRIL LOCAL — squad Agent Eval (rnd-eval-constructor, OPUS).
> Fecha: 2026-06-12. Modelo único: **qwen3:8b** (Ollama, `http://127.0.0.1:11434/v1`,
> Q4_K_M, 8.2B, ctx servido = 4096). Anti-gaming EVAL-FRAMEWORK-SPEC §2/§3: la rúbrica
> congelada (`catalog/evals/finanzas-rubrica.md`) se aplica TAL CUAL; si el equipado
> pierde o empata se reporta. Esta corrida NO depende del TPM de Groq (que bloqueó 0018).

## Tarea elegida y por qué

**T5 — la más corta del task-set.** Fixture `T5-presupuesto-vs-real-2026.xlsx`: 2 hojas
(Presupuesto, Real) × 10 líneas de P&L × 5 meses (Ene-May 2026). Deliverable: `varianzas.xlsx`
con hoja "Varianzas" (fórmulas vivas cruzando hojas, convención F/U, formato condicional,
bridge de las 3 mayores varianzas YTD). Es el deliverable de menor cardinalidad del set
(T1 ~520 filas sucias, T2 panel 60×8 + regresión, T3 comps, T4 notebook end-to-end) — el
candidato correcto para un modelo local lento (~80-115s/turno, confirmado: ~120-300s/turno
real con `<think>` a ctx 4096).

## Setup (parametrizable, sin tocar lógica de dominio)

- **EQUIPADO**: runner existente `platform/eval/runner.py` con belt excel + framing
  (tools `list_files/read_file/write_file/run_python/task_done`, system prompt de analista,
  fixture copiado al sandbox). Carril `ollama` + modelo `qwen3-8b` agregados SOLO en
  `config.yaml`. Timeout de request por turno subido a **300s** (≥180s, REGLA OPERATIVA
  06-12) vía nuevo `limits.request_timeout` (config); `wall_seconds` 480→1500 para dar aire
  a ~8-14 turnos lentos. Único cambio de código: cablear `request_timeout` desde el config
  (el valor estaba hardcodeado a 180; default preservado para corridas previas).
- **PELADO**: `platform/eval/pelado_runner.py` — MISMO modelo, MISMO prompt de tarea, SIN
  `tools`. El input NO se oculta: el xlsx se renderiza como TEXTO y se inyecta inline (§2:
  "que falle por capacidad, no por privarlo del input"). Una sola llamada de chat. Mismo
  checker mecánico (`checkers/t5.py`) decide COMPLETÓ.

## Scores

| Config | COMPLETÓ (checker) | Calidad 0-2 (rúbrica) | Turnos | Wall s | Tokens in/out | Declaró done | Artifact |
|---|---|---|---|---|---|---|---|
| **EQUIPADO** (belt excel + framing) | **NO** | **N/A** | 8 | 1586.4 | 15300 / 15327 | no | `varianzas.xlsx` nunca escrito |
| **PELADO** (mismo modelo, sin tools) | **NO** | **N/A** | 1 (1 call) | 285.5 | 1371 / 3000 | n/a | imposible (sin tools); solo texto, 784 chars |

**Calidad = N/A en AMBOS por Capa 0 de la rúbrica congelada:** "el artifact existe, abre y
pasa el checker… si no completó, calidad = N/A (no se califica prosa sobre un artifact que no
existe)". Ninguna de las dos configs produjo `varianzas.xlsx`, así que NINGUNA entra a la
tabla 0-2 de los tres ejes (rigor·verificabilidad·formato). No se inventan puntos.

### Checker mecánico (idéntico para ambos)
```
artifact=false  hoja_varianzas=false  formulas_cruzadas=0  cond_format=0  etiquetas_FU=0  bridge=false
```
Gate de COMPLETÓ: `hoja_varianzas AND formulas_cruzadas>=5 AND cond_format>=1` → ambos fallan en el primer término.

## Transcripts crudos (resumen)

**EQUIPADO** (`runs/20260612-043012/qwen3-8b/T5/`): el agente tuvo el belt completo y el
fixture en el sandbox. Consumió los **8 turnos** y el **wall completo (1586s, tocó el tope
de 1500s)** generando **15.327 tokens de salida** — casi todo `<think>` a ctx 4096 — sin
emitir nunca una tool call que escribiera el archivo y **sin llamar `task_done`**. El workdir
final contiene SOLO el fixture de entrada; cero `varianzas.xlsx`, cero `._snippet.py` con
resultado. Patrón de falla: razonamiento en loop que nunca aterriza en acción (planifica el
workbook en prosa pero no ejecuta `write_file`/`run_python`). El ctx de 4096 probablemente
truncó historial entre turnos, reforzando el loop.

**PELADO** (`runs/PELADO-T5-20260612-045659/qwen3-8b/T5/pelado_response.md`): una sola
llamada, 285s, agotó el presupuesto de **3000 tokens** pero solo **784 chars** quedaron como
`content` visible (el resto fue `<think>` consumido por el endpoint). La respuesta empieza a
describir la estructura correcta del workbook —3 hojas, columnas Línea/Tipo/meses/YTD/F-U,
intención de "Varianzas mensuales (Real - Presupuesto)"— pero **se corta a mitad de frase**
en "Varianzas mensuales (ej. Ene):" antes de dar una sola fórmula concreta, etiqueta F/U,
regla de formato condicional o el bridge. No produjo —ni podía producir— un .xlsx binario.

## Brecha de capacidad — ¿el pelado pudo siquiera ejecutar?

**No.** El pelado, por construcción (§2), no tiene sistema de archivos ni ejecución: su techo
absoluto es texto. Aun dándole el input completo, no puede materializar el deliverable
binario que el checker exige (`varianzas.xlsx` con fórmulas vivas serializadas + formato
condicional que openpyxl pueda leer). El equipado SÍ tenía el poder de ejecutar
(`write_file`/`run_python` con openpyxl disponible) — la capacidad estaba presente; lo que
faltó fue que el modelo de 8B la **usara**. Es decir: el equipo no fue el cuello de botella
en el pelado (techo de modalidad) ni el habilitador efectivo en el equipado (cognición
insuficiente para cerrar el loop a esta escala/cuantización).

## Veredicto honesto (anti-gaming)

**EMPATE EN CERO: 0-0, ambos COMPLETÓ=NO, ambos calidad N/A.** El belt excel + framing NO
abrió distancia medible sobre el modelo pelado en esta celda, porque **qwen3:8b (Q4_K_M, ctx
4096) es demasiado débil para cerrar T5 incluso equipado** — quema todo el presupuesto en
`<think>` sin aterrizar la acción. Esto se reporta tal cual, sin maquillar: el equipado NO
ganó.

Matices que NO cambian el score pero importan para el flywheel:
1. La **brecha de modalidad** es real y a favor del equipado en lo cualitativo: el pelado
   tiene techo de texto y ni siquiera terminó de describir una fórmula; el equipado al menos
   tenía el camino mecánico para entregar. Pero "potencial de entregar" no es "entregó", y la
   rúbrica congelada solo puntúa lo segundo.
2. La falla del equipado es de **cognición del modelo base**, no del harness ni del belt: el
   runner copió el fixture, expuso las tools y el python sandbox con openpyxl; el modelo
   simplemente no ejecutó. Un modelo agéntico más capaz en el MISMO belt probablemente
   completa (hipótesis para la corrida Groq cuando el TPM lo permita).
3. **Lectura para Curation/Eval:** qwen3:8b local NO es candidato de roster para tareas
   finanzas-xlsx agénticas tal como está (sin subir ctx ni domar el `<think>`). Candidato a
   kill-list para este nicho/escala salvo recalibración (num_ctx mayor, presupuesto de
   pensamiento acotado, o tarea más simple).

## Artifacts (auditable)
- EQUIPADO: `platform/eval/runs/20260612-043012/` (results.json/.md + workdir)
- PELADO: `platform/eval/runs/PELADO-T5-20260612-045659/` (results.json + pelado_response.md + pelado_prompt.txt)
- Referencia de grading (top-3 YTD): Ventas −8739.79 (U) · Nómina +988.38 (U) · Viajes +174.89 (U)
- Config y runners: `platform/eval/config.yaml`, `runner.py`, `pelado_runner.py`
