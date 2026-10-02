# Credential Broker por end-user — Tier A (F4-B4)

> Backend & API · 2026-06-16. El plumbing del broker de credenciales POR USUARIO:
> cómo la credencial del end-user entra, se guarda cifrada, y se inyecta cifrada al
> belt en un run — ligada a `user_id`, con aislamiento. La UI/D2 será la cara; esto es
> la cañería. **held ≠ wired:** el OAuth de claude.ai es del operador; el motor de
> PRODUCTO usa la credencial PROPIA de cada end-user, nunca la sesión del operador.

## 1. Qué es Tier A
Conectores que requieren **credencial por usuario**: Gmail, Google Calendar, Google
Drive, Microsoft 365, Slack — y los BYOK del catálogo (Exa, Context7, Alpha Vantage,
FRED, Hugging Face, ...). Cada end-user trae lo suyo; el motor no comparte una
credencial global.

## 2. El round-trip (lo que CORRE de verdad, ver evidencia §6)

```
  usuario guarda credencial
        │  POST /v1/keys  {user_id, provider, secret}
        ▼
  repo.upsert_key ──► encrypt_secret(Fernet) ──► keys.ciphertext (BYTEA)   [cifrado at-rest]
        │                                         UNIQUE(user_id, provider)
        │  (la API responde SOLO metadatos: provider + last4; jamás el secreto)
        ▼
  receta v1:  keys.<provider>.byok_ref = "keys:<provider>"   [§3.4: por referencia, jamás valor]
        │
        ▼  POST /v1/puppets/run  {recipe, user_id, prompt}
  router arma el resolver del broker LIGADO al user_id del run:
        credential_broker.make_user_resolver(user_id, get_conn)
        │
        ▼  executor.run_puppet_e2e(..., byok_resolver=resolver)
  assembler._resolve_keys(recipe.keys, resolver):
        byok_ref "keys:<provider>" → resolver(ref):
            parse → (user_id_del_run, provider)
            repo.get_key(conn, user_id, provider) → decrypt_secret(Fernet)  [solo en memoria]
        │  provider → cleartext
        ▼
  assembler arma child_env:  _provider_env_vars(provider) → {EXA_API_KEY|HF_TOKEN|...: cleartext}
        │  base_env → _expand_server_cfg expande ${VAR} del belt → MCPServer(env=child_env)
        ▼
  el server MCP del belt arranca con la credencial en SU subprocess env y la usa server-side.
  El LLM nunca ve el valor (llama tools por nombre). Logs/run-record: solo NOMBRES.
```

## 3. Contrato del `byok_ref` (aislamiento por usuario)
- **Forma canónica (la que valida `recipe_validator` §3.4):** `byok_ref = "keys:<provider>"`.
  El `user_id` **NO** viaja en el ref — la receta es portable/user-agnóstica. El dueño se
  liga afuera, en `make_user_resolver(user_id)`: el run sabe de quién es la credencial.
- **Aislamiento:** un resolver construido para el usuario A solo lee `keys` de A. Si un ref
  nombrara explícitamente otro usuario (`keys:user:<B>/exa`), el broker lo **rechaza**
  (devuelve `""`). Run anónimo (sin `user_id`) → no resuelve credenciales de nadie.
- **Dos users → dos credenciales:** `UNIQUE(user_id, provider)` en la tabla + el resolver
  por-usuario garantizan que A y B con el mismo provider tengan filas y cifrados distintos.

## 4. Piezas (todas existentes; el broker es el puente que faltaba)
| Pieza | Archivo | Rol |
|---|---|---|
| Tabla cifrada | `platform/db/schema.sql` (§6 `keys`) | ciphertext Fernet at-rest, UNIQUE(user_id,provider) |
| Cifrado | `platform/db/db.py` | `encrypt_secret`/`decrypt_secret` (Fernet, key fuera de la DB) |
| Capa de datos | `product/backend/app/phase1/repo.py` | `upsert_key`/`get_key`/`list_keys`/`delete_key` |
| Endpoints | `product/backend/app/phase1/router.py` | `POST /v1/keys`, `GET /v1/users/{id}/keys` (metadata) |
| **Broker (nuevo)** | `product/backend/app/phase1/credential_broker.py` | `make_user_resolver(user_id)` → resolver ligado; `parse_byok_ref` |
| Inyección | `platform/assembler/recipe_assembler.py` | `_resolve_keys` + `_provider_env_vars` + child_env → `MCPServer(env=)` |
| Cableo prod | `router.run_puppet` | arma el resolver con el `user_id` del run y lo pasa al executor |

