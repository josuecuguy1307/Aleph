# Extirpaciones — doc.haus dentro de Aleph

Registro de cortes obligatorios. Los archivos fuente y el clon testigo permanecen para
comparación; este documento describe la cirugía que habilita el workspace Legal.

| Corte | Superficie | Motivo |
|---|---|---|
| Vertex/Google y BYOK | `dochaus/opencode.json`, `apps/web/src/components/Onboarding.tsx`, `Settings.tsx`, API/provider helpers | El único cerebro es Aleph por el borde OpenAI-compatible. No se exponen claves, OAuth, ADC, cloud ni endpoint local. |
| Dos MCPs ajenos | `dochaus/opencode.json` | Sale el MCP Python/Deno con red y escritura de `node_modules`; sale el MCP remoto CourtListener duplicado. Persiste el tool legal directo `case-law`. |
| Probes cloud | `services/ingest/src/host.ts`, rutas `/host/*` | Sólo existían para onboarding GCP/AWS/BYOK. |
| Puertos horneados y launcher autónomo | `start.sh`, web/ingest config | El pack F4 entrega el puerto público; el launcher elige los dos internos y apaga el grupo completo. |

No se extirpan la cola pending→accept/reject, la vista redlined, la cita verificada, la
allowlist jurídica ni los tools de oficio: son la anatomía Legal protegida por Ley 0.

## §11 · Piel de Aleph (Gate 4 · F6 · convergencia inline, 2026-08-10)

La ley 6 permite exactamente dos cirugías sobre una pieza importada: amputarle el agente y
**teñirle la piel**. Ésta es la segunda, y queda registrada acá para que nadie tenga que
adivinar qué de este árbol no vino del origen.

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 1 | La letra de la casa, vendorizada adentro del lienzo | `apps/web/src/aleph-fonts.css` (nuevo, 8 `@font-face`) · `apps/web/src/fonts/outfit-*.woff2` (los mismos dos woff2 que sirven las ~24 pantallas de Aleph) · `apps/web/src/main.tsx` (los tres `@fontsource/space-grotesk` salen, entra `./aleph-fonts.css`) | Ley 3: si el usuario adivina de qué repo vino, se adaptó mal. El lienzo vive en OTRO ORIGEN, así que no puede linkear `vendor/fonts.css` de la casa: la letra se vendoriza, con los `unicode-range` intactos y CERO red. |
| 2 | Las familias apuntan a Outfit | `apps/web/src/styles.css` (`--font-sans`, `--font-display`) | Space Grotesk era la letra del proyecto de origen. Mono y serif quedan como stacks de sistema, igual que en la casa. |
| 3 | El esquema de la casa cruza el borde de origen | `apps/web/public/aleph-theme-preload.js` (nuevo) · `apps/web/index.html` (lo carga antes del bundle; `color-scheme` pasa a `light dark`) · `apps/web/src/styles.css` (`:root[data-aleph-scheme="dark"]`) | `legal.html:230` MANDABA `aleph_scheme` y de este lado no lo leía nadie: el lienzo era claro SIEMPRE dentro de una casa que por default es oscura, y la costura se veía a simple vista. Es el paso 3b del precedente de Ciencia, que Legal no había replicado. |
| 4 | El nombre en la pestaña | `apps/web/index.html` (`<title>`) | Marca del proyecto de origen en superficie. |

**El criterio, explícito:** no se buscó que el lienzo tenga los hex de Aleph — eso sería teñir
el oficio por dentro. Se busca que caiga del MISMO LADO de la línea claro/oscuro que la casa
(así se mide la inmersión: por luminancia, no por igualdad de color). El verde profundo del
oficio sigue siendo el acento; sólo se levanta para leerse sobre fondo oscuro.

**Lo que NO se tocó:** la jerga del oficio (redline, matter, NDA, playbook — ley 11), los
nombres internos de API y paquetes, las fuentes de datos, el motor, y la cola
proposal → pending → accept que es la anatomía de Legal.

## §6 · Las nueve puertas de credencial (Gate 4 · tanda modelos · 2026-08-14)

`internalPlugins()` (`packages/opencode/src/plugin/index.ts`) registraba **nueve plugins de
auth**, y cada uno publicaba su método en `GET /provider/auth` — un endpoint alcanzable
**sin llave** desde el puerto público del workspace, porque el motor arranca con
`OPENCODE_SERVER_PASSWORD` sin declarar y él mismo lo avisa en su log. Medido contra la
`.app` instalada `5173e055…`: `openai · github-copilot · gitlab · poe · azure ·
digitalocean · xai · cloudflare-workers-ai · cloudflare-ai-gateway`.

| # | Qué | Dónde | Por qué |
|---|---|---|---|
| 6.1 | Los nueve, desregistrados | `src/plugin/index.ts` — `internalPlugins()` devuelve `[]`, y salen sus 8 imports | Desde que el pack declara `enabled_providers: ["aleph"]`, **ninguno de esos proveedores puede servir un modelo**: el motor los descarta en `provider.ts:1471-1475`. Lo único que quedaba era la superficie — puertas que escriben credenciales en disco para modelos que ya no se pueden usar. |
| 6.2 | El plugin de Codex, **borrado** | `src/plugin/openai/codex.ts` (901 líneas) + `test/plugin/codex.test.ts` | Traía **horneado el `client_id` del Codex CLI oficial de OpenAI** — `app_EMoamEEZ73f0CkXaXp7hrann`, el mismo que Ciencia extirpó con acta (`openscience/EXTIRPACIONES.md §4`): se presentaba ante OpenAI como el cliente de primera parte, y con sesión Atlas subía el access token Y el refresh token de ChatGPT al backend del fabricante sin pedir permiso. Riesgo de ToS que no es de Aleph asumir. |

**El identificador literal vive SÓLO en esta tabla y en ningún `.ts`**, a propósito: así
`grep -rl app_EMoamEEZ… --include='*.ts'` sobre el árbol de Legal sigue siendo una vara que
da 0 y no un falso positivo sobre su propia documentación.

**El cerebro no entra por acá.** Entra por `provider.aleph` en la config que escribe el
pack, que no necesita ningún plugin. Por eso la lista queda vacía y el workspace no pierde
nada: sale superficie, no capacidad.
