/* modelos.semaforo.js — adaptador del diccionario ÚNICO del producto.
 *
 * MODELOS V2 disuelve la deuda #1 de P8: `sin_runtime`, `sin_espacio`,
 * `descarga_cancelada` y `formato_no_soportado` ya viven en CAUSAS/CAMINOS de
 * cuarto.semaforo.js. Este archivo conserva la API que usa la pantalla, pero no declara
 * una segunda verdad.
 */
import Sem from "../cuarto/cuarto.semaforo.js";

const PROPIAS = [
  "sin_runtime", "sin_espacio", "descarga_cancelada", "formato_no_soportado",
];

/** Aliases derivados sólo para compatibilidad con las varas P8 previas. */
export const CAUSAS_MODELO = Object.fromEntries(
  PROPIAS.map((c) => [c, Sem.CAUSAS[c]]).filter(([, v]) => !!v));
export const CAMINOS_MODELO = Object.fromEntries(
  PROPIAS.map((c) => ["roto/" + c, Sem.CAMINOS["roto/" + c]]).filter(([, v]) => !!v));

export function textoCausa(causa, ingles) {
  if (!causa) return "";
  const c = Sem.CAUSAS[causa];
  if (!c) return String(causa).replace(/_/g, " ");
  return ingles ? (c.en || c.es) : c.es;
}

export function caminoModelo(res) {
  return Sem.caminoDe(res);
}

/* ⚠️ [F9] ESTO ERA UNA COPIA PARALELA DEL DICCIONARIO ÚNICO, Y SE DERIVA.
 *
 * Tenía los mismos cinco estados escritos a mano —mismos emojis, clases CSS distintas
 * (`verde` vs `sem-verde`)— y le FALTABA `parcial`, que el único sí tiene: una fila parcial
 * caía a `detectado` y se leía «sin probar», que no es lo que pasa.
 *
 * Dos diccionarios del mismo vocabulario es cómo se llega a que la misma pieza salga de un
 * color en una superficie y de otro en la de al lado. No se parchea el color: se saca la
 * segunda verdad. Con las superficies leyendo del mismo lugar, la discrepancia deja de ser
 * posible POR CONSTRUCCIÓN.
 *
 * La forma (`g`/`es`/`en` en minúscula) se conserva porque es la que esta superficie
 * consume; lo que cambia es de dónde salen los valores. `cls` se mantiene por compatibilidad
 * —hoy no lo lee nadie, verificado— y ahora trae la clase REAL del diccionario (`sem-*`).
 */
export const ESTADO = Object.fromEntries(
  Object.entries(Sem.ESTADOS).map(([clave, v]) => [clave, {
    g: v.emoji,
    cls: v.css,
    es: String(v.es || "").toLowerCase(),
    en: String(v.en || "").toLowerCase(),
  }]));

export default { CAUSAS_MODELO, CAMINOS_MODELO, caminoModelo, textoCausa, ESTADO, Sem };
