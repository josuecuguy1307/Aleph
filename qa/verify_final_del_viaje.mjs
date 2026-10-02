#!/usr/bin/env node
/**
 * verify_final_del_viaje.mjs — LA VARA DEL ÉXITO QUE NO LLEVABA A NINGUNA PARTE.
 *
 *   node qa/verify_final_del_viaje.mjs
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * EL DEFECTO ERA UNA ASIMETRÍA, no un adorno faltante.
 *
 * El FALLO ya terminaba bien: el panel se queda en pantalla, dice en qué paso se detuvo,
 * por qué, y ofrece su salida. El ÉXITO no: el panel se cerraba SOLO en el mismo instante
 * en que la pieza llegaba, dejaba al usuario en el catálogo público con un aviso chico, y
 * la pieza quedaba invisible hasta buscarla a mano. persona usuaria lo probó y **no supo si había
 * entrado**.
 *
 * Lo que esta obra le da al éxito es lo que el fallo ya tenía: se queda, dice dónde quedó
 * la pieza CON SU NOMBRE, ofrece un camino que NAVEGA y SEÑALA, y lo cierra el usuario.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * EL GUARD QUE ORDENA TODO: **ALCANZABILIDAD** — igual que `verify_seccion.mjs`, del que
 * esta vara toma el arnés. No alcanza con que la superficie devuelva el HTML correcto: la
 * vara APRIETA los botones que la superficie emitió y mira qué pasó en el estado real.
 *
 * Cada punto trae su NEGATIVO, y los negativos no son mocks: son el MISMO montaje con el
 * comportamiento de antes (el viaje anulado a mano) o con la entrada que no corresponde.
 *
 * Bloques:
 *   1 · el viaje NO se cierra solo cuando la pieza llega        (+ negativo: antes sí)
 *   2 · el estado final es explícito y nombra la pieza          (+ los dos desenlaces)
 *   3 · «En preparación» dice QUÉ FALTA                         (+ negativo: sin faltante)
 *   4 · el camino NAVEGA y la pieza queda SEÑALADA              (+ negativo: no señala otra)
 *   5 · cerrar es del usuario: hay ✕ y sólo el ✕ cierra         (+ negativo: no aparece antes)
 *   6 · GUARD · el fallo no se movió: sigue con su causa y su salida
 */
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { instalarDOM, host } from "./dom_minimo.mjs";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = join(RAIZ, "product/app/design");

instalarDOM();   // ANTES de importar: `montaje.js` toca `window` al cargarse

const SC = await import(join(D, "conectores/superficie-catalogo.js"));
const M = await import(join(D, "conectores/montaje.js"));

const FALLOS = [];
const RESULTADO = {};
const ok = (cond, etiqueta, detalle = "") => {
  console.log((cond ? "  ✅ " : "  ❌ ") + etiqueta + (detalle ? ` · ${detalle}` : ""));
  if (!cond) FALLOS.push(etiqueta);
  return !!cond;
};
const paso = (clave, cond) => { RESULTADO[clave] = (RESULTADO[clave] !== false) && !!cond; };
const esperar = () => new Promise((r) => setTimeout(r, 0));
// `senalarPieza` marca en el frame siguiente (la lista se repinta después de `irA`).
const esperarFrame = () => new Promise((r) => setTimeout(r, 24));

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LOS FIXTURES · el vocabulario EXACTO de `catalog_equip_router`, y dos desenlaces.
 * ════════════════════════════════════════════════════════════════════════════════════ */
