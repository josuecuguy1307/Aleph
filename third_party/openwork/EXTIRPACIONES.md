# OpenWork — extirpaciones para Aleph Oficina

Base auditada: `different-ai/openwork@fc8b43b530b468026760c5da4e13dbb9c2fd78a0`.
Esta lista describe los cortes sobre el import MIT; `/ee` no se importó.

| Corte | Rutas / evidencia | Resultado |
|---|---|---|
| Den, cuenta y control-plane | `apps/app/src/app/cloud/**`, `apps/app/src/react-app/domains/cloud/**`, `packages/connect-link/**`, `packages/enterprise-mcp-*` | Fuera el login, handoff, org, enlace remoto y OAuth propietario. El servidor conserva sólo adaptadores locales que responden “disabled”; no hacen red. |
| Sobre-amputación revertida — módulo MIT fuera de `/ee`, importado por `providers.tsx:9` | `apps/app/src/react-app/domains/cloud/connect-link-provider.tsx` | Restaurado byte-idéntico desde el clon testigo (`SHA-256 39bde72d…049bc72f`). El módulo conserva su UI y llama a los puentes `connectLinkVerify`/`connectLinkAccept`; la costura remota ya está neutralizada mínimamente en `apps/desktop/electron/main.mjs:1718-1722`, que devuelve `disabled` sin red. La tarjeta de confirmación muestra ese estado; no hay fallo mudo. |
| Catálogo de capacidades propietario | `apps/server/src/opencode-plugins/openwork-capabilities-knowledge*`, `openwork-extensions-preview*`, `openwork-provider-adapters*`, y su inclusión en `openwork-runtime-config.ts` | No se inyecta `search_capabilities`/`execute_capability`, ni se conserva su marca en el prompt. |
| Telemetría | `apps/app/src/app/lib/analytics-key.ts`, `den-telemetry.ts`; `analytics.ts` reemplazado por inspector local | Fuera la clave PostHog horneada y cualquier envío de analítica. |
| Suscripción / proveedor gestionado | `domains/cloud/openwork-models-promo.ts`, vistas de cloud/account/providers y `managed-provider-auth` original | Sin tarjeta Subscribe ni proveedor de OpenWork; el modelo se define por el runtime de Aleph. |
| Updater y descargas propietarias | `apps/desktop/electron/updater.mjs`, estado/vista de updates | El updater original salió. La integración de OfficeCLI fija por entorno update y auto-install apagados. |
| Correo y servicios de cuenta | `packages/email/**`, `packages/docs/cloud/**`, rutas cloud-MCP y plugins cloud | No hay sender propietario ni marketplace remoto. |

Las referencias históricas de tests/documentación que permanecen fuera de los caminos
ejecutables se consideran deuda de limpieza del body; no se ejecutan ni se empaquetan
por esta importación. La prueba de frontera se hace sobre los artefactos y rutas activas.

**Regla de cirugía (A.3, 2026-08-09):** toda extirpación deja el árbol
compilando. Un extirpado vivo es parte obligatoria de la vara; se neutraliza su
costura remota, nunca se deja un import roto.

## Revisión A.4–A.6 — amputación por costuras

- **Restauración:** se restauró el cierre de **47 módulos MIT** que el
  resolvedor encontró en la UI (los 46 del dictamen más
  `connect-confirm-dialog`, revelado al restaurar el proveedor). Sus digests
  del testigo están en `SOBRE-AMPUTACION-RESTORED.sha256`; los que requerían
  una costura de Aleph se verificaron byte-idénticos antes de aplicar el corte.
  El resolvedor de `apps/` + `packages/` queda en **0 imports locales ausentes**.
- **Den / arranque:** `apps/app/src/react-app/domains/cloud/den-auth-provider.tsx:112-126`
  conserva el contexto que consumen los componentes, pero lo fija en
  `signed_out`, sin refresh, handoff, redirect ni diálogo en frío. Es el
  gatillo —no el módulo— que muere.
- **Telemetría:** `apps/app/src/app/lib/den-telemetry.ts:53-58,78-81` vacía
  localmente y descarta eventos; no queda `fetch` de telemetría.
- **Cuenta / control-plane:** los puentes Electron de connect-link ya estaban
  fail-closed en `apps/desktop/electron/main.mjs:1718-1722`. La única salida
  directa de la pantalla de organización se cerró en
  `domains/cloud/join-organization-dialog.tsx:48-53`: rechaza localmente con
  causa `disabled`, sin request. `apps/server/src/cloud-mcp-health.ts` retiene
  la API de diagnóstico, pero reporta catálogo ausente sin crear cliente ni red.
- **Puertas de UI:** `settings-page.tsx:190-242` ya no registra Updates ni
  pestañas Cloud; `settings-route.tsx:301-305` redirige
  `/settings/updates`, `/settings/cloud-account` y
  `/settings/cloud-providers` a la configuración general. El catálogo gestionado
  queda oculto por `openwork-models-promo.ts:75-83` (siempre false).
- **Raíz mínima adicional:** `constants.json` es el único dato de raíz que
  requieren server y desktop; contiene exclusivamente `opencodeVersion` del
  testigo MIT. No incorpora raíz upstream ni `/ee`.

Los dos módulos MIT de servidor que el arranque reveló
(`agent-context-cloud-probe.ts`, `enterprise-den-origin.ts`) volvieron para
resolver el grafo; el catálogo remoto sigue representado por la costura local
`cloud-mcp-health.ts`. Tres utilidades de test/compatibilidad restantes se
mantienen sin credenciales ni red (`analytics-key` devuelve vacío,
`den-signin-routing` y `remote-workspace` son puras).

