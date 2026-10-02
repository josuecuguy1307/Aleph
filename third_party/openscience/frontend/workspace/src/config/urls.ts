/**
 * [Aleph · 2026-08-11] LAS PUERTAS HACIA EL PROVEEDOR DEL STACK, CERRADAS.
 *
 * Este archivo era, en sus palabras, «single source of truth for outbound Synthetic
 * Sciences URLs». Auditado el 2026-08-11, tenía cuatro destinos hacia su web y tres eran
 * de DINERO:
 *
 *   · `dashboardBilling` → app.syntheticsciences.ai/billing — «Plans and shared wallet»
 *   · `dashboardCli`     → app.syntheticsciences.ai/cli     — «CLI plan + wallet tab»
 *   · `dashboard`        → app.syntheticsciences.ai         — cuenta, claves, facturación
 *   · `site` / `docsThemes` / `releases` → su sitio y su changelog
 *
 * Ninguno hacía una llamada de red por su cuenta: eran botones que abrían el navegador
 * (`platform.openLink`). Pero adentro de Aleph, Ajustes › Modelos ofrecía «comprar créditos»
 * y Ajustes › General tenía una fila «Billing — Manage your subscription, wallet, and
 * invoices». El cerebro de este workspace lo pone la casa; una puerta a contratar un plan
 * de un tercero no es una función, es una fuga.
 *
 * Se van los seis destinos externos. Quedan los dos que NO salen de la máquina:
 *   · `host`      — sólo se compara contra `location.hostname` para detectar el modo hosted
 *   · `changelog` — ruta RELATIVA, servida por el propio motor local
 *
 * El código extirpado y su análisis viven en ~/Desktop/CIENCIA-PAGOS-EXTIRPADO/.
 */

/** Bare deployed web host, used for dev-host detection (no scheme). */
export const HOST = "syntheticsciences.ai"

export const URLS = {
  /** Bare host (scheme-less) — matched against `location.hostname`. No se navega a él. */
  host: HOST,
  /** Same-origin changelog feed consumed by the highlights context. */
  changelog: "/settings/updates/releases",
  /** Favicon LOCAL para las notificaciones. Antes se descargaba del sitio del stack, que es
   *  una petición de red a su host cada vez que la app notifica algo. */
  favicon: "/atlas-favicon.svg",
} as const