const PIEZA = "org.arxiv/search";
const BUSQUEDA = {
  query: "arxiv", source: "registry", registry_status: "ok", internal_status: "ok",
  counts: { internal: 0, registry: 1, total: 1 }, notice: null,
  items: [{
    id: PIEZA, name: "arXiv", description: "papers", source: "registry",
    badge: { kind: "official_dns", label: "✓ oficial", verified: true, vendor_kind: "dns",
             namespace: "org.arxiv", publisher: "arxiv" },
    score: 0.99, server_name: PIEZA, requisito: "ninguno", confianza: 0.99,
    fecha_ingesta: "2026-08-05T05:41:20.377753+00:00",
    consecuencias: { write: false, send: false, delete: false, declaradas: ["search"] },
    referencia_crudo: "/v1/catalog/raw?catalog_id=org.arxiv%2Fsearch",
  }],
};
const VEREDICTO = {
  service: "arxiv", verdict: "confiable", registry_status: "ok", server_name: PIEZA,
  vendor_kind: "dns", verified: true, score: 0.99, reason: "vendor verificado",
  ranked: [], from_cache: false, registry_down: false, retry: false,
  picked: PIEZA, picked_is_trusted: true, message: "verificado",
};
const LLEGA = [
  { type: "dispatch.iniciado", service: "arxiv", server_name: PIEZA, free: true },
  { type: "resolver.buscando", service: "arxiv" },
  { type: "resolver.encontrado", origin: "registry", server_name: PIEZA, vendor_kind: "dns",
    verified: true, from_cache: false, ranked: [] },
  { type: "curacion.probando", server: PIEZA },
  { type: "mcp.equipado", origin: "registry", server: PIEZA, tools: ["search"],
    belt_ref: "synth_belts/x/belt.mcp.json", registered: true, tools_detail: [] },
  { type: "cerrado", path: "registry", ok: true, encontrado: true, forjado: false, server: PIEZA },
];
const FALLA = [
  { type: "dispatch.iniciado", service: "arxiv", server_name: PIEZA },
  { type: "resolver.buscando", service: "arxiv" },
  { type: "resolver.encontrado", origin: "registry", server_name: PIEZA, verified: true },
  { type: "curacion.probando", server: PIEZA },
  { type: "curacion.rechazo", cause: "curacion_rechazo", stage: "curar", server: PIEZA },
  { type: "cerrado", path: "curacion", ok: false, encontrado: true, forjado: false,
    server: PIEZA, cause: "curacion_rechazo" },
];

/** El modelo que `recargar()` devuelve DESPUÉS del equip: es lo que decide el desenlace.
 *  `pertenencia.local` = entró y está lista · `false` = quedó En preparación con pendientes. */
const modelo = (local, faltan = []) => ({
  entityId: PIEZA, nombre: "arXiv", servidor: PIEZA,
  pertenencia: { local, instalada_ok: true, credencial_ok: local, escrutable_ok: true,
                 faltan, rotar: false, regresion: false, admitida: false,
                 motivo: local ? null : "falta la llave" },
  pasos: [], veredicto: { estado: local ? "viva" : "sin_sondear" },
  ultima_verificacion: "2026-08-07T15:00:00+00:00",
});

function banco({ frames = LLEGA, modelos = [] } = {}) {
  const espia = { traer: [], cargas: 0 };
  Object.assign(M.ESTADO.catalogo, {
    consulta: "", vista: null, elegida: null, ficha: null, comprobando: null,
    crudo: null, crudoAbierto: false, viaje: null, llegada: null, gen: 0, genViaje: 0,
  });
  Object.assign(M.ESTADO, { modelos: [], vault: {}, vista: "conectores", leido: false,
                            abierto: null, detalle: null, q: "", senalada: null });
  M.ESTADO.midiendo.clear();
  const hosts = {
    lista: host("localRows"), resumen: host("cxSummary"), conteo: host("localCount"),
    aduana: host("aduanaRows"), conteoAduana: host("aduanaCount"),
    seccionAduana: host("aduanaSection"), llavero: host("keyringRows"),
    conteoLlavero: host("keyringCount"),
    panelConectores: host("connectorsView"), panelLlavero: host("keyringView"),
    cabecera: host("cxHead"), tabs: host("cxTabs"),
    entradaCatalogo: host("cxCatalogEntry"), panelCatalogo: host("catalogView"),
    catalogoBuscador: host("cxCatalogSearch"), catalogoLista: host("cxCatalogList"),
    catalogoFicha: host("cxCatalogCard"), catalogoLlegada: host("cxCatalogArrival"),
    catalogoVista: host("cxCatalogPane"),
  };
  for (const k of ["catalogoBuscador", "catalogoLista", "catalogoFicha", "catalogoLlegada",
                   "catalogoVista"]) {
    hosts[k].padre = hosts.panelCatalogo;
    hosts.panelCatalogo.hijos.push(hosts[k]);
  }
  hosts.catalogoLista.padre = hosts.catalogoVista;
  Object.assign(M.VERBOS, {
    cargar: async () => { espia.cargas++; return { modelos, vault: {}, leido: true, alias: {} }; },
    barrerLocal: async () => false,
    medir: async () => false,
    buscarCatalogo: async () => BUSQUEDA,
    validarPieza: async () => VEREDICTO,
    crudoDePieza: async () => null,
    traerPieza: async (args, alEvento) => {
      espia.traer.push(args);
      for (const f of frames) alEvento(f);
      return true;
    },
    noCoincide: async () => true,
  });
  return { hosts, espia };
}

