/* verify_obra6c_front.mjs — la mitad de superficie de la Obra 6c.
 *
 * La corre `qa/verify_obra6c.py`; imprime una línea JSON con los testigos. No se invoca
 * suelta: la vara es una sola, como manda la casa.
 *
 * Mide COMPORTAMIENTO, no texto: monta la sección sobre el DOM mínimo, espía los verbos y
 * aprieta los botones reales. Un grep sobre `montaje.js` habría salido verde con el string
 * escrito en un comentario.
 */
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { instalarDOM, host } from "./dom_minimo.mjs";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = join(RAIZ, "product/app/design");
instalarDOM();
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
globalThis.sessionStorage = globalThis.localStorage;

const C = await import(join(D, "conectores/catalogo.js"));
const M = await import(join(D, "conectores/montaje.js"));

const R = {};
const esperar = () => new Promise((r) => setTimeout(r, 12));

/* ── el banco: la sección montada, con los verbos espiados ─────────────────────────── */

// ⚠️ EL TÍTULO Y LA CONSULTA SON DISTINTOS A PROPÓSITO. Es lo único que hace que este banco
// discrimine: si mandara los dos el mismo string, cualquiera de los dos pasaría el testigo y
// la vara estaría midiendo la nada. `nombre` es el título largo del publicador —el que se
// mandaba antes— y `consulta` es lo que la persona tecleó.
const TITULO = "CreativeScope — Mobile Game Ad Creative Intelligence";
const PIEZA = "ai.creativescope/creative-intelligence";
const CONSULTA = "pe";

const BUSQUEDA = {
  registry_status: "ok",
  items: [{ id: PIEZA, name: TITULO, description: "ads", source: "registry",
            badge: { verified: false, label: "", publisher: "creativescope",
                     namespace: "ai.creativescope" },
            server_name: PIEZA, namespace: "ai.creativescope", vendor: "creativescope",
            requisito: "ninguno", confianza: 0.4, consecuencias: null,
            referencia_crudo: null }],
  counts: { registry: 1 },
};

function banco(veredicto) {
  const espia = { validar: [], traer: [] };
  Object.assign(M.ESTADO.catalogo, {
    consulta: "", vista: null, elegida: null, ficha: null, comprobando: null,
    crudo: null, crudoAbierto: false, viaje: null, llegada: null, gen: 0, genViaje: 0,
  });
  Object.assign(M.ESTADO, { modelos: [], vault: {}, vista: "conectores", leido: false,
                            abierto: null, detalle: null, q: "" });
  M.ESTADO.midiendo.clear();
  const hosts = {
    lista: host("localRows"), resumen: host("cxSummary"), conteo: host("localCount"),
    aduana: host("aduanaRows"), conteoAduana: host("aduanaCount"),
    seccionAduana: host("aduanaSection"), llavero: host("keyringRows"),
    conteoLlavero: host("keyringCount"), panelConectores: host("connectorsView"),
    panelLlavero: host("keyringView"), cabecera: host("cxHead"), tabs: host("cxTabs"),
    entradaCatalogo: host("cxCatalogEntry"), panelCatalogo: host("catalogView"),
    catalogoBuscador: host("cxCatalogSearch"), catalogoLista: host("cxCatalogList"),
    catalogoFicha: host("cxCatalogCard"), catalogoLlegada: host("cxCatalogArrival"),
    catalogoVista: host("cxCatalogPane"),
  };
  for (const k of ["catalogoBuscador", "catalogoLista", "catalogoFicha", "catalogoLlegada",
                   "catalogoVista"]) hosts.panelCatalogo.appendChild(hosts[k]);
  M.VERBOS.cargar = async () => ({ modelos: [], vault: {}, leido: true, alias: {} });
  M.VERBOS.barrerLocal = async () => false;
  M.VERBOS.medir = async () => false;
  M.VERBOS.buscarCatalogo = async () => BUSQUEDA;
  M.VERBOS.crudoDePieza = async () => null;
  M.VERBOS.validarPieza = async (servicio, servidor) => {
    espia.validar.push({ servicio, servidor });
    return veredicto;
  };
  M.VERBOS.traerPieza = async (args) => { espia.traer.push(args); return {}; };
  return { hosts, espia };
}

const V_DUDOSO = {
  service: CONSULTA, verdict: "dudoso", registry_status: "ok", server_name: PIEZA,
  trusted_server: null, vendor_kind: "dns", verified: false, score: 0.4,
  reason: "el namespace está verificado, pero eso identifica a quien la publicó",
  ranked: [], from_cache: false, registry_down: false, retry: false,
  picked: PIEZA, picked_is_trusted: null, message: "no está verificado como oficial.",
};

