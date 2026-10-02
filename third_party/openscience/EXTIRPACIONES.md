# EXTIRPACIONES — OpenScience dentro de Aleph

Registro línea por línea de lo que se le cortó a la pieza importada: **qué · dónde · por
qué**. Gobierna `third_party/README.md` · **Ley 6** («sólo se corta el agente y se tiñe la
piel») y **Ley 5** («cero refactor inicial»).

**Base:** `synthetic-sciences/openscience@edd5854` (v2.0.23), 4.415 archivos importados
byte a byte idénticos al origen (sha256 archivo por archivo, cero diferencias).
**Mapa que ordena estos cortes:** `~/Desktop/FASE3N-CIENCIA-ESTUDIO.md` §9.2.

**Vara sobre cada paso:** `bun run typecheck` (tsgo) después de cada grupo. Al cierre:
**typecheck verde · `bun test` 1.739 pasan / 0 fallan en 202 archivos.**

---

## 0 · Arreglo previo (no es extirpación)

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 0.1 | `.meta({ type: "object" })` sobre la unión discriminada | `backend/cli/src/tool/compute-job.ts:5,30` | La raíz del JSON Schema salía `anyOf` sin `type` y un proveedor que valida esquemas rechazaba el pedido entero con 400: la sesión moría **sin una letra de texto**, en los 4 agentes científicos, `research` incluido. Nadie lo normalizaba aguas abajo (`session/prompt.ts:1010` → `provider/transform.ts:1084`, que tiene comentado el bloque que tocaría la raíz). **Bug fix, no refactor:** el tipo inferido, las 7 ramas y la semántica quedan idénticos. |

**Cómo se midió.** Cuatro varas sobre el archivo real (no una paráfrasis): raíz
`type="object"` ✅ · 7 ramas conservadas ✅ · ya no hay `anyOf` sin `type` ✅ · semántica sin
cambios (7 casos de aceptación/rechazo, `limit` sigue defaulteando a 20) ✅.
Y **confirmado en el cable**: la bitácora de la puerta espejo pasó de
`"tools_con_raiz_anyOf": ["compute_job"]` a `[]`, con las mismas 27 tools declaradas.

---