/** Trae la pieza de punta a punta, POR CLICKS: abrir la sección, buscar, elegir, [Traer]. */
async function traerPorClicks(opciones) {
  const { hosts, espia } = banco(opciones);
  await M.montar(hosts);
  await window.__conectores.catalogo("arxiv");
  await esperar();
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar();
  const traer = hosts.catalogoFicha.querySelector("button[data-traer]");
  if (!traer) throw new Error("la ficha no ofreció [Traer]: el arnés no llegó al viaje");
  await traer.click();
  await esperar(); await esperar();
  return { hosts, espia };
}

console.log("\n══ GATE 2.5 · C — EL FINAL DEL VIAJE CUANDO SALE BIEN ══\n");

/* ══ 1 · EL VIAJE NO SE CIERRA SOLO ═══════════════════════════════════════════════════ */
console.log("1 · el viaje no se cierra solo");
{
  const { hosts } = await traerPorClicks({ modelos: [modelo(true)] });
  const viaje = M.ESTADO.catalogo.viaje;
  paso("1_no_se_autocierra", ok(!!viaje, "la pieza llegó y el viaje SIGUE en el estado"));
  paso("1_no_se_autocierra",
    ok(!!viaje && viaje.cerrado === true && viaje.ok === true,
       "…y está marcado cerrado+ok, no en curso",
       viaje ? `cerrado=${viaje.cerrado} ok=${viaje.ok}` : "sin viaje"));
  const pintado = hosts.catalogoFicha.innerHTML || "";
  paso("1_no_se_autocierra",
    ok(/cat-viaje/.test(pintado) && /cat-aterrizaje/.test(pintado),
       "el panel del viaje SIGUE pintado, con su desenlace"));

  // EL AVISO CHICO NO CONVIVE CON EL DESENLACE. Los dos cuentan el mismo hecho; juntos son
  // la duplicación de siempre —dos textos para una cosa— y un día dirán cosas distintas.
  paso("1_no_se_autocierra",
    ok((hosts.catalogoLlegada.textContent || "") === "",
       "mientras el desenlace está abierto, el aviso chico calla"));

  // ── NEGATIVO · el comportamiento de ANTES: anular el viaje al llegar. Es la línea que
  //    esta obra sacó de `correrViaje`, puesta a mano sobre el mismo estado.
  M.ESTADO.catalogo.viaje = null;
  M.irA("catalogo");                       // la única puerta de repintado que la sección expone
  const sinViaje = hosts.catalogoFicha.innerHTML || "";
  paso("1_no_se_autocierra",
    ok(!/cat-aterrizaje/.test(sinViaje),
       "NEGATIVO · con el viaje anulado (lo de antes) no queda ningún desenlace en pantalla"));
  // …y ES ENTONCES cuando el aviso aparece: el acuse SOBREVIVE al cierre. Sin este testigo,
  // el de arriba se cumpliría con un aviso que no existe nunca — que sería perder el rastro.
  paso("1_no_se_autocierra",
    ok(/arXiv/.test(hosts.catalogoLlegada.textContent || ""),
       "…y cerrado el desenlace, el aviso chico queda como rastro",
       (hosts.catalogoLlegada.textContent || "").slice(0, 60)));
}

