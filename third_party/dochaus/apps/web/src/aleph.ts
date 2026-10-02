/**
 * aleph.ts — LO QUE ESTA UI SABE DE LA CASA QUE LA EMBEBE.
 *
 * Este archivo NO es del proyecto de origen: lo agrega Aleph. Es la tercera copia del mismo
 * patrón —ya existen `third_party/openscience/frontend/workspace/src/aleph.ts` y
 * `third_party/vibetrading/frontend/src/aleph.ts`— y se escribe igual a propósito: la regla
 * «¿estoy adentro de Aleph?» tiene que leerse igual en los tres o se desincronizan.
 *
 * ⚠️ SE LEE UNA SOLA VEZ, AL CARGAR, y eso es load-bearing: la casa pasa los parámetros en
 * la URL del `<iframe>`, y en cuanto el router de esta app navega, el `search` se pierde.
 * Leerlos tarde daría «no estoy adentro de Aleph» justo después del primer click.
 */
const AL_CARGAR = typeof location !== "undefined" ? new URLSearchParams(location.search) : new URLSearchParams()

/** El workspace de la casa que embebe esta UI (`legal`), o `""` si corre suelta. */
export const alephWorkspace = AL_CARGAR.get("aleph_ws") ?? ""

/** ¿Corriendo adentro de Aleph? */
export const dentroDeAleph = alephWorkspace.length > 0
