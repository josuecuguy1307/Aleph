/* espacios.js — EL FILTRO POR ESPACIO, PARA LAS PANTALLAS DE LA CASA.
 * [convergencia · superficie 1]
 *
 * QUÉ PROBLEMA RESUELVE, MEDIDO ANTES DE ESCRIBIRLO. El pedido era «sin filtro, los seis
 * workspaces mezclados; con filtro, sólo ese espacio». Medido contra la `aleph.db` real,
 * la premisa era falsa: los seis no estaban mezclados — **no estaban**.
 *
 *   · Historial lee `GET /v1/users/{id}/runs`. Runs con espacio de workspace: 0 de 2.341.
 *     Un turno de workspace no crea un run.
 *   · Biblioteca lee `GET /v1/users/{id}/outputs`. La tabla `outputs` es
 *     `id · run_id · kind · mime · uri · content · bytes · created_at`: **no tiene ninguna
 *     columna que pueda llevar un workspace**. La obra de un workspace va a
 *     `artifact_store`, que es otro almacén.
 *
 * O sea que un filtro sobre esas dos fuentes sólo podía mostrar vacío, siempre. Así que
 * este módulo no es el filtro: es **la fuente que faltaba**. El filtro es tres chips en
 * cada pantalla, con el mismo helper de chip que esas pantallas ya tenían.
 *
 * DE DÓNDE SALE CADA MITAD, y las dos ya existían:
 *   · los HILOS ← `GET /v1/workspaces/{ws}/memoria`, el mapa `(dueño, workspace) → chat_id`
 *     que la ley técnica 4 puso en el dominio (y no en `localStorage`, que era de
 *     instalación y hacía que dos cuentas compartieran hilo);
 *   · la OBRA ← `GET /v1/sessions/{sid}/artifacts`, cuyo resumen ahora trae `workspace`
 *     resuelto de la procedencia del lado del servidor.
 *
 * LOS RÓTULOS SON DOS PALABRAS: `GENERAL` y el nombre del espacio.
 * ⚠️ DEUDA DECLARADA: la Fase 3 de Ajustes tiene sus propios rótulos de ámbito
 * (`TODA LA CASA` / `SÓLO <workspace>`) en `ajustes.js`, que hoy está SIN COMMITEAR en otro
 * worktree — o sea que no está en `main` y no se puede importar sin inventar la dependencia.
 * Cuando esa rama entre, **los dos juegos se unifican en uno**: son el mismo concepto
 * («esto que estoy mirando, ¿es de toda la casa o de un espacio?») dicho dos veces.
 */
// Del módulo de la tabla, no de `recomendados.js`: es el mismo dato y esta ruta no
// arrastra el subsistema de conectores entero.
//
// ⚠️ `ORDEN_ETIQUETA` ESTABA EN EL CUERPO Y NO EN EL IMPORT, y eso mataba el módulo entero:
// `memoriaDeLosSeis` lo usa en su PRIMERA línea, así que tiraba `ReferenceError:
// ORDEN_ETIQUETA is not defined` y con ella se caían las tres funciones públicas —
// `hilosDeEspacio` y `obraDeEspacio` la llaman. O sea que el filtro por espacio del
// Historial y de la Biblioteca no filtraba mal: **no corría**. Los chips igual se
// dibujaban (salen de `espacios()`, que sí estaba importada), y por eso la pantalla se veía
// entera y nadie lo reportó. Lo destapó abrir el Historial en el navegador; ninguna vara
// lo veía, porque una vara de Python no ejecuta el módulo de la pantalla.
import { GENERAL, ORDEN_ETIQUETA, etiqueta, espacios } from "./espacios-tabla.js";
export { GENERAL, etiqueta, espacios };
import { cabeceras } from "./conectores/fuentes.js";


async function json(url) {
  try {
    const r = await fetch(url, { headers: cabeceras() });
    return r.ok ? await r.json() : null;
  } catch (_) {
    return null;                       // sin red, la pantalla se queda con lo que tenía
  }
}

/**
 * CÓMO QUEDÓ CADA ESPACIO PARA ESTE DUEÑO: `{ws: {chat_id, sid}}`.
 *
 * Seis pedidos en paralelo y no uno: no hay endpoint que devuelva los seis, y la memoria
 * es un archivo por dueño que el backend ya lee en microsegundos. Un espacio donde el
 * usuario todavía no entró contesta `{}` — y esa ausencia se conserva como ausencia, no se
 * rellena con un hilo vacío que después la pantalla contaría como sesión.
 */
export async function memoriaDeLosSeis(userId) {
  if (!userId) return {};
  const ids = Object.keys(ORDEN_ETIQUETA);
  const partes = await Promise.all(ids.map((ws) =>
    json(`/v1/workspaces/${encodeURIComponent(ws)}/memoria?user_id=${encodeURIComponent(userId)}`)));
  const salida = {};
  ids.forEach((ws, i) => {
    const m = (partes[i] && partes[i].memoria) || null;
    if (m && (m.chat_id || m.sid)) salida[ws] = { chat_id: m.chat_id || null, sid: m.sid || null };
  });
  return salida;
}

