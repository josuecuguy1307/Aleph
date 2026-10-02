# CONTRATO AUTH / SESSION v1 — ❄️ CONGELADO (F0 §4.5 · owner T6)

> **Estado: CONGELADO el 2026-06-21 por T6 (auth/identidad).**
> Confirmado contra el código REAL (PASO 0), no contra una idea. Toda llamada `/v1`
> que toca data de un usuario codea contra ESTE contrato. **Nadie lo cambia sin avisar
> al integrador** (regla F0 §5). Cambios incompatibles ⇒ nueva versión + migración,
> jamás edición silenciosa de v1.

Fuente de verdad de "¿quién es el dueño de esta request y qué puede tocar?". La lógica
pura vive en **`product/backend/app/phase1/authz.py`** (owner T6); el resto del backend
autoriza LLAMANDO ahí, no reimplementando el parseo del token ni la comparación de dueño.

---

## 0. La invariante madre (§4.5)

> **Toda llamada `/v1` con identidad lleva una SESIÓN → `user_id`. `user_id` scopea TODO
> (puppets, spaces, runs, secrets). Nadie lee/escribe data de otro.**

Un recurso **sin dueño** (run anónimo, space de `inspect`/demo) no es data privada de
nadie → su lectura es abierta. La regla operativa es **owner-gated cuando hay dueño**.

---

## 1. La SESIÓN — token opaco, stateless (Fernet)

`repo.mint_session(user_id) -> str` emite un token que liga al `user_id`
**cifrado + autenticado** (Fernet, mismo secreto maestro del org). **No hay tabla de
sesiones**: sobrevive reinicios mientras el secreto maestro no cambie.

```
token  =  Fernet( "alephsess:v1:" + user_id )      # base64 url-safe canónico
```

`repo.session_owner(token) -> user_id | None`:
- token **ausente / forjado / manipulado / no-canónico** → `None` (la base64 se
  re-codifica y compara: un `<token>+"x"` NO pasa).
- token de OTRO usuario → su `user_id` real (el HMAC de Fernet lo garantiza; no se
  puede fabricar uno para un `user_id` ajeno sin el secreto maestro).

### Cómo se obtiene una sesión
| Endpoint | Qué hace | Devuelve |
|---|---|---|
| `POST /v1/auth/register` | crea cuenta (email + password, hash **scrypt**) | user + **`session_token`** |
| `POST /v1/auth/login` | verifica password (scrypt) | user + **`session_token`** |
| `POST /v1/users/{id}/password` | cambia password (verifica la actual) | user |

`password_hash` **JAMÁS** sale al cliente (`repo._public_user` lo quita). Formato:
`scrypt$<salt_hex>$<dk_hex>` (n=16384,r=8,p=1). Cuenta "legacy passwordless"
(sin hash) → `register` la **reclama** seteando password; `login` sin password =
get-or-create por email (sólo dev/herramientas internas).

---

## 2. TRANSPORTE del token

1. **Por defecto:** header `Authorization: Bearer <session_token>`.
2. **EXCEPCIÓN — streaming SSE:** el `EventSource` del browser **NO puede** setear
   headers. Para los `GET` de streaming/descarga-directa se acepta TAMBIÉN
   `?token=<session_token>` (query). El header gana si están ambos.
   `authz.pick_token(authorization, query_token)` unifica.

> **Para T1/T2/T4 (consumidores):** mandá el `session_token` en `Authorization: Bearer`
> en todo fetch a `/v1`. Para abrir el `EventSource` de `/v1/spaces/{id}/stream` de un
> space **con dueño**, agregá `?token=<session_token>` a la URL. Un space anónimo
> (recon/inspect/demo) NO necesita token.

---

## 3. La DECISIÓN — `authz.decide(expected_owner, token)`

```
expected_owner is None  → ("ok", owner_or_None)   # recurso anónimo → LECTURA ABIERTA
token inválido          → ("no_session", None)     # → HTTP 401
owner != expected       → ("forbidden", owner)     # → HTTP 403
owner == expected       → ("ok", owner)            # → adelante
```

Dos guardas en el router, **a propósito distintas**:

- **`_authorize(claimed_user_id, authorization)`** — IDENTIDAD OBLIGATORIA. `None ⇒ deny`.
  Para recursos que SIEMPRE tienen dueño o que exigen identidad sí o sí
  (keys, puppets propios, download de output, approve de acción retenida).
  Sin token → **401**; token de otro → **403**.
- **`_authorize_resource(expected_owner, authorization, query_token=None)`** —
  owner-gated **cuando hay dueño**; anónimo → abierto. Para spaces, instrument y
  artifacts de sesión. Acepta el `?token=` del transporte SSE.