/* ══ 13 · LA FICHA PREGUNTA POR LA PIEZA, NO POR EL TÍTULO ════════════════════════════ */
{
  const { hosts, espia } = banco(V_DUDOSO);
  await M.montar(hosts);
  await window.__conectores.catalogo(CONSULTA);
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar();
  const v = espia.validar[0] || {};
  R["13_la_ficha_pide_por_la_pieza"] = {
    ok: espia.validar.length === 1 && v.servidor === PIEZA && v.servicio === CONSULTA,
    mandó: v,
  };
  // NEGATIVO — el título del publicador NO viaja. Es el string exacto que rompía el caso, y
  // sin este testigo el de arriba pasaría igual mandando los dos.
  R["13_negativo_el_titulo_no_viaja"] = {
    ok: v.servicio !== TITULO && v.servidor !== TITULO,
    titulo: TITULO,
  };
}

/* ══ 14 · EL VIAJE MANDA LA MISMA PAREJA ═════════════════════════════════════════════ */
{
  const { hosts, espia } = banco(V_DUDOSO);
  await M.montar(hosts);
  await window.__conectores.catalogo(CONSULTA);
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar();
  const boton = hosts.catalogoFicha.querySelector("button[data-traer-asi], button[data-traer]");
  if (boton) await boton.click();
  await esperar(); await esperar();
  const t = espia.traer[0] || {};
  R["14_el_viaje_manda_la_consulta"] = {
    ok: espia.traer.length === 1 && t.servidor === PIEZA && t.servicio === CONSULTA,
    mandó: { servicio: t.servicio, servidor: t.servidor, traerAsi: t.traerAsi },
  };
  R["14_negativo_el_viaje_no_manda_el_titulo"] = {
    ok: espia.traer.length === 1 && t.servicio !== TITULO,
  };
}

/* ══ 15 · LA CARA DEL IMPOSTOR EXIGE SABER CUÁL ES LA BUENA ══════════════════════════
 *
 * Tres entradas a `modelarFicha`, tres desenlaces. Es lo que prueba que discrimina: un mapa
 * que mirara sólo `picked_is_trusted === false` pintaría impostor en los tres.
 */
const fila = C.modelarFila(BUSQUEDA.items[0]);
const cara = (v) => {
  const f = C.modelarFicha(fila, v);
  return { cara: f.cara, motivo: f.motivo, confiable: f.confiable };
};

// (a) POSITIVO — hay una buena que ofrecer → impostor, con su nombre.
const impostor = cara({ ...V_DUDOSO, picked_is_trusted: false,
                        trusted_server: "com.stripe/mcp" });
R["15_la_cara_del_impostor_nombra_la_buena"] = {
  ok: impostor.cara === C.CARA_NO_SE_PUEDE && impostor.motivo === C.MOTIVO_IMPOSTOR
      && impostor.confiable === "com.stripe/mcp",
  ...impostor,
};

// (b) NEGATIVO — `picked_is_trusted false` pero SIN una buena que ofrecer: acusar sería
//     mandar a un callejón sin salida. Cae al veredicto, que es `con_reservas`.
const sinBuena = cara({ ...V_DUDOSO, picked_is_trusted: false, server_name: null,
                        trusted_server: null });
R["15_negativo_sin_una_buena_no_hay_acusacion"] = {
  ok: sinBuena.cara === C.CARA_CON_RESERVAS, ...sinBuena,
};

// (c) NEGATIVO 2 — el dudoso HONESTO (pit null) nunca es impostor.
const honesto = cara(V_DUDOSO);
R["16_el_dudoso_honesto_no_es_impostor"] = {
  ok: honesto.cara === C.CARA_CON_RESERVAS && honesto.motivo === null, ...honesto,
};

/* ══ 17 · «NO EXISTE» DEJA DE LLEVAR EL MOTIVO «ES UN IMPOSTOR» ══════════════════════
 *
 * La contradicción latente que la Obra 5 dejó nombrada: `picked_is_trusted` valía False
 * sobre un veredicto sin ganador, así que la ficha llevaba motivo «no es de quien dice ser»
 * al lado de un mensaje que decía «el registro no conoce este servicio».
 */
const inexistente = cara({ ...V_DUDOSO, verdict: "nada", server_name: null,
                           trusted_server: null, picked_is_trusted: null });
R["17_no_existe_no_dice_impostor"] = {
  ok: inexistente.cara === C.CARA_NO_SE_PUEDE && inexistente.motivo === C.MOTIVO_INEXISTENTE,
  ...inexistente,
};
// NEGATIVO — con el False del código de antes, el MISMO veredicto sí decía impostor. Es la
// prueba de que el testigo de arriba mide el arreglo y no una casualidad.
const conElFalseViejo = cara({ ...V_DUDOSO, verdict: "nada", server_name: "com.stripe/mcp",
                               trusted_server: null, picked_is_trusted: false });
R["17_negativo_con_el_false_viejo_decia_impostor"] = {
  ok: conElFalseViejo.motivo === C.MOTIVO_IMPOSTOR, ...conElFalseViejo,
};

console.log("__JSON__" + JSON.stringify(R));