/* ══ 2 · EL ESTADO FINAL ES EXPLÍCITO Y NOMBRA LA PIEZA ═══════════════════════════════ */
console.log("\n2 · el desenlace se dice, con el nombre de la pieza");
{
  const { hosts } = await traerPorClicks({ modelos: [modelo(true)] });
  const txt = hosts.catalogoFicha.textContent || "";
  paso("2_estado_final_explicito",
    ok(/arXiv/.test(txt) && /tu local/i.test(txt),
       "entró al local: lo dice con el nombre de la pieza"));
  paso("2_estado_final_explicito",
    ok(!/En preparación/i.test(txt),
       "…y NO dice «En preparación», que es el otro desenlace"));
}
{
  // EL OTRO DESENLACE, con la MISMA entrada salvo `pertenencia.local`. Que los dos textos
  // salgan del mismo camino es lo que prueba que discrimina en vez de decir siempre lo mismo.
  const { hosts } = await traerPorClicks({ modelos: [modelo(false, ["llave"])] });
  const txt = hosts.catalogoFicha.textContent || "";
  paso("2_estado_final_explicito",
    ok(/arXiv/.test(txt) && /En preparación/i.test(txt),
       "quedó en la aduana: lo dice, también con el nombre"));
  paso("2_estado_final_explicito",
    ok(!/ya está lista para usar/i.test(txt),
       "NEGATIVO · no la declara lista cuando no lo está"));
}

/* ══ 3 · «EN PREPARACIÓN» DICE QUÉ FALTA ══════════════════════════════════════════════ */
console.log("\n3 · en preparación dice qué falta");
{
  const { hosts } = await traerPorClicks({ modelos: [modelo(false, ["llave"])] });
  const txt = hosts.catalogoFicha.textContent || "";
  paso("3_dice_que_falta",
    ok(/llave/i.test(txt), "el pendiente REAL aparece en el desenlace", "faltan=[llave]"));

  // ── NEGATIVO · sin pendiente declarado NO se inventa uno: se dice lo general y se calla
  //    lo que no se sabe. Un «le falta la llave» inventado sería peor que no decir nada.
  const b = await traerPorClicks({ modelos: [modelo(false, [])] });
  const t2 = b.hosts.catalogoFicha.textContent || "";
  paso("3_dice_que_falta",
    ok(/algo tuyo/i.test(t2) && !/llave/i.test(t2),
       "NEGATIVO · sin pendiente declarado no se inventa un faltante"));
}

/* ══ 4 · EL CAMINO NAVEGA Y SEÑALA ════════════════════════════════════════════════════ */
console.log("\n4 · el botón navega y la pieza queda señalada");
{
  const { hosts } = await traerPorClicks({ modelos: [modelo(true)] });
  const boton = hosts.catalogoFicha.querySelector("button[data-ver-pieza]");
  paso("4_navega_y_senala", ok(!!boton, "el desenlace ofrece [Ver en tu local]"));
  paso("4_navega_y_senala",
    ok(!!boton && boton.dataset.verPieza === PIEZA,
       "…apuntando a LA pieza que llegó, no a la lista a secas",
       boton ? boton.dataset.verPieza : "sin botón"));

  const antes = M.ESTADO.vista;
  await boton.click();
  await esperarFrame();
  paso("4_navega_y_senala",
    ok(antes === "catalogo" && M.ESTADO.vista === "conectores",
       "un click NAVEGA al local", `${antes} → ${M.ESTADO.vista}`));
  const fila = hosts.lista.querySelector('[data-senalada="true"]');
  paso("4_navega_y_senala",
    ok(!!fila, "…y al llegar la pieza está SEÑALADA, no hay que buscarla"));
  paso("4_navega_y_senala",
    ok(!!fila && !!fila.querySelector(`[data-panel="${PIEZA}"]`),
       "la señalada es la fila de ESA pieza"));

  // ── NEGATIVO · señalar una pieza que no está en la lista NO marca otra fila. Sin esto,
  //    un selector demasiado laxo pintaría la primera que encuentre y el testigo de arriba
  //    saldría verde igual — señalando la pieza equivocada, que es peor que no señalar.
  fila.removeAttribute("data-senalada");
  M.senalarPieza("com.no-existe/jamas");
  await esperarFrame();
  paso("4_navega_y_senala",
    ok(!hosts.lista.querySelector('[data-senalada="true"]'),
       "NEGATIVO · una pieza que no está en la lista no señala a ninguna otra"));
}
{
  // EL OTRO CAMINO · a la aduana, con su propio rótulo. El botón no puede ser el mismo
  // texto para los dos desenlaces: «Ver en tu local» sobre algo que quedó En preparación
  // mandaría a la lista equivocada.
  const { hosts } = await traerPorClicks({ modelos: [modelo(false, ["llave"])] });
  const boton = hosts.catalogoFicha.querySelector("button[data-ver-pieza]");
  paso("4_navega_y_senala",
    ok(!!boton && boton.dataset.donde === "aduana"
       && /En preparación/i.test(boton.textContent || ""),
       "en la aduana el botón dice [Ver en En preparación]",
       boton ? `${boton.dataset.donde} · ${boton.textContent}` : "sin botón"));
  await boton.click();
  await esperarFrame();
  const fila = hosts.aduana.querySelector('[data-senalada="true"]');
  paso("4_navega_y_senala",
    ok(!!fila, "…y la señala en LA ADUANA, que es donde quedó"));
}