---

## 4. Matriz de ENFORCEMENT (estado CONGELADO)

| Endpoint | Regla | Dueño resuelto por |
|---|---|---|
| `POST /v1/auth/{register,login}` | público (entrada de sesión) | — |
| `POST /v1/users/{id}/password` | `_authorize(id)` | path id |
| `GET /v1/users/{id}/{runs,outputs,puppets,keys,export}` | `_authorize(id)` | path id |
| `GET /v1/users/{id}/rag/{k}[/{name}]` (+POST/DELETE) | `_authorize(id)` | path id |
| `POST /v1/keys` · `DELETE /v1/users/{id}/keys/{prov}` | `_authorize(user_id)` | body/path |
| `GET /v1/outputs/{id}/download` | `_authorize(owner)` (None⇒deny) | run del output |
| `POST /v1/puppets` | `_authorize(owner_id)` | body owner_id |
| **`PUT /v1/puppets/{id}/config`** | `_authorize(owner)` — **cerrado (era IDOR)** | `repo.puppet_owner` |
| `POST /v1/puppets/run` · `/run/stream` | `_authorize(user_id)` si viene | body user_id |
| `POST /v1/runs` | `_authorize(user_id)` si viene | body user_id |
| **`POST /v1/runs/{id}/instrument`** | `_authorize_resource` — **cerrado** | `repo.run_owner` |
| `POST /v1/runs/{id}/approve` | `_authorize(held.user_id)` (None⇒deny) | held_action |
| **`GET /v1/spaces/{id}/events`** | `_authorize_resource` (+`?token=`) — **cerrado** | `repo.space_owner` |
| **`GET /v1/spaces/{id}/stream`** | `_authorize_resource` (+`?token=`) — **cerrado** | `repo.space_owner` |
| **`GET /v1/sessions/{sid}/artifacts[*]`** | `_authorize_resource` (+`?token=` en download) — **cerrado** | `artifact_store.get_owner` |
| **`POST /v1/sessions/{sid}/artifacts`** | `_authorize(user_id)` + claim-on-first-create | body + sid owner |
| `PUT/POST /v1/sessions/{sid}/artifacts/{aid}[/revert]` | `_authorize_resource` — **cerrado** | `artifact_store.get_owner` |
| `POST /v1/classify-turn` · `/obra-caption` · `/transcribe` · `/artifacts/classify-action` | `_authorize(user_id)` si viene | body user_id |
| `POST /v1/recipes/validate` · `/forge` | público (sin identidad: no toca data) | — |

`space_owner(space_id)` = el `user_id` del run **con dueño** más reciente que emitió ese
space (vía `runs.space_id`); `None` si ninguno → space anónimo (`inspect`/demo) → abierto.

---

## 5. EL VAULT — secretos cifrados at-rest (BYOK + OAuth)

**Un solo store cifrado por usuario:** la tabla **`keys`** (Postgres).
- `keys.ciphertext BYTEA` = token **Fernet** (AES-128-CBC + HMAC). El plaintext **NUNCA**
  toca Postgres ni un log ni una respuesta HTTP. `UNIQUE(user_id, provider)`.
- `repo.upsert_key / get_key / list_keys / delete_key`. `list_keys` devuelve SOLO
  `provider + last4` (jamás el secreto). `get_key` descifra **sólo en memoria**, sólo
  para inyectar al `child_env` del MCP server (vía `credential_broker`, ligado al
  `user_id` del run — un run de A jamás resuelve la credencial de B).
- **BYOK** (API keys del usuario): `POST /v1/keys` → `upsert_key`.
- **OAuth tokens** (Caso A): `GET /v1/connectors/{name}/callback` valida un `state`
  Fernet (CSRF, liga `{user_id, provider, exp}`) y guarda el `access_token` por el
  MISMO camino → `upsert_key(user_id, provider, access_token)`. El `client_secret` y el
  token jamás vuelven al browser.

**Secreto maestro (único):** `PUPPET_DB_ENC_KEY` (env) **o** el keyfile auto-generado
`platform/db/secrets/enc.key` (gitignored). El MISMO Fernet cifra: keys (BYOK+OAuth),
el token de sesión (§1) y el `state` OAuth. El `CredentialVault`
(`platform/gates/vault.py`, archivo `vault.enc`) es un mecanismo SEPARADO de inyección
runtime (namespace plano, no per-user) — **no** es el store multi-tenant; la verdad
per-user es la tabla `keys`.

---

## 6. Invariantes NO-NEGOCIABLES (no cambian en v1)

1. **`user_id` scopea TODO** — ningún endpoint con identidad sirve data sin verificar
   `session.owner` contra el dueño del recurso (matriz §4).
