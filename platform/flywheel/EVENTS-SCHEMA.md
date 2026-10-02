# Events Schema v0 — el evento del espacio (PRODUCT-V2-DESIGN)

> El stream de eventos del **espacio vivo** de Puppet AI.
> Contrato de diseño (PRODUCT-V2-DESIGN): **"cada evento se persiste ANTES de
> emitirse; reconexión con `Last-Event-ID` = replay exacto"**.
> Formato: **JSONL append-only**. Una línea = un evento del espacio.
> Implementación: `events_replay.py` (esta carpeta).

---

## Por qué esta lib

`platform/assembler/session.py` (la fuente REAL) ya hace **persist-before-emit**:
`_emit()` appendea a `events.jsonl` **antes** de llamar al callback. Pero usa
`time.time()` como pseudo-identidad y **no** garantiza:

- un **id monotónico contiguo** (sin huecos) que un cliente pueda usar como
  `Last-Event-ID`;
- **atomicidad** de la asignación de id entre **writers concurrentes**;
- un **replay exacto** verificable.

`events_replay.py` aporta esas tres garantías para que la reconexión con
`Last-Event-ID = N` devuelva **exactamente** los eventos `{N+1 … max}`.

---

## El evento — campos

| Campo | Tipo | Requerido | Quién lo asigna | Descripción |
|---|---|---|---|---|
| `id` | integer | SI | **la lib** | Identidad monotónica **contigua** (1, 2, 3, …). Append-only, sin huecos, sin duplicados. Es el `Last-Event-ID` del replay. El caller **no** debe fijarlo (se rechaza). |
| `ts` | number | SI | lib (si falta) | Timestamp epoch en segundos (`time.time()`). El caller puede traerlo; si no, lo pone la lib. |
| `type` | string | SI | caller | Tipo del evento. **Debe** pertenecer a la taxonomía (abajo). |
| `space_id` | string | SI | caller | Identidad del **espacio** (la sesión viva). Equivale al `session_id` de `session.py`. |
| `payload` | object | NO | caller | Datos específicos del tipo. Forma libre, serializable a JSON. Por convención, los datos que `session.py` pone "planos" en el evento (p.ej. `turn`, `call_id`, `tool`, `result`) van acá. |

Cualquier otra clave plana adicional se conserva tal cual (compat con la forma
"plana" de `session.py`). El único campo **reservado** que la lib se reserva
asignar es `id`.

### Reglas del schema

1. **Append-only**: nunca se reescribe ni se borra una línea. El historial es
   inmutable.
2. **Persist-before-emit**: `append()` escribe a disco **con `fsync`** y recién
   entonces retorna. Cuando retorna, el evento ya es durable; el caller puede
   emitirlo con seguridad. Si el emit posterior falla, el evento **ya** quedó.
3. **Ids sin huecos**: la secuencia es `1..max_id` contigua. `verify_integrity`
   detecta cualquier hueco.
4. **Ids sin duplicados** y **estrictamente crecientes**: dos writers concurrentes
   nunca obtienen el mismo id (lock exclusivo de archivo alrededor de
   *leer-último-id + escribir*).
5. **`type` validado** contra `EVENT_TYPES`; un tipo desconocido se rechaza en
   `append()` y se marca como corrupción en `verify_integrity()`.
6. **`space_id` obligatorio** y string no vacío.

---

## Taxonomía de `type` — alineada 1:1 con `session.py` (REAL) + V2

Los 8 primeros son **exactamente** los que `platform/assembler/session.py` emite
hoy vía `_emit(...)` (verificado en la fuente). Los 2 últimos son las adiciones
que V2 suma según este mandato.

