#!/usr/bin/env node
/**
 * verify_seccion.mjs — LA VARA DE LA OBRA 4: LA SECCIÓN, la cara del catálogo público.
 *
 *   node qa/verify_seccion.mjs
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * EL GUARD QUE ORDENA TODO: **ALCANZABILIDAD.** El flujo tiene que existir POR CLICKS, no
 * sólo renderizar. Una superficie que pinta el HTML correcto y no tiene un botón cableado
 * es exactamente el bug que esta casa ya pagó: `[Desconectar]` y `[Rotar llave]` existían
 * en el código, viajaban en el bundle, y ningún click de la app instalada llegaba a ellos.
 *
 * Por eso la vara APRIETA cosas. Monta la sección sobre `qa/dom_minimo.mjs` —el DOM más
 * chico que alcanza para delegar un evento— sustituye los VERBOS por espías, y dispara
 * clicks de verdad sobre los nodos que la superficie emitió. Lo que se comprueba no es que
 * una función devuelva un string: es que apretar lleve a correr el verbo correcto.
 *
 * Y corre SIN NAVEGADOR, igual que `verify_superficie_montada.mjs`, por la razón que ese
 * archivo dejó escrita: una vara que necesita browser se corre una vez y se abandona.
 * Medido en esta máquina: playwright no está instalado, y `qa/correr_varas.py` ni siquiera
 * recolecta varas `.mjs`.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * TESTIGOS HEREDADOS. Al enterrar `#registryPanel` y la puerta de `Conectar.dc.html`
 * murieron `verify_registry.mjs` y `verify_catalog_acceptance.mjs`. Sus testigos que
 * siguen siendo ciertos sobre la superficie nueva están acá, marcados «[heredado de …]».
 * Los que no están son los que probaban mecanismos que ya no existen (las facetas del
 * panel, su teclado, su gate de confianza inline).
 */
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { instalarDOM, host } from "./dom_minimo.mjs";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = join(RAIZ, "product/app/design");
const REPORTE = join(RAIZ, "..", "REPORTE-OBRA4-SECCION.md");

instalarDOM();   // ANTES de importar los módulos: `montaje.js` toca `window` al cargarse

const C = await import(join(D, "conectores/catalogo.js"));
const SC = await import(join(D, "conectores/superficie-catalogo.js"));
const S = await import(join(D, "conectores/superficie.js"));
const W = await import(join(D, "conectores/widget.js"));
const M = await import(join(D, "conectores/montaje.js"));
const Sem = await import(join(D, "cuarto/cuarto.semaforo.js"));

const FALLOS = [];
const RESULTADO = {};
const ok = (cond, etiqueta, detalle = "") => {
  console.log((cond ? "  ✅ " : "  ❌ ") + etiqueta + (detalle ? ` · ${detalle}` : ""));
  if (!cond) FALLOS.push(etiqueta);
  return !!cond;
};
const paso = (clave, cond) => { RESULTADO[clave] = (RESULTADO[clave] !== false) && !!cond; };

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LOS FIXTURES · la forma EXACTA que los endpoints devuelven hoy.
 *
 * Medidos sobre main con TestClient (Obra 4 · M1), no inventados. Si el contrato cambia,
 * estos fixtures dejan de parecerse a la realidad y hay que volver a medir — que es
 * precisamente lo que un fixture tiene que forzar.
 * ════════════════════════════════════════════════════════════════════════════════════ */

const ITEM_VERIFICADA = {
  id: "com.stripe/mcp", name: "Stripe", description: "Payment tools", source: "registry",
  badge: { kind: "official_dns", label: "✓ oficial (com.stripe)", verified: true,
           vendor_kind: "dns", namespace: "com.stripe", publisher: "stripe", pinned_as: "stripe" },
  score: 0.992, server_name: "com.stripe/mcp", namespace: "com.stripe", vendor: "stripe",
  requisito: "llave", fecha_ingesta: "2026-08-05T05:41:20.377753+00:00", confianza: 0.992,
  consecuencias: { write: true, send: false, delete: true, declaradas: ["create_charge", "delete_customer"] },
  referencia_crudo: "/v1/catalog/raw?catalog_id=com.stripe%2Fmcp",
};
const ITEM_SIN_SELLO = {
  id: "io.github.evil/stripe-mcp", name: "Stripe MCP", description: "Third-party wrapper",
  source: "registry",
  badge: { kind: "registry_publisher", label: "publicado por github: evil", verified: false,
           vendor_kind: "github_org", namespace: "io.github.evil", publisher: "evil" },
  score: 0.538, server_name: "io.github.evil/stripe-mcp", requisito: "descarga",
  fecha_ingesta: null, confianza: 0.538, consecuencias: "se_sabra_al_conectar",
  referencia_crudo: "/v1/catalog/raw?catalog_id=io.github.evil%2Fstripe-mcp",
};
const BUSQUEDA_OK = {
  query: "stripe", source: "registry", items: [ITEM_VERIFICADA, ITEM_SIN_SELLO],
  registry_status: "ok", internal_status: "ok",
  counts: { internal: 0, registry: 2, total: 2 }, notice: null,
};
const BUSQUEDA_CAIDA = {
  query: "stripe", source: "registry", items: [], registry_status: "unreachable",
  counts: { internal: 0, registry: 0, total: 0 },
  notice: "el catálogo público no responde ahora mismo; te muestro solo los conectores internos (listos). Reintenta.",
};
const BUSQUEDA_VACIA = {
  query: "crm de la ferretería", source: "registry", items: [], registry_status: "ok",
  counts: { internal: 0, registry: 0, total: 0 }, notice: null,
};

const VALIDATE = {
  confiable: { service: "stripe", verdict: "confiable", registry_status: "ok",
    server_name: "com.stripe/mcp", vendor_kind: "dns", verified: true, score: 0.94,
    reason: "vendor verificado por namespace", ranked: [], from_cache: false,
    registry_down: false, retry: false, picked: "com.stripe/mcp", picked_is_trusted: true,
    message: "verificado como oficial — puedes conectar tranquilo." },
  dudoso: { service: "stripe", verdict: "dudoso", registry_status: "ok", server_name: null,
    vendor_kind: "github_org", verified: false, score: 0.38, reason: "sin prueba de dueño",
    ranked: [], from_cache: false, registry_down: false, retry: false,
    picked: "io.github.evil/stripe-mcp", picked_is_trusted: false,
    message: "no está verificado como oficial (sin prueba de dueño). Conecta sólo si confías en la fuente." },
  nada: { service: "stripe", verdict: "nada", registry_status: "ok", server_name: null,
    vendor_kind: null, verified: false, score: null, reason: "sin coincidencia", ranked: [],
    from_cache: false, registry_down: false, retry: false, picked: null, picked_is_trusted: null,
    message: "el registro no conoce este servicio. Puedes construir un MCP desde tu API o tus docs." },
  impostor: { service: "stripe", verdict: "confiable", registry_status: "ok",
    server_name: "com.stripe/mcp", vendor_kind: "dns", verified: true, score: 0.94,
    reason: "vendor verificado", ranked: [], from_cache: false, registry_down: false,
    retry: false, picked: "io.github.evil/stripe-mcp", picked_is_trusted: false,
    message: "ojo: el conector oficial verificado es «com.stripe/mcp», distinto del que elegiste. Conecta el verificado." },
  outage: { service: "stripe", verdict: null, registry_status: "unreachable", server_name: null,
    vendor_kind: null, verified: false, score: null, reason: null, ranked: [],
    from_cache: false, registry_down: true, retry: true, picked: null, picked_is_trusted: null,
    message: "no puedo validar ahora — el catálogo público no responde. Reintenta ↻" },
};