## 1 · Superficie Atlas y los 9 verbos de cuenta

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1.1 | El módulo cliente de Atlas, vaciado de red | `src/openscience/index.ts` (1.777 → 1.106 líneas) | Órgano **mixto**: la mitad era la cuenta del fabricante, la otra mitad es higiene de entorno del kernel de Python y redacción de secretos, que 34 archivos importan. Se cortó la mitad Atlas y se conservó la de higiene verbatim. |
| 1.2 | `atlasFetch()` — el único `fetch` del módulo | `src/openscience/index.ts` (ex-324) | Era la puerta por la que salían las 20 llamadas a `app.syntheticsciences.ai`. Sin superficie Atlas no queda a quién llamar. |
| 1.3 | `sendReport()` — POST de uso a `/api/cli/usage` | `src/openscience/index.ts` (ex-910) | Contabilidad de una billetera ajena. |
| 1.4 | `startCallbackServer()` — loopback del login por navegador | `src/openscience/index.ts` (ex-495) | Capturaba el redirect del OAuth de la cuenta. |
| 1.5 | `clearAtlasCliConfig()` | `src/openscience/index.ts` (ex-409) | Limpiaba la config del CLI companion que ya no viaja. |
| 1.6 | 27 funciones de cuenta reducidas a talón sin red | `src/openscience/index.ts` | `getSession` → `null`, `isAuthenticated` → `false`, `syncServices` → `null`, `getBalance`/`getCredits`/`getTransactions`/`getBillingMode`/`listDevices`/`fetchLegacy*` → `null`, `reportUsage`/`flushPendingUsage` → no-op, `browserLogin`/`loginWithKey` → error explícito. **Se conserva la firma exportada porque 34 archivos la consultan**; abrirles el cuerpo sería refactor (Ley 5). El efecto es «esta instalación no tiene cuenta, nunca». |
| 1.7 | El banner de backend-no-productivo y `VERIFICATION_PAGE` | `src/openscience/index.ts` (ex-29..49) | Avisaban contra qué backend del fabricante estaba hablando el CLI, y la URL de aprobación de dispositivos. |
| 1.8 | El default del host gestionado, a vacío | `src/endpoints.ts:20` | Era el **único punto** donde el host cerrado del fabricante estaba horneado. Ahora `DEFAULT_MANAGED_API_BASE = ""`: sin default, la única forma de que el cliente le hable a alguien es que alguien lo declare por entorno. **Fail-closed medido**: `isAtlasProxyURL` hace `new URL("")`, tira, y ninguna URL queda clasificada como ruta gestionada. |
| 1.9 | 5 comandos de cuenta Atlas | `src/cli/cmd/connect.ts` (310 líneas, borrado) | `login` · `logout` · `status` · `sync` · `devices`. |
| 1.10 | El comando de proyecto Atlas | `src/cli/cmd/project.ts` (251 líneas, borrado) | `project` — el proyecto en el grafo hospedado del fabricante. |
| 1.11 | El comando de billetera | `src/cli/cmd/billing.ts` (73 líneas, borrado) | `wallet` — créditos prepagos del fabricante. |
| 1.12 | Los 9 verbos, desregistrados del CLI | `src/index.ts:131-141` | `login · logout · status · sync · devices · wallet · project · connect · disconnect`. **`keys` (BYOK) queda**: es la puerta por la que entra una credencial de proveedor si el cerebro de Aleph la necesita. |
| 1.13 | 4 rutas HTTP de cuenta, desmontadas y borradas | `src/server/server.ts:181,192,270` + `routes/account.ts` (224) · `routes/atlas-bridge.ts` (715) · `routes/settings/wallet.ts` (78) · `routes/settings/billing.ts` (115) | `/account/*`, `/settings/wallet`, `/settings/billing` y el puente `/api/atlas/*` que reenviaba al backend del fabricante con la llave `thk_` del usuario. |
| 1.14 | El asistente de primer arranque, sin Atlas | `src/cli/onboard.ts` | Cayeron `onboardManaged()` (login + saldo + link para cargar créditos), la opción «Atlas managed ★ recommended» del menú y la línea `Atlas account: connected/not connected` del `doctor`. El default del asistente pasó de `managed` a `byok`. |
| 1.15 | Las tools `atlas` y `atlas_record` + su broker | `src/tool/atlas.ts` (62) · `src/tool/atlas-record.ts` (77) · `src/science/atlas/broker.ts` (153) · `src/science/atlas/record.ts` (144), borrados; desregistradas en `src/tool/registry.ts:136` | El **grafo de investigación hospedado**: hablaban con `app.syntheticsciences.ai` y exigían sesión (`AtlasBrokerError: Sign in to Atlas before using the host broker`). No es ciencia local, es servicio del fabricante. |

## 2 · Dependencia `@synsci/atlas`

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 2.1 | El resolvedor del paquete | `src/openscience/atlas-package.ts` (52 líneas, borrado) | Localizaba `node_modules/@synsci/atlas` para ponerlo en el PATH del agente. |
| 2.2 | `ensureAtlasBinDir()` → siempre `null` | `src/openscience/index.ts` | Los llamadores ya trataban `null` como «atlas no disponible» y seguían: el corte usa la degradación que el propio repo dejó prevista. |
| 2.3 | `offerAtlasCli()` — el asistente ofrecía instalarlo | `src/cli/onboard.ts` (ex-134..159) | Corría `npm install -g @synsci/atlas@latest` en la máquina del usuario. |
| — | **Por qué sale** | | El paquete viene del repo **PRIVADO** `synthetic-sciences/thesis`. Se declara MIT, pero **una licencia sin fuente accesible no es un permiso que se pueda heredar con confianza**, ni un binario que se pueda auditar dentro de un `.app`. Entraba **siempre** (era `optionalDependency` sin restricción de plataforma) y traía 7 skills que no están en el repo público. |