2. **Token tamper-proof** — sesión y state OAuth son Fernet (HMAC). Forjar/manipular →
   rechazo (401/callback rechazado). No hay autorización por id-del-cliente.
3. **Secretos sólo cifrados at-rest** — BYOK y OAuth en `keys.ciphertext` (Fernet).
   Plaintext jamás a DB/log/HTTP. Respuestas exponen a lo sumo `last4`.
4. **`password_hash` jamás sale** del backend; passwords sólo como hash scrypt.
5. **Owner-gated cuando hay dueño** — recurso con dueño ⇒ sólo el dueño; recurso
   anónimo ⇒ abierto (no rompe recon/inspect/demo). El default de un recurso de
   identidad-obligatoria es **deny** (`_authorize`, None⇒deny).

---

## 7. VERIFICADO en vivo (DONE-BAR §4.5)

`product/backend/app/phase1/test_t6_multitenancy.py` — **18 checks offline + 16 live, verdes**:
- dos usuarios reales (signup), cada uno su key cifrada at-rest; A no lee las keys de B
  (**403**), sin token (**401**), A ve su `last4` y NUNCA el secreto.
- IDOR de escritura cerrado: `PUT /puppets/{de-otro}/config` → 401 / 403 / 200(dueño).
- fuga de datos cerrada: `GET /spaces/{de-otro}/events` → 401 / 403 / 200(dueño).
- crypto round-trip + token forjado rechazado + claim-on-first-create de artifacts.

No-regresión: `test_authz_idor`, `test_credential_broker_roundtrip` verdes.

---

## 8. Follow-ups (FUERA del freeze v1, registrados honestos)

- **OAuth refresh_token:** `exchange_code` hoy guarda `access_token`; el refresh para
  tokens de vida corta es una extensión (mismo `keys`, provider derivado).
- **`/v1/inspect` con dueño:** hoy los spaces de recon son anónimos (abiertos). Cuando
  el Cuarto ligue el recon a un usuario, `inspect` debe crear el run con `user_id` →
  el space queda owner-gated automáticamente (ya soportado por `space_owner`).
- **Rotación del secreto maestro:** re-cifrado de `keys` + invalidación de sesiones
  (operación de ops, no de código).

---

_v1 — ❄️ CONGELADO 2026-06-21 por T6. Base: `authz.py` + `repo.py` (sesión/keys/scrypt) +
`platform/connectors/oauth_flow.py` (OAuth) + `platform/db/db.py` (Fernet) + `schema.sql`.
Reference impl + DONE-BAR: `app/phase1/{authz,test_t6_multitenancy}.py`._

---

## 9. ENMIENDA ADITIVA 2026-07-16 — borrado de cuenta (ticket 2 · sprint pre-launch)

**Qué cambia (aditivo, sin romper §1-§7):** la validez de una sesión pasa de
`token descifra` a `token descifra ∧ cuenta NO borrada`. `repo.session_owner` sigue PURO
(stateless, sin DB) — el check `users.deleted_at` vive en el **middleware HTTP de
`main.py`** (`_block_deleted_accounts`), el único choke point que cubre todos los
routers (Bearer y `?token=` del SSE). Cuenta en soft-delete → **401
`account_deleted`** con `purge_at`; exentos `/v1/auth/login` (puerta de reactivación)
y `/v1/auth/register`.

Semántica nueva (migración 0011: `users.deleted_at`, `users.purge_after`):
- `DELETE /v1/account` (owner de la sesión) → acceso muere YA + OAuth se **revoca al
  instante** (best-effort `oauth.revoke_url` + delete local base/companions + barrido de
  `synth_belts/u/<slug>`) + outbox del mail con la fecha EXACTA de purga.
- Re-login exitoso en ventana → **reactivación intacta** (`reactivated:true`). La puerta
  legacy sin password JAMÁS reactiva una cuenta con password; `register` no reclama
  emails de cuentas congeladas.
- `purge_after` vencido → purga TOTAL (`account_deletion.purge_user`): deletes explícitos
  de lo que el CASCADE no cubre (runs/job_queue SET NULL; billing sin FK) + disco
  (rag/, run_outputs/, espacios/, artifacts/, synth_belts/). DONE-BAR: cero filas
  huérfanas (`test_account_deletion.py` + `qa/verify_borrado_cuenta.py`).
- El broker (`make_user_resolver`) no resuelve credenciales de cuentas en soft-delete
  (cubre runs en vuelo al momento del pedido).

Costo: 1 SELECT por PK por request autenticada (fail-open ante infra caída — sin DB los
endpoints de datos fallan solos).