/** Los frames del SSE, con el vocabulario EXACTO de `catalog_equip_router`. */
const SSE = {
  keyless: [
    { type: "dispatch.iniciado", service: "arxiv-search", server_name: "org.arxiv/search", free: true },
    { type: "resolver.buscando", service: "arxiv-search", registry: "registry.modelcontextprotocol.io" },
    { type: "resolver.encontrado", origin: "registry", server_name: "org.arxiv/search",
      vendor_kind: "dns", verified: true, from_cache: false, ranked: [] },
    { type: "curacion.probando", server: "org.arxiv/search", detail: "Compruebo que la herramienta responda." },
    { type: "mcp.equipado", origin: "registry", server: "org.arxiv/search",
      tools: ["search", "get_paper"], belt_ref: "synth_belts/x/belt.mcp.json", registered: true,
      tools_detail: [] },
    { type: "cerrado", path: "registry", ok: true, encontrado: true, forjado: false, server: "org.arxiv/search" },
  ],
  conLlave: [
    { type: "dispatch.iniciado", service: "stripe", server_name: "com.stripe/mcp", free: true },
    { type: "resolver.buscando", service: "stripe" },
    { type: "resolver.encontrado", origin: "registry", server_name: "com.stripe/mcp", verified: true },
    { type: "curacion.probando", server: "com.stripe/mcp" },
    { type: "mcp.equipado", origin: "registry", server: "com.stripe/mcp", tools: ["charge"],
      belt_ref: "synth_belts/y/belt.mcp.json", registered: true, tools_detail: [] },
    { type: "cerrado", path: "registry", ok: true, encontrado: true, forjado: false, server: "com.stripe/mcp" },
  ],
  registroCaido: [
    { type: "dispatch.iniciado", service: "zzz" },
    { type: "resolver.buscando", service: "zzz" },
    { type: "resolver.registry_down", reason: "No pude consultar el registro público ahora.", retry: true },
    { type: "cerrado", path: "registry_down", ok: false, encontrado: false, forjado: false,
      retry: true, cause: "registry_unreachable" },
  ],
  sinPruebaDeOrigen: [
    { type: "dispatch.iniciado", service: "pepita" },
    { type: "resolver.buscando", service: "pepita" },
    { type: "resolver.miss", reason: "Encontré una opción, pero no pude comprobar su procedencia.",
      rejected_impostor: false },
    { type: "cerrado", path: "miss", ok: false, encontrado: false, forjado: false,
      rejected_impostor: false, premium_available: true, cause: "no_confiable",
      cause_literal: "sin_prueba_de_origen", next: "traer_asi" },
  ],
  curacionRechazo: [
    { type: "dispatch.iniciado", service: "stripe" },
    { type: "resolver.buscando", service: "stripe" },
    { type: "resolver.encontrado", origin: "registry", server_name: "com.stripe/mcp", verified: true },
    { type: "curacion.probando", server: "com.stripe/mcp" },
    { type: "curacion.rechazo", stage: "curar", server: "com.stripe/mcp",
      detail: "La opción no pasó la comprobación." },
    { type: "cerrado", path: "curacion", ok: false, encontrado: true, forjado: false,
      server: "com.stripe/mcp", cause: "curacion_rechazo" },
  ],
  necesitaLlave: [
    { type: "dispatch.iniciado", service: "stripe" },
    { type: "resolver.buscando", service: "stripe" },
    { type: "resolver.encontrado", origin: "registry", server_name: "com.stripe/mcp", verified: true },
    { type: "curacion.probando", server: "com.stripe/mcp" },
    { type: "curacion.necesita_credencial", server: "com.stripe/mcp", service: "stripe",
      detail: "Esta opción necesita una credencial para comprobarla." },
    { type: "cerrado", path: "curacion", ok: false, encontrado: true, forjado: false,
      server: "com.stripe/mcp", cause: "needs_credential", next: "connect" },
  ],
  conReservas: [
    { type: "dispatch.iniciado", service: "pepita" },
    { type: "resolver.buscando", service: "pepita" },
    { type: "resolver.con_reservas", server_name: "com.pepita/mcp",
      reason: "No se pudo confirmar la identidad del namespace que publicó esta pieza." },
    { type: "curacion.probando", server: "com.pepita/mcp" },
    { type: "mcp.equipado", origin: "registry_with_reservation", server: "com.pepita/mcp",
      tools: ["read_site"], belt_ref: "synth_belts/z/belt.mcp.json", registered: true,
      reserva: { texto_1linea: "No se pudo confirmar la identidad del namespace que publicó esta pieza.",
                 detalle: "Señal del matcher: 0.515.", origen: "escrutinio_registro_publico" },
      tools_detail: [] },
    { type: "cerrado", path: "registry", ok: true, encontrado: true, forjado: false,
      server: "com.pepita/mcp", reserva: true },
  ],
};

/* ── EL BANCO · la sección montada sobre el DOM mínimo, con los verbos espiados ──────── */

/** Los controles que la SECCIÓN trae escritos en el HTML (no los pinta el adaptador). Se
 *  leen del archivo real para que la vara no pruebe un botón inventado por ella misma. */
function ESTATICOS_DE_LA_SECCION() {
  const html = readFileSync(join(D, "Conectores.dc.html"), "utf8");
  const m = html.match(/<a class="cx-back"[^>]*>[^<]*<\/a>/);
  return m ? m[0] : null;
}

function banco({ busqueda = BUSQUEDA_OK, veredicto = VALIDATE.confiable, frames = SSE.keyless,
                 crudo = { server: { name: "com.stripe/mcp", remotes: [] } },
                 modelos = [], vault = {} } = {}) {
  const espia = { buscar: [], validar: [], crudo: [], traer: [], noCoincide: 0, cargas: 0 };
  // ⚠️ ESTADO SE LIMPIA ENTRE BANCOS, y esto es la diferencia entre una vara y un adorno.
  // `ESTADO` es del MÓDULO: sin este reset, la `llegada` que dejó un bloque anterior sigue
  // ahí y el bloque siguiente la lee como propia. Medido: el testigo de «buscar mientras una
  // pieza viaja» pasaba en verde CON el bug reintroducido a mano, porque estaba leyendo la
  // llegada de otro caso. Una vara puede ser verde y no medir nada.
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
    conteoLlavero: host("keyringCount"),
    panelConectores: host("connectorsView"), panelLlavero: host("keyringView"),
    cabecera: host("cxHead"), tabs: host("cxTabs"),
    entradaCatalogo: host("cxCatalogEntry"), panelCatalogo: host("catalogView"),
    catalogoBuscador: host("cxCatalogSearch"), catalogoLista: host("cxCatalogList"),
    catalogoFicha: host("cxCatalogCard"), catalogoLlegada: host("cxCatalogArrival"),
    catalogoVista: host("cxCatalogPane"),
  };
  // La lista de la sección vive DENTRO del panel: es lo que hace que un click en una fila
  // burbujee hasta el único listener delegado. Si estuvieran sueltos, la vara probaría una
  // delegación que la pantalla real no tiene.
  for (const k of ["catalogoBuscador", "catalogoLista", "catalogoFicha", "catalogoLlegada",
                   "catalogoVista"]) {
    hosts[k].padre = hosts.panelCatalogo;
    hosts.panelCatalogo.hijos.push(hosts[k]);
  }
  hosts.catalogoLista.padre = hosts.catalogoVista;
  // LOS CONTROLES ESTÁTICOS DE LA SECCIÓN, tomados de la pantalla REAL. El «← Tus
  // conectores» no lo pinta el adaptador: vive en el HTML de `Conectores.dc.html`. Copiarlo
  // acá a mano sería probar un botón que yo mismo inventé; se extrae del archivo, así que si
  // alguien lo borra de la pantalla, esta vara se pone roja.
  const marca = ESTATICOS_DE_LA_SECCION();
  if (marca) {
    const est = document.createElement("div");
    est.innerHTML = marca;
    est.padre = hosts.panelCatalogo;
    hosts.panelCatalogo.hijos.push(est);
  }

  Object.assign(M.VERBOS, {
    cargar: async () => { espia.cargas++; return { modelos, vault, leido: true, alias: {} }; },
    barrerLocal: async () => false,
    medir: async () => false,
    buscarCatalogo: async (q) => { espia.buscar.push(q); return busqueda; },
    validarPieza: async (svc, srv) => { espia.validar.push([svc, srv]); return veredicto; },
    crudoDePieza: async (id) => { espia.crudo.push(id); return crudo ? { id, manifest: crudo, source: "registry" } : null; },
    traerPieza: async (args, alEvento) => {
      espia.traer.push(args);
      for (const f of frames) alEvento(f);
      return true;
    },
    noCoincide: async () => { espia.noCoincide++; return true; },
  });
  return { hosts, espia };
}

const esperar = () => new Promise((r) => setTimeout(r, 0));

console.log("\n══ OBRA 4 · LA SECCIÓN ══\n");