/* ══ 5 · CERRAR ES DEL USUARIO ════════════════════════════════════════════════════════ */
console.log("\n5 · cerrar es del usuario");
{
  const { hosts } = await traerPorClicks({ modelos: [modelo(true)] });
  const x = hosts.catalogoFicha.querySelector("button[data-cerrar-viaje]");
  paso("5_cierra_el_usuario", ok(!!x, "el viaje terminado tiene su ✕"));
  await x.click();
  await esperar();
  paso("5_cierra_el_usuario",
    ok(M.ESTADO.catalogo.viaje === null, "…y el ✕ lo cierra"));
  paso("5_cierra_el_usuario",
    ok(!/cat-aterrizaje/.test(hosts.catalogoFicha.innerHTML || ""),
       "el desenlace se fue de la pantalla sólo cuando el usuario lo pidió"));
}
{
  // ── NEGATIVO · MIENTRAS EL VIAJE CORRE NO HAY ✕. La salida de un viaje en curso es
  //    Cancelar, que además dice qué implica; un aspa ahí no aclara si cierra la ventana o
  //    aborta la traída. Se mira el viaje EN CURSO, sin frames de cierre.
  const enCurso = { cerrado: false, ok: false, causa: null, causaLiteral: null,
                    siguiente: null, servidor: PIEZA,
                    pasos: [{ id: "resolver", estado: "hecho" },
                            { id: "comprobar", estado: "probando" },
                            { id: "traer", estado: "pendiente" }] };
  const html = SC.pintarViaje(enCurso, { nombre: "arXiv" });
  paso("5_cierra_el_usuario",
    ok(!/data-cerrar-viaje/.test(html) && /data-cancelar-viaje/.test(html),
       "NEGATIVO · en curso no hay ✕, hay Cancelar"));
}

/* ══ 6 · GUARD · EL FALLO NO SE MOVIÓ ═════════════════════════════════════════════════ */
console.log("\n6 · guard · el fallo sigue como estaba");
{
  const { hosts } = await traerPorClicks({ frames: FALLA, modelos: [] });
  const txt = hosts.catalogoFicha.textContent || "";
  const html = hosts.catalogoFicha.innerHTML || "";
  paso("6_guard_el_fallo_no_se_movio",
    ok(!!M.ESTADO.catalogo.viaje, "el viaje que falla sigue en pantalla, como siempre"));
  paso("6_guard_el_fallo_no_se_movio",
    ok(/Se detuvo en/i.test(txt), "…diciendo en qué paso se detuvo"));
  paso("6_guard_el_fallo_no_se_movio",
    ok(/cat-paso-causa/.test(html), "…con su causa junto al paso culpable"));
  paso("6_guard_el_fallo_no_se_movio",
    ok(!/cat-aterrizaje/.test(html),
       "y SIN desenlace de llegada: no llegó a ninguna parte"));
  paso("6_guard_el_fallo_no_se_movio",
    ok(!html.includes("data-ver-pieza"),
       "ni botón de ver la pieza: no hay pieza que ver"));
}

console.log("\n" + "═".repeat(78));
console.log("MEDIDO=" + JSON.stringify(RESULTADO));
console.log("═".repeat(78) + "\n");
if (FALLOS.length) {
  console.log(`❌ ${FALLOS.length} FALLO(S):`);
  for (const f of FALLOS) console.log("   · " + f);
  process.exit(1);
}
console.log("✅ verify_final_del_viaje: TODO VERDE");
