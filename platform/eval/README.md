# platform/eval — model-watch harness (PARAMETRIZABLE)

Runner del squad Agent Eval. Toma un **task-set** (instancia por nicho, vive en
`catalog/evals/<nicho>-tasks/`) y una **lista de modelos** (config) y produce la tabla
modelo×tarea: **completó** (checker mecánico) · **calidad 0-2** (juez humano contra la
rúbrica PRE-escrita `catalog/evals/<nicho>-rubrica.md`) · **tokens** · **wall**.

```
.venv/bin/python runner.py --config config.yaml            # corrida completa
.venv/bin/python runner.py --models qwen3-32b --tasks T1   # re-corrida puntual (Reviewer)
```

**Cero hardcodeo (clase PARAMETRIZABLE del ledger):** `runner.py` no contiene ningún
nombre de modelo, nicho, tarea ni prompt de dominio. Para evaluar otro modelo u otro
nicho se edita SOLO `config.yaml` (o se pasa `--models/--tasks`). El Reviewer valida
esto apuntando el runner a un modelo distinto sin tocar código.

**Carriles:** lista ordenada en config — `litellm` (:4000, aliases del gateway) primero;
si su health no responde, `groq` directo. Las API keys se referencian por **nombre de
env var** (`api_key_env`) y se leen del entorno del proceso (cargar `infra/.env` con
`set -a; source infra/.env; set +a` antes de correr). **Jamás se imprimen ni se
loguean.** El campo `modelo_servido` del resultado detecta sustituciones silenciosas
por fallback del router LiteLLM.

**Rate limits (free tier):** las celdas corren SERIALIZADAS; ante 429 el runner hace
backoff exponencial y el wall reportado es el real (disciplina de la misión 0018).

**Anti-gaming (EVAL-FRAMEWORK-SPEC):** la rúbrica se escribe ANTES de correr y no se
ajusta después; el checker decide "completó" mecánicamente; si un modelo chico empata
al grande se reporta tal cual; el Reviewer re-corre ≥2 celdas.

Setup: `uv venv .venv && uv pip install -p .venv/bin/python pandas openpyxl statsmodels matplotlib nbformat nbclient ipykernel pyyaml requests`

Salida: `runs/<timestamp>/results.{json,md}` + un workdir por celda con los artifacts
del modelo (auditable por el juez y el Reviewer). Resultados de corrida = dato del
flywheel (`platform/flywheel/`).