/* ══ 1 · DESDE CONECTORES SE LLEGA A LA SECCIÓN POR CLICK ═════════════════════════════ */
console.log("1 · la entrada existe por click");
{
  const { hosts } = banco();
  await M.montar(hosts);
  const antes = M.ESTADO.vista;
  await hosts.entradaCatalogo.click();
  paso("1_entrada_por_click",
    ok(antes === "conectores" && M.ESTADO.vista === "catalogo",
       "un click en [Catálogo público] abre la sección", `${antes} → ${M.ESTADO.vista}`));
  paso("1_entrada_por_click",
    ok(hosts.panelCatalogo.hidden === false && hosts.panelConectores.hidden === true,
       "la sección se muestra y el local se esconde"));
  // VOLVER ES UN CLICK, y no navega: es la misma pantalla cambiando de vista, así que ni la
  // búsqueda ni un viaje en curso se pierden al ir y venir.
  const volver = hosts.panelCatalogo.querySelector("[data-volver-conectores]");
  paso("1_entrada_por_click", ok(!!volver, "la sección tiene su «← Tus conectores»"));
  if (volver) {
    await volver.click();
    paso("1_entrada_por_click", ok(M.ESTADO.vista === "conectores",
      "…y un click en él vuelve al local, sin navegar", M.ESTADO.vista));
  }
}

/* ══ 2 · BUSCAR PINTA FILAS CON LOS CAMPOS REALES · EL ✓ SÓLO DEL PIN ═════════════════ */
console.log("\n2 · las filas, con los campos del contrato M1");
{
  const { hosts, espia } = banco();
  await M.montar(hosts);
  await hosts.entradaCatalogo.click();
  hosts.catalogoBuscador.value = "stripe";
  await M.VERBOS.buscarCatalogo && null;
  await window.__conectores.catalogo("stripe");
  const filas = hosts.catalogoLista.querySelectorAll("li.cat-fila");
  paso("2_filas_y_sello", ok(espia.buscar.includes("stripe"), "buscar consultó el registro", JSON.stringify(espia.buscar)));
  paso("2_filas_y_sello", ok(filas.length === 2, "una fila por ítem", `n=${filas.length}`));

  const texto = hosts.catalogoLista.textContent;
  // los campos REALES: nombre · voz · requisito · confianza · sello
  paso("2_filas_y_sello", ok(/Stripe/.test(texto), "el nombre"));
  paso("2_filas_y_sello", ok(/Payment tools/.test(texto), "la voz (description)"));
  paso("2_filas_y_sello", ok(/Pide tu llave/.test(texto) && /Pide una descarga/.test(texto),
    "el requisito, por tipo (llave · descarga)"));
  paso("2_filas_y_sello", ok(/0\.99/.test(texto) && /0\.54/.test(texto),
    "la confianza, la misma que el endpoint dio"));

  // [heredado de verify_registry.mjs (b2/b3) y verify_catalog_acceptance.mjs (c2/c3)]
  const conSello = filas.filter((f) => f.getAttribute("data-verificada") === "true");
  const sinSello = filas.filter((f) => f.getAttribute("data-verificada") === "false");
  paso("2_filas_y_sello", ok(conSello.length === 1 && sinSello.length === 1,
    "[heredado] el ✓ aparece en la pineada y sólo en ella", `sello=${conSello.length}`));
  paso("2_filas_y_sello", ok(/✓ oficial \(com\.stripe\)/.test(conSello[0].textContent),
    "[heredado] la pineada lleva ✓ oficial"));
  paso("2_filas_y_sello", ok(/publicado por github: evil/.test(sinSello[0].textContent)
    && !/✓/.test(sinSello[0].querySelector(".cat-sello").textContent),
    "[heredado] la no pineada dice «publicado por X» y NO lleva ✓"));
}

/* ══ 3 · TOCAR CORRE VALIDATE · LAS CUATRO CARAS ══════════════════════════════════════ */
console.log("\n3 · tocar una pieza corre validate, y cada desenlace tiene su cara");
{
  const { hosts, espia } = banco({ veredicto: VALIDATE.confiable });
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  const fila = hosts.catalogoLista.querySelector("button[data-elegir]");
  await fila.click();
  await esperar(); await esperar();
  paso("3_cuatro_caras", ok(espia.validar.length === 1,
    "un click en la fila corre validate — y UNO solo", JSON.stringify(espia.validar)));
  paso("3_cuatro_caras", ok(hosts.catalogoFicha.querySelector('[data-cara="verificada"]') != null,
    "…y pinta la ficha al lado"));
}
for (const [etiqueta, veredicto, cara, seña] of [
  ["verificada", VALIDATE.confiable, "verificada", /Traer/],
  ["con reservas", VALIDATE.dudoso, "con_reservas", /Traer así/],
  ["no se puede · inexistente", VALIDATE.nada, "no_se_puede", /Construir un MCP/],
  ["no se puede · impostor", VALIDATE.impostor, "no_se_puede", /Traer esta/],
  ["el registro no contestó", VALIDATE.outage, "sin_registro", /Reintentar/],
]) {
  const { hosts } = banco({ veredicto });
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar();
  const nodo = hosts.catalogoFicha.querySelector(`[data-cara="${cara}"]`);
  paso("3_cuatro_caras", ok(nodo != null && seña.test(hosts.catalogoFicha.textContent),
    `cara «${etiqueta}» → data-cara="${cara}" + su salida`,
    nodo ? "" : hosts.catalogoFicha.innerHTML.slice(0, 90)));
}
{
  // la línea MEDIDA de la reserva, no un adjetivo
  const { hosts } = banco({ veredicto: VALIDATE.dudoso });
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar();
  paso("3_cuatro_caras", ok(/sin prueba de dueño/.test(hosts.catalogoFicha.textContent),
    "«con reservas» dice QUÉ no se confirmó, medido (`reason`)"));
}

/* ══ 4 · EL AVISO DE CONSECUENCIAS, VISIBLE SIN INTERACCIÓN ═══════════════════════════ */
console.log("\n4 · el aviso se ve sin tocar nada, en la lista y en la ficha");
{
  const { hosts } = banco();
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  const avisos = hosts.catalogoLista.querySelectorAll(".cat-aviso");
  paso("4_aviso_sin_interaccion", ok(avisos.length === 2,
    "cada fila trae su franja de aviso, sin desplegar nada", `n=${avisos.length}`));
  paso("4_aviso_sin_interaccion",
    ok(/escriben y borran/.test(avisos[0].textContent),
       "la que declara: los verbos que declaró", avisos[0].textContent.slice(0, 60)));
  paso("4_aviso_sin_interaccion",
    ok(/se sabrá al conectar/.test(avisos[1].textContent),
       "la que NO declara: «se sabrá al conectar»", avisos[1].textContent.slice(0, 60)));
  paso("4_aviso_sin_interaccion",
    ok(avisos[0].classList.contains("pesa") && !avisos[1].classList.contains("pesa"),
       "sólo pesa la que declara algo que escribe, envía o borra"));

  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar();
  paso("4_aviso_sin_interaccion",
    ok(hosts.catalogoFicha.querySelector(".cat-aviso-bloque") != null
       && /escriben y borran/.test(hosts.catalogoFicha.textContent),
       "y en la ficha, también sin desplegar"));
}

/* ══ 5 · EL [?] · EL CRUDO DE UNA PIEZA ══════════════════════════════════════════════ */
console.log("\n5 · el [?] trae el crudo de UNA pieza");
{
  // con sello: NO se auto-abre; se abre por click y pide UN manifest
  const { hosts, espia } = banco({ veredicto: VALIDATE.confiable });
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar();
  paso("5_crudo_de_una", ok(espia.crudo.length === 0,
    "con sello, el crudo NO se pide solo", JSON.stringify(espia.crudo)));
  const q = hosts.catalogoFicha.querySelector("button[data-crudo]");
  paso("5_crudo_de_una", ok(!!q, "el [?] existe en la ficha"));
  await q.click(); await esperar(); await esperar();
  paso("5_crudo_de_una", ok(espia.crudo.length === 1,
    "un click pide el crudo de UNA pieza, no de la lista", JSON.stringify(espia.crudo)));
  paso("5_crudo_de_una", ok(hosts.catalogoFicha.querySelector(".cat-crudo") != null,
    "…y lo pinta"));
  const nc = hosts.catalogoFicha.querySelector("button[data-no-coincide]");
  paso("5_crudo_de_una", ok(!!nc, "[Esto no coincide] existe"));
  await nc.click(); await esperar();
  paso("5_crudo_de_una", ok(espia.noCoincide === 1,
    "…y dispara su reporte", `n=${espia.noCoincide}`));
}
{
  // SIN sello: se auto-abre, y sin que nadie lo pida
  const { hosts, espia } = banco({ busqueda: { ...BUSQUEDA_OK, items: [ITEM_SIN_SELLO] },
                                   veredicto: VALIDATE.dudoso });
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar(); await esperar();
  paso("5_crudo_de_una", ok(espia.crudo.length === 1
    && hosts.catalogoFicha.querySelector(".cat-crudo") != null,
    "sin sello de origen, el crudo se abre SOLO", `pedidos=${espia.crudo.length}`));
}