| `type` | Origen | `payload` típico | Significado |
|---|---|---|---|
| `belt_ready` | session.py | `{servers, servers_skipped, tools}` | El cinturón MCP del agente quedó montado y vivo. |
| `turn_started` | session.py | `{turn, global_turn, reused_belt}` | Arrancó un turno del loop de tool-use. |
| `tool_call_started` | session.py | `{call_id, tool, args}` | El modelo invocó una tool; aún no terminó. |
| `tool_call_finished` | session.py | `{call_id, tool, result, status, executed, gate_decision, gate_action?, wall_s?, causa?, origen?, reintentable?, timeout_s?, vencio_el_reloj?}` | La tool terminó: `status` distingue `ok` de `error`; `executed:false` marca rechazos pre-ejecución; y la causa tipada firma los fallos. |
| `gate_waiting` | session.py (`gate_*`) | `{payload}` | El gate decidió `NEEDS_OK`: el espacio **pausa** esperando aprobación humana. |
| `gate_resolved` | session.py (`gate_*`) | `{approved, timed_out}` | El humano resolvió el gate (OK/NO) o expiró el deadline. |
| `final` | session.py · recipe_assembler.py | `{answer, turns_truncated?, model_final?, ok?, run_id?, degraded?}` | Respuesta final del turno del agente. **El run e2e lo enriquece** con `model_final`/`ok`/`run_id` para que un cliente que mira SOLO el SSE reporte honesto sin un POST bloqueante. |
| `closed` | session.py · executor.py | `{ok, model_final?, run_id?, error?, degraded?, answer?, turns?, trajectory_steps?, instrumentation_log_id?, held_actions?}` | El espacio se cerró. **TERMINAL HONESTO del run** (Gap #3): emitido por el executor en el `finally` → sale en TODOS los caminos (éxito, gate fail-closed, excepción), llevando el veredicto real del run. `iter_sse_events` corta limpio acá. |
| `artifact_created` | **V2** | `{artifact_id, kind, path?, uri?, bytes?, mime?}` | El agente produjo un artefacto persistente (archivo, reporte, imagen…). |
| `equipment_changed` | **V2** | `{added?, removed?, belt_version?, tools?}` | El equipamiento del espacio cambió en vivo (se sumó/quitó una tool o cinturón). |

> Nota de mapeo: el `gate_waiting`/`gate_resolved` de `session.py` cubre la familia
> `gate_*` mencionada en el mandato. Si V2 desglosa más estados de gate, se agregan
> a `EVENT_TYPES` aquí y la lib los acepta sin cambios de lógica.

### Contrato de error de `tool_call_finished`

Cuando `status="error"`, el evento lleva `causa` del vocabulario existente,
`origen` (`modelo`, `conector` o `aleph`) y `reintentable`. `detalle` es texto
humano seguro; `timeout_s` sólo aparece si el reloj fue medido y
`vencio_el_reloj` sólo si se conoce. El `role:"tool"` equivalente conserva su
texto humano y termina con una línea estable:

```text
[causa=<causa> origen=<modelo|conector|aleph> reintentable=<si|no>]
```

`gate_decision` es el nombre canónico. `gate_action` se emite con el mismo valor
solamente como compatibilidad de consumidores vivos —incluida Sala y
`method_harness`— y es **legacy**; se elimina cuando ambos migren a
`gate_decision`. `wall_s` es monotónico alrededor de una call realmente ejecutada:
no se emite para una call que no se midió.

---

## Ejemplo de un stream válido (3 eventos de un espacio)

```json
{"id": 1, "ts": 1781240000.10, "type": "belt_ready", "space_id": "sp_7f3a", "payload": {"servers": ["echo"], "tools": ["echo"]}}
{"id": 2, "ts": 1781240000.42, "type": "turn_started", "space_id": "sp_7f3a", "payload": {"turn": 1, "global_turn": 1, "reused_belt": false}}
{"id": 3, "ts": 1781240001.07, "type": "tool_call_started", "space_id": "sp_7f3a", "payload": {"call_id": "2fa5e5340f31", "tool": "echo", "args": "{\"text\": \"hola\"}"}}
```

Reconexión con `Last-Event-ID = 2` ⟹ `read_since(2)` ⟹ **exactamente** el evento
`id=3` (y los que sigan). Ni uno de más, ni uno de menos.

---

## API de `events_replay.py`

```python
from events_replay import EventLog, verify_integrity, EVENT_TYPES

log = EventLog("space-sp_7f3a.jsonl")

# append: valida -> asigna id monotónico atómico -> persiste con fsync ANTES de volver
ev = log.append({"type": "turn_started", "space_id": "sp_7f3a",
                 "payload": {"turn": 1}})
# ev["id"] == 1 (asignado por la lib)

# replay exacto desde un Last-Event-ID
faltantes = log.read_since(2)        # -> [{id:3,...}, {id:4,...}, ...]
todo      = log.read_all()
ultimo    = log.last_id()            # 0 si vacío

# auditoría
rep = verify_integrity("space-sp_7f3a.jsonl")
assert rep.ok                        # False si hay huecos/duplicados/corrupción/desorden
```

### Garantías de concurrencia

`append()` toma un **lock exclusivo de archivo** (`fcntl.flock` en POSIX,
`msvcrt.locking` en Windows) alrededor de *leer-el-último-id + escribir-la-línea*.
Por eso, **dos writers concurrentes** (threads o procesos) nunca:

- obtienen el mismo `id` (no hay duplicados),
- intercalan escrituras a media línea (no hay corrupción),
- saltan un número (no hay huecos).

El id se deriva del **estado persistido** (la cola del archivo), no de un contador
en memoria — por eso funciona también entre **procesos** distintos.

---

## Archivos

| Archivo | Propósito |
|---|---|
| `events_replay.py` | La lib: `EventLog`, `verify_integrity`. |
| `EVENTS-SCHEMA.md` | Este documento — define el evento del espacio. |
| `demo_replay.py` | Demo ejecutable: 20 eventos / 2 writers concurrentes / corte+replay / corrupción detectada. |
| `REPLAY-DEMO-OUTPUT.txt` | Output crudo de la demo. |

---

> v0 — 2026-06-11 — Squad Database (eng-database-constructor), Puppet AI · platform/flywheel

---

## Migración `gate_action` → `gate_decision` — PLAN, no ejecución

> **[GATE 3 · fase 3 · O5]** Sólo documentación. **No se toca una línea de código en esta
> obra**, y el motivo está medido abajo: matar `gate_action` hoy se lleva puesto el
> anti-grift de la Sala, que es lo único que impide que un turno sin evidencia se pinte
> como verificado.

### Dónde estamos (medido sobre main `a60edcf`)

`gate_decision` es el nombre **sellado**; `gate_action` es el legacy. La migración es
**aditiva y está a mitad**: el emisor manda **los dos, con el mismo valor**
(`recipe_assembler.py:3277-3278`), y los consumidores nuevos ya prefieren el sellado.

| capa | archivos con `gate_action` | archivos con `gate_decision` | estado |
|---|---|---|---|
| `product/app/design` | 4 | 3 | la Sala ya lee `gate_decision` primero (`sala.html:3773`), con `gate_action` de respaldo |
| `product/backend` | 2 | 3 | `instrumentation.py:113-116` lee los cuatro orígenes en orden, sellado primero |
| `platform/assembler` | 4 | 4 | el emisor manda los dos |
| `platform/inspection` · `flywheel` · `gates` | 0 | 0 | no lo tocan |

### Por qué NO se puede borrar hoy

1. **Los eventos y records YA PERSISTIDOS sólo traen `gate_action`.** `events.jsonl` es
   append-only y se replaya (`events_replay.py`): un consumidor que deje de leer el
   legacy deja de entender la historia, no sólo los eventos nuevos.
2. **El anti-grift de la Sala depende de él como respaldo.** `cuentaComoGrounding`
   (`sala.html:4196-4206`) usa `gate_action` **sólo** cuando el registro no trae
   `executed` — o sea, exactamente para los registros viejos del punto 1. Sacarlo hace
   que un record viejo no pueda decir si su tool corrió, y una tool que no se sabe si
   corrió **no puede contar como evidencia**: el badge se caería a «sin herramientas» en
   toda la historia.
3. **`gate_action` no tiene un consumidor único que se pueda cortar.** Está en 10
   archivos de producción repartidos en tres capas.

### El orden, y qué se rompe en cada paso

| # | quién migra | qué hace | qué se rompe si se saltea |
|---|---|---|---|
| 1 | `events_replay.py` | **normalizar al leer**: si el evento trae `gate_action` y no `gate_decision`, poblar el sellado. Un solo lugar traduce la historia. | sin esto, cada consumidor tiene que conocer los dos nombres para siempre |
| 2 | consumidores de backend | borrar el respaldo `gate_action` — ya no hace falta, el paso 1 se lo garantiza | leen `None` en todo evento viejo |
| 3 | `sala.html` | borrar el respaldo en `cuentaComoGrounding` y en `:3773` | **el anti-grift deja de poder juzgar los records viejos** — el caso del punto 2 de arriba |
| 4 | `recipe_assembler.py` | dejar de emitir `gate_action` | los consumidores que quedaron sin migrar rompen en silencio |
| 5 | `EVENTS-SCHEMA.md` | declarar `gate_action` retirado, con la fecha | — |

**El paso 1 es el que hace baratos a los demás.** Sin él, los pasos 2-4 son cuatro
migraciones independientes que hay que sincronizar; con él, cada consumidor se migra
solo y sin coordinación.

**Condición de arranque:** una vara que corra un replay de `events.jsonl` REAL —no un
fixture— y afirme que la trayectoria sale idéntica antes y después del paso 1. Sin esa
medición, el paso 1 es una traducción que nadie verificó sobre la historia que dice
traducir.