## 3 · Proveedor `synsci` y el gate de facturación

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 3.1 | El loader del proveedor gestionado | `src/provider/provider.ts` (ex-324..351, 28 líneas) | Decidía si había llave, marcaba el sentinel `apiKey: "public"` de su demo sin costo y podaba los modelos pagos. **Era además la causa del `ERROR` de cada arranque**: sin catálogo Atlas, `database["synsci"]` no existe y el bucle de `CUSTOM_LOADERS` lo gritaba en cada boot (medido en el estudio, §8.6). |
| 3.2 | El gate de facturación, vaciado | `src/session/billing-gate.ts` (117 → 47 líneas) | Clasificaba cada llamada en `managed` (token `thk_*` o secreto sincronizado del dashboard) / `byok` / `oauth-free`, y de ahí colgaban tres decisiones: si hacía falta saldo, si el uso se reportaba al fabricante, y si la sesión se bloqueaba por créditos agotados. Ahora **todo es BYOK y nada es facturable**. Se conserva la superficie exportada porque `session/processor.ts` y `session/prompt.ts` la consultan en el camino caliente (6 llamadas); abrirles el cuerpo sería refactor. |

**Deuda declarada:** quedan ramas `providerID === "synsci"` inertes en
`provider/transform.ts`, `provider/inference.ts`, `cli/cmd/models.ts` y `acp/agent.ts`.
Sin superficie Atlas ese proveedor **no puede materializarse**, así que son código muerto;
sacarlas es refactor y se hace en la fase de cableado.

## 4 · Camino Codex

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 4.1 | El plugin entero | `src/plugin/codex.ts` (901 líneas, borrado) + desregistrado en `src/plugin/index.ts:31` | **Usaba el `client_id` del Codex CLI oficial de OpenAI** (`app_EMoamEEZ73f0CkXaXp7hrann`, verificado con `strings` contra el binario de OpenAI instalado en esta máquina): se presentaba ante OpenAI como si fuera el cliente de primera parte. Y **con sesión Atlas subía el access token Y el refresh token de ChatGPT** al backend del fabricante, sin pedir permiso (`codex.ts:727,846`). Riesgo de ToS que no es de Aleph asumir. |
| 4.2 | El proveedor virtual `openai-codex` | `src/provider/provider.ts` (ex-47..79 y ex-1418..1460) | `CODEX_MODEL_IDS`, `isCodexOAuthModel`, `codexOAuthModes` y la síntesis del proveedor con sus modelos a costo cero. Sin `CodexAuthPlugin` no hay transporte que los sirva. |
| 4.3 | Las dos excepciones de ruteo | `src/provider/provider.ts` (ex-1274 y ex-1611) | `openai-codex` se salteaba el ruteo de modo gestionado y la lista de exentos, por ser «la suscripción propia del usuario». |
| 4.4 | El camino Codex del CLI | `src/cli/cmd/auth.ts:518-684` (167 líneas) | `backendHasCodex`, `runCodexAuthFlow`, `AuthCodexCommand` (`keys signin` / `keys codex`), `disconnectCodexBackend`, `ConnectCommand`, `DisconnectCommand`. |
| 4.5 | La revocación en el backend al desloguear | `src/cli/cmd/auth.ts` (ex-556..584) | `revokeCodexOnBackend()` — un `DELETE` a `/api/keys/openai-codex` del fabricante. |
| 4.6 | Las dos entradas del selector de proveedores | `src/cli/cmd/auth.ts` | La opción «Sign in with ChatGPT (Codex)» que encabezaba la lista, y la bifurcación bajo «OpenAI» entre suscripción y llave. Queda sólo la llave. |

## 5 · CORS y CSP del fabricante

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 5.1 | El apex confiado por default, a vacío | `src/server/host-guard.ts:25` | Traía `["syntheticsciences.ai"]`: **cualquier página en un subdominio del proyecto de origen podía hablarle a este servidor local Y abrirle WebSockets** — y `OPENSCIENCE_CORS_DOMAINS` sólo **agrega** apexes, nunca reemplaza, así que no había forma de sacarlo por configuración. Loopback y `tauri://localhost` siguen confiados, que es lo único que este servidor necesita. |
| 5.2 | El `connect-src` de la CSP | `src/web/csp.ts:2` | Autorizaba `https://syntheticsciences.ai` y `https://*.syntheticsciences.ai`: era el permiso de navegador que acompañaba al CORS. Ahora `connect-src 'self' data:`. |
| 5.3 | La vara, invertida | `test/server/host-guard.test.ts:60` | La prueba afirmaba que el subdominio del fabricante **se permitía**. Ahora afirma que se **rechaza**: deja la extirpación clavada en vez de sólo borrar la prueba. |