/* ══ 6 · EL VIAJE · los eventos reales, y la detención en el culpable ═════════════════ */
console.log("\n6 · [Traer] pinta el viaje con los eventos del stream");
async function viaje(frames, veredicto = VALIDATE.confiable, busqueda = BUSQUEDA_OK) {
  const { hosts, espia } = banco({ frames, veredicto, busqueda });
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar(); await esperar();
  const btn = hosts.catalogoFicha.querySelector("button[data-traer]");
  if (btn) { await btn.click(); await esperar(); await esperar(); await esperar(); }
  return { hosts, espia, btn };
}
{
  const { hosts, espia } = await viaje(SSE.keyless);
  paso("6_viaje_se_detiene", ok(espia.traer.length === 1,
    "un click en [Traer] dispara el equip", JSON.stringify(espia.traer)));
  // los pasos son TRES, los que el sistema corre — no cinco dibujados
  paso("6_viaje_se_detiene", ok(C.PASOS_DEL_VIAJE.length === 3,
    "el viaje tiene los pasos que el stream permite: 3", C.PASOS_DEL_VIAJE.join(" → ")));
}
for (const [etiqueta, frames, pasoCulpable, señaCausa, botón] of [
  ["registro caído", SSE.registroCaido, "resolver", /no contestó/i, "[data-reintentar-viaje]"],
  ["sin prueba de origen", SSE.sinPruebaDeOrigen, "resolver", /quién es|de quien dice ser/i, "[data-traer-asi]"],
  ["la curación rechaza", SSE.curacionRechazo, "comprobar", /no pasó la comprobación/i, "[data-reintentar-viaje]"],
  ["pide tu llave", SSE.necesitaLlave, "comprobar", /Pide tu llave/i, "[data-traer-con-llave]"],
]) {
  const { hosts } = await viaje(frames);
  const pasos = hosts.catalogoFicha.querySelectorAll("li.cat-paso");
  const roto = pasos.find((p) => p.getAttribute("data-estado") === "roto");
  const idRoto = roto && roto.getAttribute("data-paso");
  const iRoto = pasos.findIndex((p) => p === roto);
  const posteriores = pasos.slice(iRoto + 1);
  paso("6_viaje_se_detiene", ok(idRoto === pasoCulpable,
    `«${etiqueta}» se detiene en el paso culpable (${pasoCulpable})`, `roto=${idRoto}`));
  paso("6_viaje_se_detiene", ok(roto != null && señaCausa.test(roto.textContent),
    `«${etiqueta}» dice la causa, con copy y sin jerga`,
    roto ? roto.textContent.replace(/\s+/g, " ").slice(0, 70) : ""));
  paso("6_viaje_se_detiene", ok(hosts.catalogoFicha.querySelector(botón) != null,
    `«${etiqueta}» ofrece su salida (${botón})`));
  paso("6_viaje_se_detiene",
    ok(posteriores.every((p) => /no llegamos acá/.test(p.textContent)),
       `«${etiqueta}»: los pasos posteriores dicen que no corrieron`));
}
{
  // ninguna causa muda, y ninguna en jerga: el barrido contra las causas REALES del router
  const reales = ["registry_unreachable", "no_confiable", "curacion_rechazo", "needs_credential",
                  "sin_red", "sin_sesion", "estado_local_no_escribible",
                  "sin_prueba_de_origen", "candidato_distinto_del_oficial",
                  // las cuatro finas del saneamiento (selladas 2026-08-07): partieron
                  // `curacion_rechazo`, que las decía a todas con la misma frase.
                  "servicio_inexistente", "servicio_no_responde",
                  "credencial_no_declarada", "sin_herramientas"];
  const sinCopy = reales.filter((c) => !SC.causaDe(c));
  const conJerga = reales.filter((c) => (SC.causaDe(c).texto || "").includes(c));
  paso("6_viaje_se_detiene", ok(sinCopy.length === 0,
    "TODAS las causas del router tienen copy", sinCopy.join(",")));
  paso("6_viaje_se_detiene", ok(conJerga.length === 0,
    "…y ninguna muestra su nombre técnico", conJerga.join(",")));
  const inventada = SC.causaDe("causa_que_no_existe_todavia");
  paso("6_viaje_se_detiene", ok(inventada && inventada.texto && inventada.provisional === true,
    "una causa desconocida sale provisional, no muda ni cruda", JSON.stringify(inventada)));
}

{
  // ⚠️ EL TESTIGO QUE CAZÓ UN BUG REAL DURANTE LA OBRA. La sección le promete al usuario
  // «podés irte a otra pantalla: seguimos igual y te lo contamos acá». Con UNA sola
  // generación para la búsqueda y el viaje, escribir en el buscador mientras una pieza
  // viajaba invalidaba el viaje: el backend terminaba de equipar, y la pantalla no
  // repintaba, no recargaba y no acusaba la llegada. La pieza entraba a tu local y nadie te
  // lo decía. Buscar y traer pasan a la vez A PROPÓSITO; cancelar una no puede cancelar la
  // otra.
  const llegada = {
    entityId: "org.arxiv/search", nombre: "org.arxiv/search",
    veredicto: { estado: "conectado" }, pertenencia: { local: true, faltan: [] },
    pasos: [], evidencia: {}, conocimiento: {}, header: {},
  };
  let soltar;
  const { hosts } = banco({ frames: SSE.keyless, modelos: [llegada] });
  const traerReal = M.VERBOS.traerPieza;
  M.VERBOS.traerPieza = async (args, alEvento) => {
    // el stream se corta a la mitad y se retoma DESPUÉS de que el usuario siga buscando
    for (const f of SSE.keyless.slice(0, 3)) alEvento(f);
    await new Promise((r) => { soltar = r; });
    for (const f of SSE.keyless.slice(3)) alEvento(f);
    return true;
  };
  await M.montar(hosts);
  await window.__conectores.catalogo("arxiv");
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar(); await esperar();
  const traer = hosts.catalogoFicha.querySelector("button[data-traer]");
  const enVuelo = traer.click();          // NO se espera: queda a mitad del stream
  for (let i = 0; i < 3; i++) await esperar();
  await window.__conectores.catalogo("otra cosa");   // el usuario sigue buscando
  soltar();
  await enVuelo;
  for (let i = 0; i < 6; i++) await esperar();
  paso("6_viaje_se_detiene", ok(M.ESTADO.catalogo.llegada != null,
    "buscar mientras una pieza viaja NO abandona el viaje en silencio",
    JSON.stringify(M.ESTADO.catalogo.llegada)));
  M.VERBOS.traerPieza = traerReal;
}

