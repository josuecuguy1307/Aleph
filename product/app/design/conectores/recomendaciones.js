/* recomendaciones.js — DE DÓNDE SALEN LOS CONECTORES RECOMENDADOS POR ESPACIO.
 *
 * La capa LEE de la cuarta vista, en las mismas capas que el resto:
 *
 *   recomendaciones.js       LEE   · esto: las tres llamadas, cero interpretación
 *   recomendados.js          PINTA · el HTML de las filas y las palabras
 *   montaje.js               CONECTA · nodos, clicks y recarga
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * POR QUÉ ESTE ARCHIVO NACE DESPUÉS DE LA VISTA, Y NO ANTES.
 *
 * La vista se escribió con sus tres `fetch` adentro, más los clicks, más los textos: un
 * archivo haciendo los cuatro trabajos que `3541f7c3` separó cuando demolió 4.592 líneas por
 * exactamente eso. Este archivo es la mitad de la reparación. No trae lógica nueva: trae la
 * que estaba adentro de la vista, movida al piso que le toca.
 *
 * ⚠️ Y LAS DOS VISTAS LEEN DE ACÁ — la de Conectores y la del canvas de cada workspace. Ese
 * es el punto: si cada una resolviera su propia lista, configurar `github` en Ciencia podría
 * verse «sin configurar» en Diseño. Un destino, N vistas.
 *
 * CONVENCIÓN, la misma de `catalogo.js`: falla ABIERTO. Un cable cortado devuelve `null` y
 * quien pinta dice «no pude leer»; jamás un cero, que se lee como «no hay» y es otra cosa.
 */
import { cabeceras } from "./fuentes.js";

/** LOS RECOMENDADOS DE UN ESPACIO, con el estado del usuario si hay sesión.
 *
 * `user_id` viaja sólo si lo hay: sin él el catálogo se sirve igual (es público) pero con
 * `tiene_llave: null`, que la cara tiene que leer como «no sé» y no como «no». */
export async function traerRecomendados(ws, userId = null) {
  const u = new URL("/v1/connectors", location.origin);
  u.searchParams.set("workspace", ws);
  if (userId) u.searchParams.set("user_id", userId);
  try {
    const r = await fetch(u, { headers: cabeceras() });
    if (!r.ok) {
      // LA CAUSA TIPADA DEL CUERPO ANTES QUE EL NÚMERO. Un «HTTP 500» pelado sobre un error
      // que traía motivo es perder el motivo en el camino. Se devuelve, no se pinta: pintar
      // es de la otra capa.
      let causa = "";
      try { const j = await r.json(); causa = (j.detail && (j.detail.detail || j.detail.error)) || ""; }
      catch (_) { /* sin cuerpo */ }
      return { error: { http: r.status, causa } };
    }
    return await r.json();
  } catch (_) {
    return { error: { http: 0, causa: "" } };
  }
}

/** LA FICHA DE UN CONECTOR · qué campos pide. Se pide al abrir el formulario de UNO, nunca
 *  para la lista: 29 fichas para pintar 29 filas es pagar por lo que no se muestra. */
export async function traerFicha(slug) {
  try {
    const r = await fetch(`/v1/connectors/${encodeURIComponent(slug)}`, { headers: cabeceras() });
    if (!r.ok) return null;
    return await r.json();
  } catch (_) { return null; }
}

/** LA LISTA A · las fuentes que YA funcionan en cada espacio, del stack instalado.
 *
 * Devuelve un mapa `{ws: [fuentes]}` o `null`. La diferencia entre «no hay» y «no sé» es
 * la razón del `null`: si este workspace no está instalado en esta máquina, decir «0 ya
 * funcionan» sería afirmar algo que no se midió. */
export async function traerFuentesPorEspacio() {
  try {
    const r = await fetch("/v1/workspaces", { headers: cabeceras() });
    if (!r.ok) return null;
    const d = await r.json();
    const mapa = {};
    (d.workspaces || []).forEach((w) => { mapa[w.id] = w.sources || []; });
    return mapa;
  } catch (_) { return null; }
}