## 6 · Marca

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 6.1 | El banner ASCII | `src/cli/logo.ts` | Decía `OPEN SCIENCE`. Ahora dice `ALEPH CIENCIA`, con la tagline «la ciencia, con el cerebro de Aleph». |
| 6.2 | El wordmark | `assets/wordmark.svg` (borrado) | Logo del proyecto de origen. |
| 6.3 | El `$schema` estampado en la config **del usuario** | `src/config/config.ts` (4 sitios) | El cliente escribía `"$schema": "https://syntheticsciences.ai/config.json"` dentro del `openscience.json` del usuario. **No se estampa ningún dominio ajeno en el archivo de nadie.** También salieron dos `.describe()` que mandaban a la documentación del fabricante. |
| 6.4 | El `$schema` de los 18 temas + el `$id` del esquema | `frontend/ui/src/theme/themes/*.json` · `desktop-theme.schema.json` | Apuntaban a `syntheticsciences.ai/desktop-theme.json`. Ahora apuntan al archivo de esquema que vive **en este mismo árbol**. |

## 7 · Atribución de red → identidad de Aleph

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 7.1 | El User-Agent de los conectores | `src/science/connectors/http.ts:18` | Era `openscience-science/1.0 (+https://syntheticsciences.ai)`. |
| 7.2 | El mailto de Crossref | `src/science/connectors/literature/crossref.ts:13` | Estaba **hardcodeado sin override**: toda consulta a Crossref quedaba atribuida al buzón del fabricante. |
| 7.3 | El mailto de OpenAlex | `src/science/connectors/literature/openalex.ts:19` | Mismo buzón como default. |
| — | **Cómo quedó** | `CONTACTO_CIENCIA` en `http.ts`, sobreescribible con `ALEPH_SCIENCE_MAILTO` | Los tres leen un solo contacto. No es cosmética: Crossref y OpenAlex dan **cola rápida** («polite pool») a quien se identifica con un buzón real, y el resto de las fuentes lo usan para avisar si el cliente se porta mal. Tiene que ser de quien opera la instalación. |

## 8 · Desatar `codesearch` / `websearch`

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 8.1 | La condición del proveedor | `src/tool/registry.ts:188` | Decía `model.providerID === "synsci" \|\| Flag.OPENSCIENCE_ENABLE_EXA`: dos herramientas quedaban **detrás del proveedor gestionado del fabricante**, o sea capacidad atada a comprarle a ellos. Con el cerebro de Aleph ese proveedor no existe, así que la condición se cae sola y las dos tools quedan gobernadas **sólo por su propia bandera**. |

## 9 · Skills

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 9.1 | `license:` → `upstream-license:` en 270 `SKILL.md` | `backend/cli/skills/*/*/SKILL.md` | El campo describía la **librería que la skill envuelve**, no la skill. Leído literalmente decía que Aleph distribuía 6 skills GPL dentro de un producto cerrado. Se verificó que no hay código copyleft vendorizado. El código no lee ese campo (cero referencias en `src/skill/`), así que el renombre no cambia comportamiento. Detalle y censo en [`NOTICE-ALEPH.md`](NOTICE-ALEPH.md). |

---

## Varas del propio repo que salieron con su órgano

Una vara que prueba un órgano amputado, o falla, o pasa **vacíamente** — que es peor,
porque queda verde sin medir nada. Se fueron con lo que probaban:

| Archivo | Líneas | Qué probaba |
|---|---|---|
| `test/plugin/codex.test.ts` + `codex-401-retry` + `codex-device-poll` + `codex-refresh` | 264 | el plugin de Codex |
| `test/openscience/atlas-resolution.test.ts` + `atlas-dependency.test.ts` | — | la resolución de `@synsci/atlas` |
| `test/science/atlas-broker.test.ts` | 298 | el broker del grafo hospedado |
| `test/server/atlas-bridge.test.ts` · `account-session.test.ts` · `settings-billing.test.ts` | — | las rutas de cuenta |
| `test/session/billing-gate.test.ts` · `test/provider/managed-routing.test.ts` | — | el gate de facturación y el ruteo gestionado |
| `test/openscience-logout` · `openscience-session` · `openscience-usage` · `openscience/session-file` · `openscience/sync-precedence` · `openscience/usage-queue-account` | 381 | sesión, sync y cola de uso de la cuenta |