/**
 * LOS HILOS DE WORKSPACE COMO SESIONES: `[{ws, chat_id, title, updated_at}]`.
 *
 * Un hilo de workspace **es** una sesión —más que un `run`, que es una ejecución suelta—,
 * y hasta hoy no aparecía en ninguna pantalla de la casa aunque estuviera en la misma
 * tabla `chats` que los de la Sala. El título y la fecha salen de `GET /v1/chats`, que ya
 * los sirve para el sidebar: no se re-piden por hilo ni se re-derivan acá.
 */
export async function hilosDeEspacio(userId) {
  const mem = await memoriaDeLosSeis(userId);
  const wss = Object.keys(mem).filter((ws) => mem[ws].chat_id);
  if (!wss.length) return [];
  const lista = await json("/v1/chats");
  const porId = {};
  ((lista && (lista.chats || lista.items)) || []).forEach((c) => { porId[c.id] = c; });
  return wss.map((ws) => {
    const c = porId[mem[ws].chat_id] || {};
    return { ws, chat_id: mem[ws].chat_id, title: c.title || etiqueta(ws),
             updated_at: c.updated_at || c.created_at || null,
             n: Number(c.n_messages || c.messages || 0) || 0 };
  }).filter((h) => porId[h.chat_id]);   // un hilo que el dueño ya borró no es una sesión
}

/**
 * LA OBRA CON SU ESPACIO: `[{id, title, type, created_at, workspace, sid}]`.
 *
 * Las sesiones de obra son POCAS y casi siempre UNA: la Sala y los seis workspaces
 * comparten `sid` a propósito («la Biblioteca es una sola», `workspaces/<ws>.html`), así
 * que esto se deduplica a un pedido en el caso normal. Se piden igual todas las que la
 * memoria declare, porque compartir el `sid` es la regla y no una garantía.
 */
export async function obraDeEspacio(userId, sidDeLaSala) {
  const mem = await memoriaDeLosSeis(userId);
  const sids = [];
  const ver = (s) => { if (s && sids.indexOf(s) < 0) sids.push(s); };
  ver(sidDeLaSala);
  Object.keys(mem).forEach((ws) => ver(mem[ws].sid));
  if (!sids.length) return [];
  const partes = await Promise.all(sids.map((sid) =>
    json(`/v1/sessions/${encodeURIComponent(sid)}/artifacts`)));
  const salida = [];
  partes.forEach((p, i) => {
    ((p && p.artifacts) || []).forEach((a) => {
      salida.push(Object.assign({}, a, { sid: sids[i], workspace: a.workspace || null }));
    });
  });
  return salida;
}

/** ¿Esta fila pasa el filtro? Sin filtro pasa todo — GENERAL no es un espacio, es su ausencia. */
export function pasa(filtro, wsDeLaFila) {
  return !filtro || filtro === GENERAL || filtro === wsDeLaFila;
}

if (typeof window !== "undefined") {
  // El puente a las pantallas `.dc.html`, que corren su lógica en un bloque
  // `<script type="text/x-dc">` y por eso no pueden `import`. Mismo patrón que
  // `workspaces/conectores-del-espacio.js` con `window.AlephConectoresDelEspacio`.
  window.AlephEspacios = { GENERAL, espacios, etiqueta, hilosDeEspacio, obraDeEspacio,
                           memoriaDeLosSeis, pasa };

  /* ── Y AVISA QUE LLEGÓ. Acá estaba la carrera. ──────────────────────────────────────
   * Este archivo es `type="module"`, o sea que se ejecuta DESPUÉS de parsear el
   * documento. El runtime DC de Historial y Biblioteca monta cuando le toca, y las dos
   * pantallas leían `window.AlephEspacios` UNA vez:
   *
   *     Historial.dc.html:311   const E=window.AlephEspacios; if(!E) return;   ← y no vuelve
   *     Historial.dc.html:427   window.AlephEspacios || {espacios:()=>[]}      ← sin chips
   *
   * Si el módulo llegaba después del montaje, la pantalla se dibujaba SIN la fila de chips
   * y sin reintento — y si llegaba antes, CON. La misma pantalla, dos caras, según quién
   * ganara. Lo destapó `qa/vara_visual.mjs`: 2,4–2,9 % de diferencia entre dos capturas
   * seguidas sin tocar nada. Ninguna de las 356 varas lo veía, porque ninguna mira la cara.
   *
   * El aviso no es un mecanismo nuevo: es el mismo que `brandface.js` usa desde su primera
   * versión —una promesa `ready` más un evento— para exactamente este problema. */
  try {
    window.AlephEspacios.listo = true;
    window.dispatchEvent(new Event("aleph:espacios"));
  } catch (e) { /* un aviso que falla no puede tumbar el módulo */ }
}