/* ══ 7 · EL ATERRIZAJE · lo decide `pertenencia()`, no la sección ═════════════════════ */
console.log("\n7 · dónde aterriza la pieza lo dice el clasificador");
{
  // el stub devuelve, tras la recarga, una pieza que TODAVÍA espera su llave
  const enAduana = {
    entityId: "com.stripe/mcp", nombre: "Stripe",
    veredicto: { estado: "esperando" }, pertenencia: { local: false, faltan: ["llave"], motivo: "falta la llave" },
    pasos: [], evidencia: {}, conocimiento: {}, header: {},
  };
  const { hosts } = banco({ frames: SSE.conLlave, modelos: [enAduana] });
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar(); await esperar();
  await hosts.catalogoFicha.querySelector("button[data-traer]").click();
  for (let i = 0; i < 6; i++) await esperar();
  paso("7_aterrizaje", ok(M.ESTADO.catalogo.llegada != null,
    "con final feliz, la sección acusa la llegada"));
  paso("7_aterrizaje", ok(M.ESTADO.catalogo.llegada && M.ESTADO.catalogo.llegada.escala === true,
    "una pieza que espera algo tuyo aterriza CON escala (En preparación)",
    JSON.stringify(M.ESTADO.catalogo.llegada)));
  // ⚠️ EL AVISO CHICO ES AHORA EL RASTRO, NO EL ANUNCIO. Desde «el final del viaje» (C) el
  // desenlace lo cuenta el panel del viaje, que además dice dónde quedó la pieza y ofrece el
  // camino; el aviso aparece cuando el usuario CIERRA. Tenerlos juntos era decir lo mismo dos
  // veces. Se aprieta la ✕ y recién ahí se exige el aviso — el testigo salió reforzado: ahora
  // también prueba que el acuse SOBREVIVE al cierre.
  const equis = hosts.catalogoFicha.querySelector("button[data-cerrar-viaje]");
  paso("7_aterrizaje", ok(!!equis, "el viaje terminado se cierra con su ✕, no solo"));
  if (equis) { await equis.click(); await esperar(); }
  paso("7_aterrizaje", ok(/En preparación/.test(hosts.catalogoLlegada.textContent),
    "…y lo dice con el vocabulario de la casa", hosts.catalogoLlegada.textContent.slice(0, 70)));
  // y la aduana REAL la muestra: la misma sección de siempre, derivada de la fila
  paso("7_aterrizaje", ok(S.piezasDeAduana([enAduana]).length === 1,
    "la aduana real la reconoce (derivada de la fila, no de la sección)"));
}
{
  const enLocal = {
    entityId: "org.arxiv/search", nombre: "org.arxiv/search",
    veredicto: { estado: "conectado" }, pertenencia: { local: true, faltan: [] },
    pasos: [], evidencia: {}, conocimiento: {}, header: {},
  };
  const { hosts } = banco({ frames: SSE.keyless, modelos: [enLocal] });
  await M.montar(hosts);
  await window.__conectores.catalogo("arxiv");
  await hosts.catalogoLista.querySelector("button[data-elegir]").click();
  await esperar(); await esperar(); await esperar();
  await hosts.catalogoFicha.querySelector("button[data-traer]").click();
  for (let i = 0; i < 6; i++) await esperar();
  paso("7_aterrizaje", ok(M.ESTADO.catalogo.llegada && M.ESTADO.catalogo.llegada.escala === false,
    "una keyless entra SIN escala, directo al local",
    JSON.stringify(M.ESTADO.catalogo.llegada)));
  const equis2 = hosts.catalogoFicha.querySelector("button[data-cerrar-viaje]");
  if (equis2) { await equis2.click(); await esperar(); }
  paso("7_aterrizaje", ok(/No pidió nada/.test(hosts.catalogoLlegada.textContent),
    "…y se dice así"));
}

/* ══ 8 · LA MISMA CARD DE LAS 41 · y la reserva sin tocar el semáforo ════════════════ */
console.log("\n8 · la pieza traída usa la card de siempre");
{
  // ASSERT DE IDENTIDAD: la sección NO define una card. Si la definiera, habría dos formas
  // de mostrar una pieza — que es exactamente lo que el adaptador vino a matar.
  paso("8_misma_card", ok(typeof SC.pintarFila === "function" && SC.pintarCard === undefined,
    "la sección no define su propia card de pieza equipada"));

  const base = {
    entityId: "com.pepita/mcp", nombre: "Pepita",
    veredicto: { estado: "conectado", bloqueo: "ninguno", fuente: "registro" },
    pertenencia: { local: true, faltan: [] }, pasos: [], evidencia: { estado: "viva" },
    conocimiento: {}, credencial: {}, header: { ts: "2026-08-05T12:00:00Z" }, trazas: [],
  };
  const traida = { ...base, reserva: {
    texto_1linea: "No se pudo confirmar la identidad del namespace que publicó esta pieza.",
    detalle: "Señal del matcher: 0.515.", origen: "escrutinio_registro_publico" } };

  const cardSinReserva = S.pintarCard(base);
  const cardConReserva = S.pintarCard(traida);
  paso("8_misma_card", ok(cardSinReserva === cardConReserva,
    "la card de una pieza traída es BYTE A BYTE la de cualquier otra"));

  const semSin = /data-estado="([^"]+)"/.exec(cardSinReserva)[1];
  const semCon = /data-estado="([^"]+)"/.exec(cardConReserva)[1];
  paso("8_misma_card", ok(semSin === semCon && semCon === "conectado",
    "la reserva NO cambia el semáforo", `${semSin} vs ${semCon}`));

  const panel = S.pintarPanel(traida);
  paso("8_misma_card", ok(/cx-reserva/.test(panel)
    && /no se pudo confirmar la identidad/i.test(panel),
    "…y sí se ve, en el panel, con el aviso guardado al traerla"));
  paso("8_misma_card", ok(!/cx-reserva/.test(S.pintarPanel(base)),
    "una pieza sin reserva no muestra el bloque"));
}

/* ══ 9 · LOS TRES BORDES, DISTINGUIBLES ══════════════════════════════════════════════ */
console.log("\n9 · los tres bordes de la lista se distinguen");
{
  const casos = [
    ["vacio", "", null, /Escribí qué necesitás/, /Construir un MCP/],
    ["caido", "stripe", BUSQUEDA_CAIDA, /no pudimos preguntar|no responde/i, /Reintentar/],
    ["sin_resultados", "crm de la ferretería", BUSQUEDA_VACIA, /no hay ninguna pieza/i, /Construir un MCP/],
  ];
  const vistos = [];
  for (const [borde, q, busqueda, seña, salida] of casos) {
    const { hosts } = banco({ busqueda });
    await M.montar(hosts);
    await window.__conectores.catalogo(q);
    const nodo = hosts.catalogoLista.querySelector(`[data-borde="${borde}"]`);
    vistos.push(hosts.catalogoLista.innerHTML);
    paso("9_tres_bordes", ok(nodo != null, `borde «${borde}» se pinta con su propia marca`));
    paso("9_tres_bordes", ok(nodo != null && seña.test(nodo.textContent),
      `borde «${borde}» dice POR QUÉ está vacío`, nodo ? nodo.textContent.slice(0, 60) : ""));
    paso("9_tres_bordes", ok(nodo != null && salida.test(nodo.textContent),
      `borde «${borde}» ofrece su salida`));
  }
  paso("9_tres_bordes", ok(new Set(vistos).size === 3,
    "los tres se ven DISTINTO (ninguno se confunde con otro)", `únicos=${new Set(vistos).size}`));
  // [heredado de verify_catalog_acceptance.mjs (a)] outage → banner honesto y CERO card de
  // construir: decirle «no existe» a alguien porque no pudimos preguntar es el peor bug acá.
  const { hosts } = banco({ busqueda: BUSQUEDA_CAIDA });
  await M.montar(hosts);
  await window.__conectores.catalogo("stripe");
  paso("9_tres_bordes", ok(!/Construir un MCP/.test(hosts.catalogoLista.textContent),
    "[heredado] en outage NO se ofrece construir (no sabemos si existe)"));
}

/* ══ 10 · EL ENTIERRO ════════════════════════════════════════════════════════════════ */
console.log("\n10 · lo viejo está enterrado, y el wizard sigue vivo");
{
  const conectar = readFileSync(join(D, "Conectar.dc.html"), "utf8");
  const conectores = readFileSync(join(D, "Conectores.dc.html"), "utf8");
  const cuarto = readFileSync(join(D, "cuarto/cuarto.pixi.html"), "utf8");

  paso("10_entierro", ok(!/id="regGrid"|id="regWrap"/.test(conectar),
    "Conectar: el bloque del registro público ya no existe"));
  paso("10_entierro", ok(!/function searchRegistry|function renderRegistry|async function curateEquip/.test(conectar),
    "Conectar: sus funciones tampoco"));
  paso("10_entierro", ok(!/catalogo=publico"\)?\s*\)?\s*return/.test(conectar)
    && /old\.get\("c"\)\)\s*return/.test(conectar),
    "Conectar: el shim ya no exceptúa ?catalogo=publico — exceptúa el wizard"));
  paso("10_entierro", ok(/next\.set\("catalogo", "publico"\)/.test(conectar),
    "…y ?catalogo=publico se reenvía a Conectores, no muere en un dead-end"));
  paso("10_entierro", ok(/catalogo.*===\s*"publico"/.test(conectores)
    && /__conectores\.catalogo\(/.test(conectores),
    "Conectores atiende ese deep-link y abre la sección"));

  // EL WIZARD SIGUE VIVO: sus funciones están, y su puerta también
  for (const fn of ["function openWizard", "async function doConnect", "function show",
                    "async function ensureSession", "function serviceFace", "async function loadList"])
    paso("10_entierro", ok(conectar.includes(fn), `el wizard conserva \`${fn.split(" ").pop()}\``));
  paso("10_entierro", ok(/if\(c\) openWizard\(c\)/.test(conectar),
    "…y ?c=<conector> sigue abriéndolo"));
  paso("10_entierro", ok(/oa==='ok'/.test(conectar) && /old\.get\("c"\)\)\s*return/.test(conectar),
    "…y la vuelta de OAuth llega hasta él (antes la comía el shim)"));

  paso("10_entierro", ok(!/id="registryPanel"/.test(cuarto),
    "el registryPanel del Cuarto murió como superficie"));
  paso("10_entierro", ok(!/const fetchCatalog|const renderRegistry|const pickCatalog/.test(cuarto),
    "…con su búsqueda, su render y su teclado"));
  paso("10_entierro", ok(/__cuartoCatalog = \{/.test(cuarto)
    && /Conectores\.dc\.html\?" \+ qs/.test(cuarto),
    "…pero su API redirige a la sección: la Guía no se rompe"));
  paso("10_entierro", ok(/_doConnect: \(server, service\) => doConnect\(server, service\)/.test(cuarto),
    "…y el carril libre queda intacto"));
  for (const muerta of ["cuarto/verify_registry.mjs", "cuarto/verify_catalog_acceptance.mjs"])
    paso("10_entierro", ok(!existsSync(join(D, muerta)),
      `la vara del panel enterrado se retiró (${muerta.split("/").pop()})`));
}