Y tres varas **editadas** en vez de borradas, porque su sujeto sigue vivo:
`test/provider/provider.test.ts` (3 tests de Codex fuera), `test/tool/plan-mode.test.ts` y
`test/tool/registry.test.ts` (las tools atlas fuera),
`test/server/project-selection-routes.test.ts` (las sondas a `/api/atlas/*` fuera),
`test/config/config.test.ts` (ahora afirma que **no** se estampa dominio ajeno).

---

## Estado al cierre de la etapa 1

| Vara | Resultado |
|---|---|
| `bun run typecheck` (tsgo) | **verde** |
| `bun test` sobre el árbol extirpado | **1.739 pasan · 0 fallan · 202 archivos** |
| Boot del servidor desde fuente | **0 ERROR** — el `Provider does not exist in model list synsci` de cada arranque desapareció |
| Turno completo contra la puerta de Aleph | `aleph/brain` · `finish: stop` · sin error · **27 tools** · lazo modelo→tool→modelo cerrado |
| Esquema de `compute_job` en el cable | `tools_con_raiz_anyOf: []` (antes: `["compute_job"]`) |
| `syntheticsciences` en el log de la corrida | **0** |

---

## 10 · Inmersión NIVEL-2 · Gate 4 · Fase 4 · obra O3 (2026-08-09)

No son extirpaciones: son **tres toques de PIEL y una adición**, en el mismo registro para
que nadie tenga que adivinar qué de este árbol no vino del origen. Los tres salen de
**capturas MIRADAS** de la caminata de F3 y de esta obra, no de una opinión de diseño.

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 10.1 | **Adición**: `src/aleph.ts` (30 líneas) | `frontend/workspace/src/aleph.ts` | Un solo lugar donde se lee «¿estoy adentro de Aleph?». Los parámetros se leen **al cargar**, porque el router de esta app pierde el `search` en cuanto navega a un proyecto |
| 10.2 | El chip del servidor deja de decir un puerto | `frontend/workspace/src/pages/home.tsx` (`nombreDelServidor`) | Decía **`127.0.0.1:4096`** arriba a la derecha — se ve en las capturas de F3. Es la dirección de un proceso que Aleph levanta y apaga solo: plomería en la cara del usuario. **Corriendo suelto sigue diciendo el servidor**, que ahí sí es información |
| 10.3 | Cero pantalla intermedia: se entra al banco de trabajo | `frontend/workspace/src/pages/home.tsx` (efecto de apertura) | El usuario ya eligió «Ciencia» en la casa; adentro le pedían elegir **otra vez** (el selector de proyectos). Ley 3.8: se entra y está el banco. El directorio no se adivina: es el `cwd` con el que el pack levantó el proceso, que el propio server publica en `path.directory`. **Sólo adentro de Aleph**; suelto, esa pantalla es su casa y no se toca. Y el botón de volver al selector **queda**: un científico con dos proyectos lo necesita, y quitarlo sería construir dominio (ley 0) |
| 10.4 | El tema cruza el borde de origen | `frontend/workspace/public/openscience-theme-preload.js` | Esta UI se sirve desde otro origen, así que su `localStorage` es otro: no podía enterarse del tema de Aleph, caía en `"system"` y seguía al SO. Y Aleph es **oscuro por defecto**, no `auto`. Medido con captura: **marco oscuro de la casa, lienzo claro del stack** — dos pantallas pegadas. Ésa era la «pantalla-sobre-pantalla» de la caminata, y la causa no era el layout: era el tema |

**Medición de cierre** (`qa/verify_inmersion_nivel2.mjs`, contra el producto real, las dos
direcciones del tema): casa oscura `rgb(11,11,12)` ⇄ lienzo `rgb(19,16,16)`; casa clara
`rgb(244,244,245)` ⇄ lienzo `rgb(248,247,247)`. **Cero localhost** en lo que el usuario lee,
**cero marca del origen**, cero errores de consola.

**Lo que NO se tocó, y va a la TANDA DE CONVERGENCIA:** el copy del composer sigue diciendo
`ask anything… "generate API documentation"` / `"help me debug this issue"` en un banco de
trabajo científico. Es la deuda 3 de la caminata; el plan la manda a la convergencia final,
no a esta fase.
