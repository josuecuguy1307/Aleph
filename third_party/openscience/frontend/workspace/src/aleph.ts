/**
 * aleph.ts — LO QUE ESTA UI SABE DE LA CASA QUE LA EMBEBE.
 * [Aleph · Gate 4 · Fase 4 · O3 · inmersión nivel-2 · ley 3]
 *
 * Este archivo NO es del proyecto de origen: lo agrega Aleph, y está registrado como tal
 * en `EXTIRPACIONES.md`. Existe para que la regla «¿estoy adentro de Aleph?» se escriba
 * UNA vez: tres copias de un `location.search.includes(...)` en tres pantallas se
 * desincronizan sin que nadie se entere.
 *
 * ⚠️ LOS PARÁMETROS SE LEEN UNA SOLA VEZ, AL CARGAR, y esto es load-bearing: la casa los
 * pasa en la URL del `<iframe>`, y en cuanto el router de esta app navega a un proyecto
 * (`navigate(projectHref(...))`) el `search` se pierde. Leerlos tarde daría «no estoy
 * adentro de Aleph» justo después del primer click.
 */

const AL_CARGAR = typeof location !== "undefined" ? new URLSearchParams(location.search) : new URLSearchParams()

/** El workspace de la casa que embebe esta UI (`ciencia`), o `null` si corre suelta. */
export const alephWorkspace = AL_CARGAR.get("aleph_ws")

/** ¿Corriendo adentro de Aleph? */
export const dentroDeAleph = Boolean(alephWorkspace)

/** Cómo se llama este lugar EN LA CASA. Es lo que la UI muestra donde antes decía un puerto. */
export const alephNombre = AL_CARGAR.get("aleph_label") || alephWorkspace || ""

/** El hilo de la casa para este workspace, si lo hay. */
export const alephChat = AL_CARGAR.get("aleph_chat")