/* ══ 11 · CERO STRINGS POR-CONECTOR EN EL CÓDIGO NUEVO ═══════════════════════════════ */
console.log("\n11 · ni un nombre de conector en el código de la sección");
{
  // EL MISMO GUARD QUE `verify_superficie_montada.mjs`, sobre los archivos nuevos: los
  // nombres REALES de servidor de TODO el catálogo (`*.mcp.json`) más las fichas de
  // onboarding. Si alguno aparece entre comillas en el código, es contenido hardcodeado —
  // escala a una pieza y muere en las 17.000.
  const nombres = new Set();
  const pila = [join(RAIZ, "catalog")];
  while (pila.length) {
    const dir = pila.pop();
    if (!existsSync(dir)) continue;
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      if (e.isDirectory()) pila.push(p);
      else if (e.name.endsWith(".mcp.json")) {
        try { for (const s of Object.keys(JSON.parse(readFileSync(p, "utf8")).mcpServers || {})) nombres.add(s); }
        catch (_) { /* un belt ilegible no puede tumbar el guard */ }
      } else if (dir.endsWith("onboarding") && e.name.endsWith(".json"))
        nombres.add(e.name.replace(/\.json$/, ""));
    }
  }
  const sospechosos = [...nombres].filter((s) => s.length > 4);
  for (const archivo of ["conectores/catalogo.js", "conectores/superficie-catalogo.js"]) {
    const src = readFileSync(join(D, archivo), "utf8");
    // los comentarios se descartan: nombrar un conector para explicar un bug histórico es
    // documentación, no una decisión de render. Es el mismo corte que hace la vara hermana.
    const cuerpo = src.split("\n").filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join("\n");
    const hits = sospechosos.filter((s) => new RegExp(`["'\`]${s}["'\`]`).test(cuerpo));
    paso("11_cero_por_conector", ok(hits.length === 0,
      `${archivo}: cero nombres de conector · (probado contra ${sospechosos.length})`,
      hits.slice(0, 5).join(", ")));
  }
  // y la capa que lee no escribe texto de usuario
  const catalogo = readFileSync(join(D, "conectores/catalogo.js"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const frases = catalogo.match(/["'`][^"'`]{25,}["'`]/g) || [];
  const conTexto = frases.filter((f) => /\s(de|la|el|que|los|tu|your|the|that)\s/i.test(f)
                                     && !/^["'`]\/v1\//.test(f));
  paso("11_cero_por_conector", ok(conTexto.length === 0,
    "catalogo.js no escribe un solo texto de usuario", conTexto.slice(0, 2).join(" | ")));
}

/* ══ 14 · EL FILTRO POR REQUISITO ════════════════════════════════════════════════════
 *
 * GUARD DE ALCANZABILIDAD: cada testigo APRIETA el chip que la superficie emitió. No alcanza
 * con que `aplicarFiltro` devuelva bien —eso es la mitad—: el bug que esto previene es un
 * filtro que existe en el modelo y no tiene un botón que lo alcance, o que lo tiene y no está
 * cableado. Se mide sobre el DOM real, con clicks reales.
 * ════════════════════════════════════════════════════════════════════════════════════ */
console.log("\n14 · el filtro por requisito");

// Cuatro piezas, TRES requisitos, y `llave` repetida: sin repetición el conteo «2» no se
// puede distinguir de un «1» y el testigo de los conteos no probaría nada.
const _it = (id, requisito, nombre) => ({
  id, name: nombre, description: "x", source: "registry",
  badge: { kind: "registry_publisher", label: "publicado por x", verified: false,
           vendor_kind: "github_org", namespace: "io.github.x", publisher: "x" },
  score: 0.5, server_name: id, requisito, fecha_ingesta: null, confianza: 0.5,
  consecuencias: "se_sabra_al_conectar", referencia_crudo: null,
});
const BUSQUEDA_FILTRO = {
  query: "n", source: "registry", registry_status: "ok", internal_status: "ok",
  items: [_it("v/uno", "llave", "Uno"), _it("v/dos", "llave", "Dos"),
          _it("v/tres", "descarga", "Tres"), _it("v/cuatro", "click", "Cuatro")],
  counts: { internal: 0, registry: 4, total: 4 }, notice: null,
};

async function bancoFiltro(busqueda = BUSQUEDA_FILTRO) {
  const { hosts, espia } = banco({ busqueda });
  await M.montar(hosts);
  await window.__conectores.catalogo("n");
  await esperar();
  return { hosts, espia };
}
const chips = (hosts) => [...hosts.catalogoLista.querySelectorAll("[data-filtro]")];
const filas = (hosts) => [...hosts.catalogoLista.querySelectorAll("li.cat-fila")];
const reqs  = (hosts) => filas(hosts).map((li) => li.dataset.requisito).sort();

/* ── 14.1 · las opciones son DERIVADAS, con sus conteos ─────────────────────────────── */
{
  const { hosts } = await bancoFiltro();
  const cs = chips(hosts);
  const leidos = cs.map((c) => `${c.dataset.filtro}:${c.querySelector(".cat-chip-n").textContent}`);
  paso("14_filtro", ok(leidos.join(" ") === "click:1 llave:2 descarga:1 ninguno:0",
    "las opciones con el conteo REAL, en el orden de REQUISITO()", leidos.join(" ")));
  // NEGATIVO — el conteo sale de los datos, no de una tabla: «ninguno» está en CERO porque
  // ninguna de las 4 lo pide, y se ve atenuado. Un conteo escrito a mano no podría distinguir
  // el 2 de llave del 1 de click.
  const cero = cs.find((c) => c.dataset.filtro === "ninguno");
  // `className` no existe en el DOM mínimo; el atributo sí. Se lee por donde el banco puede.
  paso("14_filtro", ok(cero.dataset.cuenta === "0"
    && /\bvacio\b/.test(cero.getAttribute("class") || ""),
    "y la que NADIE pide se ofrece en cero y atenuada — no mentida",
    cero.getAttribute("class")));
}

/* ── 14.2 · filtrar por llave deja las de llave; multi-selección SUMA ───────────────── */
{
  const { hosts } = await bancoFiltro();
  paso("14_filtro", ok(filas(hosts).length === 4, "[antes] las 4 están"));
  await chips(hosts).find((c) => c.dataset.filtro === "llave").click();
  await esperar();
  paso("14_filtro", ok(filas(hosts).length === 2 && reqs(hosts).join() === "llave,llave",
    "un click en «Llave» deja SÓLO las de llave", reqs(hosts).join()));
  await chips(hosts).find((c) => c.dataset.filtro === "click").click();
  await esperar();
  paso("14_filtro", ok(filas(hosts).length === 3
    && reqs(hosts).join() === "click,llave,llave",
    "sumar «Click» SUMA, no reemplaza", reqs(hosts).join()));
  // los conteos NO se mueven al filtrar: si se derivaran del resultado filtrado, el usuario
  // quedaría encerrado en su primer chip.
  const leidos = chips(hosts).map((c) => c.querySelector(".cat-chip-n").textContent).join();
  paso("14_filtro", ok(leidos === "1,2,1,0", "y los conteos siguen siendo los del universo", leidos));
  // NEGATIVO — destildar el mismo chip lo saca: es toggle, no acumulador.
  await chips(hosts).find((c) => c.dataset.filtro === "click").click();
  await esperar();
  paso("14_filtro", ok(filas(hosts).length === 2, "destildar vuelve atrás"));
}

/* ── 14.3 · se VE que hay filtro puesto, y se limpia de un click ────────────────────── */
{
  const { hosts } = await bancoFiltro();
  const antes = hosts.catalogoLista.querySelector(".cx-number").textContent;
  await chips(hosts).find((c) => c.dataset.filtro === "llave").click();
  await esperar();
  const conFiltro = hosts.catalogoLista.querySelector(".cx-number");
  paso("14_filtro", ok(/2\s*de\s*4/.test(conFiltro.textContent)
    && conFiltro.dataset.filtrado === "true",
    "con filtro el contador dice «2 de 4», no «2 encontradas»", conFiltro.textContent));
  paso("14_filtro", ok(/4/.test(antes) && !/de/.test(antes),
    "[negativo] sin filtro decía «4 encontradas»", antes));
  const chipOn = chips(hosts).find((c) => c.dataset.filtro === "llave");
  paso("14_filtro", ok(chipOn.getAttribute("aria-pressed") === "true",
    "el chip puesto lo dice por aria-pressed, no sólo por color"));
  const limpiar = hosts.catalogoLista.querySelector("[data-filtro-limpiar]");
  paso("14_filtro", ok(limpiar != null, "…y hay UN botón para quitarlo"));
  await limpiar.click();
  await esperar();
  paso("14_filtro", ok(filas(hosts).length === 4
    && hosts.catalogoLista.querySelector(".cx-number").dataset.filtrado === undefined,
    "un click lo limpia y vuelven las 4"));
}

/* ── 14.4 · el vacío por FILTRO es su propio estado ─────────────────────────────────── */
{
  // se pide un requisito que ninguna de las 4 tiene → hay piezas, las tapa el filtro
  const { hosts } = await bancoFiltro();
  await chips(hosts).find((c) => c.dataset.filtro === "descarga").click();
  await esperar();
  await chips(hosts).find((c) => c.dataset.filtro === "descarga").click();  // limpio
  await esperar();
  // para forzar el vacío se filtra por «click» sobre una búsqueda sin clicks
  const soloLlave = { ...BUSQUEDA_FILTRO,
    items: [_it("v/uno", "llave", "Uno"), _it("v/dos", "descarga", "Dos")] };
  const b2 = await bancoFiltro(soloLlave);
  await chips(b2.hosts).find((c) => c.dataset.filtro === "descarga").click();
  await esperar();
  await chips(b2.hosts).find((c) => c.dataset.filtro === "llave").click();
  await esperar();
  await chips(b2.hosts).find((c) => c.dataset.filtro === "descarga").click();
  await esperar();
  const soloDescarga = b2.hosts.catalogoLista.querySelectorAll("li.cat-fila").length;
  paso("14_filtro", ok(soloDescarga === 1, "control: filtrar deja 1", String(soloDescarga)));

  // LOS TRES VACÍOS, uno al lado del otro. Es el punto entero: tienen que SENTIRSE distintos.
  const bordeDe = async (busqueda, clicks = []) => {
    const { hosts } = await bancoFiltro(busqueda);
    for (const c of clicks) {
      const chip = chips(hosts).find((x) => x.dataset.filtro === c);
      if (chip) { await chip.click(); await esperar(); }
    }
    const n = hosts.catalogoLista.querySelector("[data-borde]");
    return { borde: n ? n.dataset.borde : null, texto: hosts.catalogoLista.textContent };
  };
  const vFiltro = await bordeDe({ ...BUSQUEDA_FILTRO,
    items: [_it("v/uno", "llave", "Uno"), _it("v/dos", "descarga", "Dos")] }, ["llave", "llave"]);
  // (dos clicks al mismo chip lo dejan limpio; para el vacío real filtramos por uno ausente)
  const sinClicks = { ...BUSQUEDA_FILTRO,
    items: [_it("v/uno", "llave", "Uno"), _it("v/dos", "llave", "Dos")] };
  const b3 = await bancoFiltro(sinClicks);
  // con un solo requisito PRESENTE el filtro NO se ofrece: filtrar no separaría a nadie
  paso("14_filtro", ok(chips(b3.hosts).length === 0,
    "[negativo] con un solo requisito presente, el filtro no se ofrece"));

  const vBusqueda = await bordeDe(BUSQUEDA_VACIA);
  const vCaido = await bordeDe(BUSQUEDA_CAIDA);
  // EL CAMINO AL VACÍO es el chip en CERO — el que existe justamente para que este estado
  // se pueda alcanzar. Con opciones sólo-de-los-presentes esto era imposible y el borde era
  // código muerto; lo destapó esta vara.
  const b4 = await bancoFiltro();
  await chips(b4.hosts).find((c) => c.dataset.filtro === "ninguno").click();
  await esperar();
  const nb = b4.hosts.catalogoLista.querySelector("[data-borde]");
  const vacioFiltro = { borde: nb ? nb.dataset.borde : null,
                        texto: b4.hosts.catalogoLista.textContent };
  paso("14_filtro", ok(vacioFiltro.borde === "filtro_vacio",
    "el vacío por filtro tiene su PROPIO data-borde", String(vacioFiltro.borde)));
  const tres = new Set([vacioFiltro.borde, vBusqueda.borde, vCaido.borde]);
  paso("14_filtro", ok(tres.size === 3 && tres.has("sin_resultados") && tres.has("caido"),
    "y los tres vacíos son TRES estados distintos", [...tres].join(" · ")));
  paso("14_filtro", ok(/Llegaron 4/.test(vacioFiltro.texto)
    && !/Construir un MCP/.test(vacioFiltro.texto),
    "dice cuántas hay detrás y NO ofrece construir lo que ya llegó"));
  paso("14_filtro", ok(/no hay ninguna pieza/.test(vBusqueda.texto),
    "[negativo] el vacío por búsqueda sí dice que no existe"));
}

/* ── 14.5 · filtrar NO dispara búsqueda ni escribe nada ─────────────────────────────── */
{
  const { hosts, espia } = await bancoFiltro();
  const antes = espia.buscar.length;
  const genAntes = M.ESTADO.catalogo.gen;
  await chips(hosts).find((c) => c.dataset.filtro === "llave").click();
  await esperar();
  await chips(hosts).find((c) => c.dataset.filtro === "click").click();
  await esperar();
  await hosts.catalogoLista.querySelector("[data-filtro-limpiar]").click();
  await esperar();
  paso("14_filtro", ok(espia.buscar.length === antes,
    "tres cambios de filtro y CERO búsquedas nuevas", `${antes} → ${espia.buscar.length}`));
  paso("14_filtro", ok(M.ESTADO.catalogo.gen === genAntes,
    "y la generación de la búsqueda no se toca"));
  // NEGATIVO — el espía SÍ cuenta cuando de verdad se busca: si no, el testigo de arriba
  // saldría verde con un espía roto.
  await window.__conectores.catalogo("otra");
  await esperar();
  paso("14_filtro", ok(espia.buscar.length === antes + 1,
    "[negativo] buscar de verdad SÍ suma una llamada"));
  paso("14_filtro", ok(M.ESTADO.catalogo.filtro.length === 0,
    "y una búsqueda nueva limpia el filtro: no es una preferencia"));
}

/* ── 14.6 · la ficha abierta no queda huérfana ──────────────────────────────────────── */
{
  const { hosts } = await bancoFiltro();
  await hosts.catalogoLista.querySelector('[data-elegir="v/uno"]').click();  // una de LLAVE
  await esperar(); await esperar();
  paso("14_filtro", ok(M.ESTADO.catalogo.elegida === "v/uno" && !!M.ESTADO.catalogo.ficha,
    "[antes] la ficha de una pieza de llave está abierta"));
  // el filtro la CONSERVA si su pieza sigue visible
  await chips(hosts).find((c) => c.dataset.filtro === "llave").click();
  await esperar();
  paso("14_filtro", ok(M.ESTADO.catalogo.elegida === "v/uno" && !!M.ESTADO.catalogo.ficha,
    "filtrar por «Llave» la CONSERVA: su pieza sigue en la lista"));
  // y la CIERRA si la saca — una ficha al lado de una lista que no la contiene es huérfana
  await chips(hosts).find((c) => c.dataset.filtro === "llave").click();
  await esperar();
  await chips(hosts).find((c) => c.dataset.filtro === "click").click();
  await esperar();
  paso("14_filtro", ok(M.ESTADO.catalogo.elegida == null && M.ESTADO.catalogo.ficha == null,
    "filtrar por «Click» la CIERRA: el filtro sacó su pieza"));
  paso("14_filtro", ok(!hosts.catalogoFicha.querySelector("[data-cara]"),
    "…y no quedó una ficha pintada de la pieza equivocada"));
}

/* ══ LEY · i18n ES/EN COMPLETO ═══════════════════════════════════════════════════════
 * [heredado de verify_catalog_acceptance.mjs (i1-i4)] · Aleph es bilingüe, y «la pantalla
 * se reescribió» no es una razón para que deje de serlo. La sección entera tiene que
 * hablar inglés: las filas, las cuatro caras, los tres bordes y TODAS las causas.
 * ════════════════════════════════════════════════════════════════════════════════════ */
console.log("\nley · i18n ES/EN");
{
  // ⚠️ SE SETEA EL GLOBAL, NO SÓLO `window`. La casa lee el idioma con
  // `window.AlephI18n && AlephI18n.lang()`: en un navegador `window.X` ES el global, en node
  // no — y sin esto el `try/catch` de `lang()` se traga un ReferenceError y todo sale en
  // español. La vara diría «bilingüe» midiendo una sola mitad.
  const conLang = async (lang, fn) => {
    globalThis.AlephI18n = { lang: () => lang };
    window.AlephI18n = globalThis.AlephI18n;
    try { return await fn(); } finally { delete globalThis.AlephI18n; delete window.AlephI18n; }
  };
  // ninguna causa puede quedarse sin su mitad inglesa
  const sinEN = Object.entries(SC.CAUSAS_CATALOGO)
    .filter(([, m]) => !m.en || m.en === m.es).map(([k]) => k);
  paso("ley_i18n", ok(sinEN.length === 0, "todas las causas tienen ES y EN distintos", sinEN.join(",")));

  const es = await conLang("es", async () => {
    const { hosts } = banco();
    await M.montar(hosts);
    await window.__conectores.catalogo("stripe");
    await hosts.catalogoLista.querySelector("button[data-elegir]").click();
    await esperar(); await esperar();
    return hosts.catalogoLista.textContent + " ‖ " + hosts.catalogoFicha.textContent;
  });
  const en = await conLang("en", async () => {
    const { hosts } = banco();
    await M.montar(hosts);
    await window.__conectores.catalogo("stripe");
    await hosts.catalogoLista.querySelector("button[data-elegir]").click();
    await esperar(); await esperar();
    return hosts.catalogoLista.textContent + " ‖ " + hosts.catalogoFicha.textContent;
  });
  paso("ley_i18n", ok(/Pide tu llave/.test(es) && /Needs your key/.test(en),
    "el requisito habla los dos idiomas"));
  paso("ley_i18n", ok(/Qué avisa/.test(es) && /What it warns/.test(en),
    "el aviso de consecuencias, también"));
  paso("ley_i18n", ok(/Declara herramientas que escriben y borran/.test(es)
    && /Declares tools that write and delete/.test(en),
    "…incluidos los verbos que la pieza declaró"));
  // sin `\b`: el textContent concatena nodos sin espacio («Traer» pega con «Comprobado»),
  // así que un borde de palabra al final nunca matchea. La vara medía su propio regex.
  paso("ley_i18n", ok(/Traer/.test(es) && /Bring it/.test(en) && !/Traer/.test(en),
    "y el botón — que en inglés deja de decir «Traer»"));
  // los tres bordes y el viaje, en inglés. El `notice` del borde caído viene del BACKEND en
  // español a propósito (contrato de `catalog_search_router`): lo traduce la capa TM de
  // `i18n.js` nodo a nodo en el DOM, no esta superficie. Acá se mide lo que esta capa sí
  // escribe: el título y su salida.
  const enBorde = await conLang("en", async () => {
    const { hosts } = banco({ busqueda: BUSQUEDA_CAIDA });
    await M.montar(hosts);
    await window.__conectores.catalogo("stripe");
    return hosts.catalogoLista.textContent;
  });
  paso("ley_i18n", ok(/Not available right now/.test(enBorde) && /Retry/.test(enBorde),
    "el borde del registro caído, en inglés", enBorde.slice(0, 60)));
  const enViaje = await conLang("en", async () => {
    const { hosts } = banco({ frames: SSE.curacionRechazo });
    await M.montar(hosts);
    await window.__conectores.catalogo("stripe");
    await hosts.catalogoLista.querySelector("button[data-elegir]").click();
    await esperar(); await esperar(); await esperar();
    await hosts.catalogoFicha.querySelector("button[data-traer]").click();
    for (let i = 0; i < 4; i++) await esperar();
    return hosts.catalogoFicha.textContent;
  });
  paso("ley_i18n", ok(/Check the piece/.test(enViaje) && /failed the check/.test(enViaje),
    "el viaje y su causa, en inglés", enViaje.replace(/\s+/g, " ").slice(0, 70)));
}

/* ══ 12 · PREDICCIÓN vs MEDIDO ═══════════════════════════════════════════════════════ */
console.log("\n12 · la predicción, registrada antes");
let PREDICHO = null;
{
  const hay = existsSync(REPORTE);
  const texto = hay ? readFileSync(REPORTE, "utf8") : "";
  const m = texto.match(/PREDICCION_SECCION = (\{[\s\S]*?\n\})/);
  paso("12_prediccion", ok(!!m, "la predicción estaba escrita ANTES de esta corrida",
    hay ? "" : "falta el reporte"));
  if (m) { try { PREDICHO = JSON.parse(m[1]); } catch (_) { PREDICHO = null; } }
  paso("12_prediccion", ok(PREDICHO != null, "…y es legible"));
}

/* ══ 13 · REGRESIÓN ══════════════════════════════════════════════════════════════════ */
console.log("\n13 · regresión: cero veredictos cambiados");
{
  const py = "python3";
  const varas = [
    ["verify_tramite", join(RAIZ, "verify_tramite.py"), /"10_regresion_sellada": true/],
    ["verify_entrar", join(RAIZ, "verify_entrar.py"), /"8_common_verifier": true/],
    ["verify_escrutinio", join(RAIZ, "product/backend/tests/phase1/verify_escrutinio.py"), /VERDE · 9\/9/],
  ];
  for (const [nombre, ruta, seña] of varas) {
    let salida = "", codigo = 0;
    try { salida = execFileSync(py, [ruta], { cwd: RAIZ, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], maxBuffer: 64e6 }); }
    catch (e) { codigo = e.status || 1; salida = String((e.stdout || "") + (e.stderr || "")); }
    paso("13_regresion", ok(codigo === 0 && seña.test(salida),
      `${nombre} sigue verde`, `exit=${codigo}`));
  }
  // verify_tramite paso 10 ya corre los 5 arneses de Gate 1 + el pool de catálogo (53).
  console.log("     (los 5 arneses de Gate 1 y el pool de catálogo 53 corren dentro de verify_tramite)");
}

/* ══ CIERRE ══════════════════════════════════════════════════════════════════════════ */
console.log("\n" + "═".repeat(78));
if (PREDICHO) {
  console.log("PREDICHO vs MEDIDO");
  let desvios = 0;
  for (const k of Object.keys(PREDICHO)) {
    const medido = RESULTADO[k];
    const igual = medido === PREDICHO[k];
    if (!igual) desvios++;
    console.log(`  ${igual ? "=" : "≠"} ${k}: predicho ${PREDICHO[k]} · medido ${medido}`);
  }
  ok(desvios === 0, "lo medido coincide con lo predicho", `desvíos=${desvios}`);
}
console.log("MEDIDO=" + JSON.stringify(RESULTADO));
console.log("═".repeat(78));
console.log(FALLOS.length
  ? `\n❌ ${FALLOS.length} FALLO(S):\n` + FALLOS.map((f) => "   · " + f).join("\n")
  : "\n✅ verify_seccion: TODO VERDE");
process.exit(FALLOS.length ? 1 : 0);
