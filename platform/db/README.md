# platform/db — Fundación de datos (FASE 0 · Database & Data)

> Conecta al **Postgres EXISTENTE de persona usuaria** (`postgresql@17`, `:5432`), base
> lógica **`puppet_ai`**. No se inventó un servidor nuevo: se usa la instancia
> local que ya corría (`brew services` → `postgresql@17 started`).

## Archivos
| Archivo | Qué hace |
|---|---|
| `schema.sql` | DDL de las 7 tablas. La receta vive como JSONB parametrizable; nada hardcodeado por nicho. |
| `db.py` | Conexión psycopg2 + cifrado BYOK (Fernet) at-rest. |
| `init_db.py` | Crea la base `puppet_ai` si no existe y aplica `schema.sql` (idempotente). |
| `verify_phase0.py` | **Evidencia** del gate: corre contra el Postgres real e imprime output. |
| `secrets/enc.key` | Clave Fernet local (auto-generada, `0600`, gitignored vía `**/secrets/**`). |

## Correr
```bash
cd platform/db
python3 init_db.py          # crea base + schema
python3 verify_phase0.py    # prueba (revierte sus filas con ROLLBACK)
python3 verify_phase0.py --keep   # deja las filas de prueba para inspección
```

## Conexión
- `db.py` lee de env con defaults locales: `PG_HOST=127.0.0.1`, `PG_PORT=5432`,
  `PG_USER=$USER`, `PG_DB=puppet_ai`.
- **Trust local**: NO se setea `PG_PASSWORD` para localhost (así está el Postgres
  de persona usuaria). El `PG_PASSWORD` de `infra/.env` es del stack legacy team-bby (`agent`),
  no de esta instancia — no lo cargues al entorno o romperás el trust auth.

## Las 7 tablas
`users` · `puppets` (recetas, `config` JSONB) · `runs` · `outputs` · `historial`
· `keys` (BYOK cifradas) · `instrumentation_logs` (**el moat**).

## El moat: `instrumentation_logs`
Una fila liga por `run_id` los **5 campos exactos del loop**:
1. `intent` — qué pidió el usuario
2. `belt` (JSONB) — la receta usada (snapshot de `config.json` al correr)
3. `trayectoria` (JSONB) — secuencia model-calls + tool-calls, cada uno con `latency_ms` y `error`
4. `senal` (JSONB) — explícita (`👍/👎`) + implícita (`saved/edited/abandoned`)
5. `costo` (JSONB) — tokens

El stream del espacio (`platform/flywheel/events_replay.py`, `platform/assembler/session.py`)
es la fuente de `trayectoria` (cada `tool_call_finished` trae `wall_s` y `gate_decision`).

## BYOK
`keys.ciphertext` es un token **Fernet** (AES-128-CBC + HMAC). La clave de cifrado
vive **fuera de la DB** (env `PUPPET_DB_ENC_KEY` o `secrets/enc.key`). El plaintext
nunca toca Postgres — verificado en `verify_phase0.py` §5.

> v0 — 2026-06-15 — FASE 0, ejecutado en persona por el Supervisor (régimen: el org no spawnea asientos todavía).
