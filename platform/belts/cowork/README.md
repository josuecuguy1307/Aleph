# Belt COWORK — mitad GMAIL (draft + send-gate, turnkey, multi-usuario)

> Esta carpeta cubre **solo Gmail** del belt de oficina: **deja correos en borrador** y
> **NUNCA manda sin OK** (send-gate). **Notion lo lleva otra terminal** — acá no se toca.
> Verificado E2E SIN cuenta real (2026-06-16).

## Qué hay acá

> **Convención de path (decisión A/T7):** `${PUPPET_BELTS}` = **`<root>/product/belts`** — el
> BELTS-ROOT único del que cuelgan TODOS los belts (lo fija el executor de prod; el assembler lo
> respeta). Cada belt referencia su server relativo a ese root: programación →
> `${PUPPET_BELTS}/gaps/script_runner_mcp.py` · cowork → `${PUPPET_BELTS}/cowork/gmail_draft_server.py`.
> (El server cowork vive en `product/belts/cowork/`; el test y los fixtures siguen en
> `platform/belts/cowork/`.)

| Archivo | Qué es |
|---|---|
| `gmail_draft_server.py` | MCP server (stdio) de Gmail. Lee `GMAIL_TOKEN` (access-token OAuth). `create_draft` (idempotente, **no envía**) + `send_email` (existe para que el **send-gate lo detenga**). |
| `fixtures/gmail_stub.py` | Stub HTTP local de la API de Gmail (formas reales + **auth real**). Detector del invariante *construir≠inyectar*. |
| `test_cowork_gmail_e2e.py` | Verificación E2E (gate · inyección · draft · idempotencia · run real OSS). |
| `../../../catalog/templates/cowork/belt-cowork-gmail.mcp.json` | El belt runnable (declara el server + su `base_matrix`). |
| `../../../catalog/templates/cowork/base-matrix-cowork-gmail.json` | Declara `create_draft` como escritura segura (auto-ejecuta). |
| `../../../platform/assembler/fixtures/e2e/cowork-gmail.recipe.json` | La receta de verificación. |

## Familia de conector

**Gmail = Familia 3 (OAuth Connect).** El usuario toca *“Conectar Gmail”*; el
**credential-broker (B4)** guarda/renueva el OAuth **por end-user**. El server consume el
access-token; es agnóstico a cómo se obtuvo. **Nunca** la cuenta del dev ni una global.

> **Regla de oro de UX:** *show the work, hide the machinery.*

## Cómo entra la credencial (per-usuario)

**NO se pega en `infra/.env` ni se hardcodea.** En un run, el runtime arma un `byok_resolver`
**ligado al `user_id`** (`credential_broker.make_user_resolver`) y `assemble_and_run` lo
inyecta: `keys.gmail.byok_ref` → cleartext → `child_env["GMAIL_TOKEN"]` del **subprocess del
server** (vía el alias `gmail → GMAIL_TOKEN` en `recipe_assembler._PROVIDER_ENV_ALIASES`).
El cleartext **solo** vive en el env del subprocess; nunca en el record/log/HTTP.

### Invariante crítico: **construir ≠ inyectar**

La credencial tiene que **llegar al server que la usa**, no solo guardarse. El stub lo hace
cumplir: exige el `Authorization: Bearer` correcto y devuelve **401** si no llega. La
verificación asserta `stub.gmail_bearer_seen == <token>` *después* del run.

## El send-gate (HELD) y la deuda de approve

- `create_draft` **prepara** el borrador (escritura segura → auto-ejecuta). **No envía.**
- `send_email` matchea `SEND_HINTS` → el **enforcer lo fuerza a `needs_ok`** aunque la receta
  apague el gate. En un run sin aprobación, `send_email` **nunca** corre → el correo **no sale**
  (HELD). En producción la receta **no lista** `send_email` (SEND-GATE-FIRST).
- **Deuda viva:** el *approve-by-HTTP* todavía no ejecuta la acción retenida (prioridad #1
  post-Fase-4). **No asumas que “aprobar” manda.** Hoy el contrato es: el gate **sostiene**.

## Idempotencia (re-correr NO duplica)

`create_draft` compara (to, subject) contra los drafts; no crea otro si ya está.

## base_matrix turnkey (para el path `:8080`)

El router pasa `base_matrix=None`. Para que `create_draft` no caiga a `needs_ok` por
fail-closed, el belt **declara** su matriz de tools-seguras en `_meta.base_matrix` y
**`assemble_and_run` la auto-carga**. "Belt nuevo = belt + su base_matrix", cero wiring por
call-site. El enforcer fuerza money/send por encima.

## Ir a producción (live) — sin recodear

Por defecto el server pega a `https://gmail.googleapis.com`. La verificación usa un stub vía
`GMAIL_API_BASE`. **Para ir live: no seteés esa var** y asegurate de que el OAuth del usuario
esté conectado. Cero cambios de código.

## Re-correr la verificación

```bash
python3 platform/belts/cowork/test_cowork_gmail_e2e.py
# 15 passed → DONE: borrador real, send HELD, idempotente, inyección confirmada.
```
