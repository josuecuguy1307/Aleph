# Migraciones de puppet_ai (T8-infra)

Desde 2026-06-21 el schema se gestiona con **migraciones versionadas**, no aplicando
`schema.sql` entero. `migrations/` es la **fuente de verdad**; `schema.sql` queda como
referencia legible del estado total.

## Reglas

- Cada cambio = un archivo nuevo `migrations/NNNN_nombre.sql` (prefijo numérico creciente).
- Una migración aplicada **no se edita jamás** (el runner detecta el *drift* por checksum
  y avisa). Si te equivocaste, corregí con una migración nueva.
- `0001_baseline.sql` está **CONGELADO** = el schema v0 al adoptar el sistema. Es idempotente
  (`CREATE … IF NOT EXISTS`), así que aplicarlo sobre la base ya poblada de persona usuaria es un no-op.
- Cada migración corre dentro de **su propia transacción**: entra entera + se registra en
  `schema_migrations`, o no entra nada.

## Comandos

```bash
python platform/db/migrate.py            # aplica las pendientes
python platform/db/migrate.py status     # aplicadas / pendientes / drift
python platform/db/migrate.py --db otra  # apuntar a otra base (tests)
```

`schema_migrations(version, name, checksum, applied_at)` lleva el registro.

## Migraciones actuales

| Versión | Archivo | Qué |
|---|---|---|
| 0001 | `0001_baseline.sql` | schema v0 congelado (users, puppets, runs, outputs, historial, keys, instrumentation_logs, held_actions) |
| 0002 | `0002_job_queue.sql` | cola de trabajo durable `job_queue` (worker pool de T8) |
| 0003 | `0003_agent_memories.sql` | memoria del AGENTE por `puppet_id` (Step 2 · A3) |
| 0004 | `0004_held_action_provenance.sql` | proveniencia de held-actions |
| 0005 | `0005_shared_memories.sql` | memoria COMPARTIDA por composición (Step 2 · B2) |
| 0006 | `0006_knowledge.sql` | corpus RAG (docs+chunks) por composición (Step 2 · C1) |
| 0007 | `0007_chats.sql` | conversaciones persistentes (UX · A1) |
| 0008 | `0008_held_turn_text.sql` | texto del turno retenido |
| 0009 | `0009_instructions.sql` | instrucciones persistentes del dueño (UX · B5) |
| 0010 | `0010_account_memories.sql` | memoria de CUENTA por `owner_id`=users(id), la lee todo agente del dueño (Orden 2 · Sistema 2) |
| 0011 | `0011_account_deletion.sql` | soft-delete de cuenta: `users.deleted_at` + `users.purge_after` (fecha exacta de purga día-30) — ticket 2 pre-launch |
| 0018 | `0018_chat_turn_idempotency.sql` | Sala: idempotencia por `chat_messages.client_turn_id` + índice único parcial por chat/turno/rol |
| 0019 | `0019_multiagente_saltos.sql` | MULTIAGENTE: el salto de cadena enlazado POR CAMPO — `runs.{parent_run_id,hop_index,hop_latency_ms,modo}` + `idx_runs_parent`. Ver `docs/multiagente.md` §4 |

> **El cliente (SQLite) NO usa `migrations/`.** Su schema vive en `schema_sqlite.sql` (DBs
> vírgenes) + `sqlite_db._MIGRACIONES_CLIENTE` (DBs ya desplegadas), versionado por
> `PRAGMA user_version`. Una migración que toque una tabla del cliente tiene que ir a los
> DOS lados, y `platform/db/verify_multiagente_saltos.py` es el molde de cómo se prueba
> que los dos caminos dan la misma tabla.

## Backups

`backup.py` hace `pg_dump -Fc` a `backups/` con rotación; restore con `--restore`.
Los `*.dump` están gitignored (pueden traer datos de usuarios). Ver `app/infra/README.md`.