## Costuras A.6.a (2026-08-10) — la cara medida, no supuesta

El Parcial 6 dio A por técnica (`pnpm run build` verde, `/health` 200, UI 200)
pero no llegó a mirar la pantalla. Mirada con un navegador headless por CDP, la
forma que EMBARCA —la UI servida por el propio server vía `OPENWORK_WEB_ROOT`,
que es como la sirve el pack— abría en «Welcome to OpenWork · Sign in to
OpenWork Cloud». Dos costuras, las dos por seams del propio repo:

- **Base same-origin cuando el server sirve la UI.**
  `apps/app/src/app/lib/openwork-server.ts:1078-1089`. Sin `VITE_OPENWORK_URL`
  —o sea, siempre fuera de dev— el cliente caía en
  `DEFAULT_OPENWORK_SERVER_PORT` (8787) y hablaba con un puerto de nadie:
  medido, la app NUNCA pidió `/workspaces`, así que `workspaces.length` valía 0.
  Ahora, si hay `__OPENWORK_BOOTSTRAP__` y no es desktop, la base es
  `window.location.origin`. El camino gateway (`/ee`) no se toca: retorna antes.
- **El landing de cuenta desregistrado.**
  `use-workspace-route-state.ts:800-805` (el redirect, ELIMINADO) y
  `app-root.tsx:32-37` (la ruta, redirigida a `/session` como ya se hace con
  Updates y Cloud). Es la ley 2.bis en su forma literal: cuentas, logins y
  landings del stack heredado no existen. Un install sin workspaces es un
  estado vacío que se pinta («No tasks yet.»), jamás un pedido de cuenta.

Evidencia: `reports/fase6-oficina/A6-degradado-landing-cloud.png` (antes) y
`reports/fase6-oficina/A6-cuerpo-vivo-prod.png` (después, forma de producción:
un solo proceso sirviendo API + UI, cero requests fallidas).

**Marca todavía en pantalla, para la obra E:** «Sign in» ×2, «Sync with
OpenWork Cloud», `/openwork-mark.svg`, «Using the free starter model · Get
frontier models with no API keys» y el modelo `big-pickle` en el selector — este
último es además la ley 12 sin cumplir: ahí tiene que decir «Cerebro de Aleph».

## El motor: descarga en build → binario embebido (2026-08-10)

**Causa: local-first y reproducibilidad.** `apps/desktop/scripts/prepare-sidecar.mjs`
bajaba el motor `opencode` de GitHub releases en tiempo de build
(`:236` arma la URL, `:299` la baja con `curl`, `:287` con `Invoke-WebRequest` en Windows).
Un build que sale a la red no es reproducible —el asset de un tag puede reemplazarse— y no
es local. El bloque queda **a la vista pero inalcanzable** detrás de
`ALEPH_DESCARGA_EN_BUILD = false` (`:272-274`), a propósito: así la diferencia con el
origen se lee de un vistazo y el día que haya una morada de artefactos se re-cablea en vez
de reescribirse.

En su lugar, `shouldDownloadOpencode` **falla visible** con la ruta esperada
(`third_party/opencode/bin/opencode-darwin-arm64`) y remite a
`third_party/opencode/IMPORT.md`. No hay caída al camino de red «por las dudas»: ese
camino es justo el que se cortó.

El motor viaja verificado: tag `v1.17.11` (el exacto de `constants.json`), SHA-256
contrastado **contra el digest que publica la API de GitHub**, y su MIT preservado.

**Auto-update del motor, apagado por su costura oficial.** El binario trae actualización
viva (`opencode upgrade [target]` y la variable `OPENCODE_DISABLE_AUTOUPDATE`). El pack lo
arranca con `OPENCODE_DISABLE_AUTOUPDATE=1`, igual que OfficeCLI con
`OFFICECLI_SKIP_UPDATE=1`. Un motor que se actualiza solo deja de ser el que el manifiesto
describe, y su SHA pasaría a mentir.

## Costura 2026-08-14 — el copy que enseñaba a desconectar el cerebro de la casa

Un cambio, una clave de i18n, diez locales:
`apps/app/src/i18n/locales/*.ts` → `providers.still_connected_suffix`.

**Qué decía.** Es el sufijo del mensaje que sale al apretar `Disconnect` sobre un
proveedor que el motor no toma de `auth` sino de la config —o sea, sobre **el cerebro de
Aleph**, que es `source: "config"` (medido: el botón queda habilitado para él porque
`settings-route.tsx:2175` sólo exige `source !== "env"`)—:

> «…, but the worker still reports it as connected. Clear any remaining API key or OAuth
> credentials and restart the worker to fully disconnect.»

Es un instructivo para insistir hasta desconectar el modelo del workspace. Dentro de
Aleph, eso es una instrucción activa en contra del producto: la ley 12 dice que a un stack
no se le consigue modelo, se le enchufa el nuestro.

**Qué dice ahora.** El hecho, sin el instructivo: «…, but this workspace configures it, so
it stays connected.» (y su equivalente en los otros nueve idiomas). No nombra a Aleph
—esta rama del árbol importado no tiene por qué conocernos— y no le dice a nadie cómo
defenderse de su propia casa.

**Lo que NO se tocó, a propósito:** los botones `Connect provider` y `Disconnect` siguen
donde estaban. No es olvido: se estandarizan en la tanda de convergencia de la cara, junto
con el Base URL editable de Educación y los 23 proveedores de Finanzas, que son el mismo
problema tres veces. El cerco a `POST /workspace/:id/runtime-config/disabled-providers`
tampoco se abrió acá.
