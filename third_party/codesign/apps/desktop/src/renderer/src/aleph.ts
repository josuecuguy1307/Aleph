/**
 * aleph.ts — LO QUE ESTA UI SABE DE LA CASA QUE LA EMBEBE.
 *
 * No es del proyecto de origen: lo agrega Aleph. Cuarta copia del mismo patrón —ya existen
 * en `openscience`, `vibetrading` y `dochaus`— y se escribe igual a propósito: la regla
 * «¿estoy adentro de Aleph?» tiene que leerse igual en los cuatro o se desincronizan.
 *
 * ⚠️ SE LEE UNA SOLA VEZ, AL CARGAR: la casa pasa los parámetros en la URL del `<iframe>` y
 * el router de esta app pierde el `search` en cuanto navega.
 */
const AL_CARGAR = typeof location !== 'undefined' ? new URLSearchParams(location.search) : new URLSearchParams();

/** El workspace de la casa que embebe esta UI (`diseno`), o `''` si corre suelta. */
export const alephWorkspace = AL_CARGAR.get('aleph_ws') ?? '';

/** ¿Corriendo adentro de Aleph? */
export const dentroDeAleph = alephWorkspace.length > 0;