## 5. El flujo OAuth por end-user (diseño; la UI lo implementa)
No hace falta un flujo OAuth completo hasta que haya app registrada por proveedor. El
almacenamiento + inyección cifrada por usuario YA corre (§6). El OAuth encaja así sin
tocar el resto del plumbing:

1. **UI/D2** inicia el consent del proveedor (Google/MS/Slack) con la **app del producto**
   (client_id/secret del PRODUCTO, no del operador). Redirect URI del producto.
2. El callback recibe el `authorization_code`, lo canjea por `access_token` + `refresh_token`.
3. **El token entra por el MISMO endpoint que las API keys:** `POST /v1/keys`
   `{user_id, provider:"google", secret:<refresh_token | token JSON>}`. Se cifra at-rest
   igual que cualquier BYOK. (Para OAuth conviene guardar el `refresh_token`; el broker
   puede en el futuro canjearlo por un `access_token` fresco al resolver — ver deuda.)
4. La receta referencia `keys.google.byok_ref = "keys:google"`; el belt declara la env var
   que su server espera (`GOOGLE_APPLICATION_CREDENTIALS`, etc.) y el broker la cablea.

**Lo que la UI necesita saber (el contrato que expone el backend):**
- `POST /v1/keys` para guardar (provider + secret). Responde metadata, nunca el secreto.
- `GET /v1/users/{user_id}/keys` para listar lo conectado (provider + last4 + enc_scheme).
- Señal de fallo a media tarea: `424 byok_failure` + payload tipado (`byok.py`, screen 11)
  con `reason` (missing/invalid/expired/revoked/...) y `recoverable` → CTA "reconectar".

## 6. Evidencia ejecutada (real, no declaración)
`product/backend/app/phase1/test_credential_broker_roundtrip.py` corre contra el Postgres
`puppet_ai` real:
- **Cifrado at-rest:** SELECT crudo de `keys.ciphertext` muestra `enc_scheme=fernet-v1`,
  140 bytes, y el plaintext NO aparece en los bytes (ciphertext ≠ plaintext). Dos users →
  dos ciphertexts distintos.
- **Inyección por usuario:** run E2E real (modelo OSS gpt-oss-120b) donde el agente llama
  `cred_status()`; el server reporta `fingerprint = sha256(secretoA)[:12]` que coincide con
  el computado afuera → la credencial llegó al child_env del belt SIN exponer el valor.
  Prueba determinista (sin LLM) confirma lo mismo y el cross-user (resolver_B → cred de B).
- **Cero plaintext:** grep del secreto sobre el run record + logs/events/data → 0 hits.

## 7. Deuda sin maquillar
- **Dos stores de credenciales conviven:** `platform/gates/vault.py` (Fernet, file-based,
  single-tenant, fase previa) y la tabla `keys` (Postgres, per-user, este broker). El path
  de PRODUCTO usa `keys` + broker; `vault.py` quedó del runtime mono-usuario. **Deberían
  converger** (que el runtime lea siempre del broker per-user). No tocado en esta misión.
- **OAuth real diferido:** hoy se guarda el secreto que la UI mande; el broker NO canjea
  `refresh_token → access_token` ni refresca tokens vencidos. Cuando haya app registrada:
  agregar un paso de refresh en el resolver (o un job) que use el `refresh_token` cifrado.
- **Mapa provider→env-var es una allow-list** (`_PROVIDER_ENV_ALIASES`): cubre los conocidos
  (huggingface→HF_TOKEN, exa→EXA_API_KEY, ...) + el canónico `<PROVIDER>_API_KEY`. Un
  provider con otra convención de var hay que agregarlo ahí (o que el belt declare la var
  y el provider matchee el canónico).
- **Send sigue detrás del gate (B5):** este broker cablea LECTURA. Gmail/Slack **send** no
  se ejecutan sin el send-gate (`SEND-GATE-FIRST.md`); el broker no los habilita.
- **`get_key` abre conexión corta por lookup:** correcto para no compartir la transacción
  del run, pero N providers = N conexiones cortas por run. Aceptable hoy (recetas con 1-3
  keys); si crece, cachear el descifrado en memoria por la vida del run.
