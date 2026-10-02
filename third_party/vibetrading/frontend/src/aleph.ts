// aleph.ts — LO QUE LA CASA LE CUENTA A LA MESA.
//
// [Gate 4 · Fase 6 · Finanzas · inmersión 3.8]
//
// La puerta de Finanzas (`product/app/design/workspaces/finanzas.html`) arma el `src` del
// iframe UNA SOLA VEZ, con `?aleph_ws`, `?aleph_label`, `?aleph_scheme` y `?aleph_chat`. Los
// parámetros se leen ACÁ, al cargar el módulo, y no cuando alguien los pregunta: en cuanto el
// router del stack navega a otra vista, el `search` se pierde. Es el mismo motivo por el que
// existe `third_party/openscience/frontend/workspace/src/aleph.ts`, y está medido.
//
// Sirve para que la mesa sepa que está EMBEBIDA y esconda lo que la casa ya provee (el
// interruptor de tema, que adentro lo gobierna `aleph_scheme`). Corriendo suelta, el stack
// conserva todo lo suyo: ninguno de estos parámetros existe y `dentroDeAleph` es falso.
const AL_CARGAR = new URLSearchParams(typeof location === "undefined" ? "" : location.search);

export const alephWorkspace = AL_CARGAR.get("aleph_ws") ?? "";
export const alephNombre = AL_CARGAR.get("aleph_label") ?? "";
export const alephChat = AL_CARGAR.get("aleph_chat") ?? "";
export const dentroDeAleph = alephWorkspace.length > 0;
