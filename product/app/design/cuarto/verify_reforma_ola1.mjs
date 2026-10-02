/* verify_reforma_ola1.mjs — REFORMA DEL CUARTO · OLA 1 (EL MODELO).
 *
 * Vara de las cinco piezas de la ola, medidas contra el SIDECAR FROZEN real (no un stub):
 *   a · el catálogo lista MCPs (no tools), las tools van anidadas, cero filas de filtros,
 *       y la búsqueda por nombre de tool revela el MCP padre. Recetas viejas cargan.
 *   b · pieza local sin trámite: jamás ⚪ "sin configurar", jamás pide llave.
 *   c · el banner de path crudo murió (nombre humano + camino real).
 *   d · los conectores sin tools declaran su verdad y no prometen capacidad.
 *   e · calc/time/sympy/units son NATIVAS: fuera del catálogo equipable.
 *   + · caminoDe(causa): UN diccionario, los 5 estados con su botón correcto.
 *
 * Run:  SIDECAR=http://127.0.0.1:8261 node product/app/design/cuarto/verify_reforma_ola1.mjs
 */
import { webkit } from "playwright";

const BASE = process.env.SIDECAR || "http://127.0.0.1:8261";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (c, label, extra) => {
  console.log(`${c ? "✓" : "✗"} ${label}${extra != null && extra !== "" ? "  — " + extra : ""}`);
  if (!c) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── health-gate: sin sidecar vivo la vara no corre (mejor rojo que verde falso) ──
try {
  const r = await fetch(BASE + "/health");
  if (!r.ok) throw new Error("health " + r.status);
  console.log(`── sidecar ${BASE} vivo\n`);
} catch (e) {
  console.log(`✗ el sidecar ${BASE} no responde (${e.message}) — levantalo antes de correr la vara`);
  process.exit(1);
}

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errores = [];
page.on("pageerror", (e) => errores.push(String(e)));
await page.goto(PAGE, { waitUntil: "domcontentloaded" });
// esperar a que el módulo TERMINE de montarse (__preflight es de las últimas líneas):
// __catalog se publica a mitad de camino y los handlers de la barra todavía no existen.
await page.waitForFunction(() => !!window.__catalog && !!window.__preflight, null, { timeout: 45000 }).catch(() => {});
await sleep(900);

ok(errores.length === 0, "la página carga sin errores de JS", errores.slice(0, 2).join(" | "));

// ══ e · LAS NATIVAS ══════════════════════════════════════════════════════════════════
console.log("\n§e · nativas — capacidad del cerebro, no pieza equipable");
const nat = await page.evaluate(() => {
  const c = window.__catalog || {};
  const ids = (c.entries || []).map((e) => e.server || e.id);
  return {
    nativas: (c.nativas || []).map((n) => n.server || n.id),
    enCatalogo: ["calc", "time", "sympy", "units"].filter((x) => ids.includes(x)),
    // [FIX-P4] la franja se BORRÓ: la vara ahora mide su AUSENCIA, no su contenido.
    host: document.querySelectorAll("#palNativas").length,
    chips: document.querySelectorAll(".nat,[data-nat]").length,
    copy: (document.body.innerText || "").includes("Ya vienen en el cerebro")
       || (document.body.innerText || "").includes("Already in the brain"),
  };
});
ok(nat.nativas.length === 4, "las 4 nativas salen del catálogo de átomos", nat.nativas.join(","));
ok(nat.enCatalogo.length === 0, "ninguna nativa queda como pieza equipable", nat.enCatalogo.join(",") || "0");
// [FIX-P4] la franja "Ya vienen en el cerebro" MURIÓ (decisión del 26-jul): a un cerebro
// frontier no se le anuncia que sabe sumar. Los brazos que NO tiene los trae el kit base.
ok(nat.host === 0 && nat.chips === 0 && !nat.copy,
   "la franja de nativas NO existe (host/chips/copy)",
   `host=${nat.host} chips=${nat.chips} copy=${nat.copy}`);

// ══ a · EL CATÁLOGO SON MCPs ═════════════════════════════════════════════════════════
console.log("\n§a · el catálogo son MCPs, las tools van adentro");
const cat = await page.evaluate(() => {
  const c = window.__catalog || {};
  const mcp = (c.entries || []).filter((e) => e.mcp);
  const dupes = {};
  mcp.forEach((e) => { dupes[e.mcp] = (dupes[e.mcp] || 0) + 1; });
  return {
    cards: c.cardCount, mcps: c.mcpCount, total: c.total,
    repetidos: Object.entries(dupes).filter(([, n]) => n > 1).map(([k]) => k),
    freecad: (mcp.find((e) => e.mcp === "freecad") || {}).tools || [],
    maritime: (mcp.find((e) => e.mcp === "maritime") || {}).tools || [],
    marConn: (mcp.find((e) => e.mcp === "maritime") || {}).connectors || [],
    conDetalle: mcp.filter((e) => (e.toolsDetail || []).length === (e.tools || []).length).length,
  };
});
ok(cat.mcps > 0 && cat.mcps < cat.cards, `${cat.cards} cards → ${cat.mcps} MCPs`, "");
ok(cat.repetidos.length === 0, "ningún MCP aparece dos veces en el catálogo", cat.repetidos.join(",") || "0");
ok(cat.freecad.length === 6, "freecad plegó sus 2 cards en UN MCP con las 6 tools", cat.freecad.join(","));
ok(cat.maritime.length === 5 && cat.marConn.length === 2,
   "maritime plegó sus 4 cards en 1 MCP (5 tools) y conserva SUS DOS cuentas", cat.marConn.join(","));
ok(cat.conDetalle === cat.mcps, "cada MCP trae el detalle de todas sus tools", `${cat.conDetalle}/${cat.mcps}`);

// filas de filtros: muertas
console.log("\n§a · las 5 filas de filtros murieron");
const filtros = await page.evaluate(() => ({
  segs: document.querySelectorAll("#palette .pfilters, #palette .seg").length,
  ids: ["fGroup", "fZone", "fType", "fKind", "fKey"].filter((i) => !!document.getElementById(i)),
  buscador: !!document.getElementById("palSearch"),
}));
ok(filtros.segs === 0 && filtros.ids.length === 0, "cero segmentados de filtro en la paleta", filtros.ids.join(",") || "0");
ok(filtros.buscador, "queda el buscador (la única entrada)");

// tools anidadas + búsqueda por tool revela el padre
console.log("\n§a · tools anidadas · buscar por tool revela el MCP padre");
await page.evaluate(() => { const b = document.getElementById("equipBtn"); if (b) b.click(); });
await sleep(500);
ok(await page.evaluate(() => document.getElementById("palette").classList.contains("open")), "＋ Equipar abre la paleta");
const anid = await page.evaluate(() => {
  // abrir el primer MCP con tools
  const t = document.querySelector("#paletteList .chip .ptools");
  const antes = document.querySelectorAll("#paletteList .ptools-box").length;
  if (t) t.click();
  return { antes, hayToggle: !!t };
});
await sleep(220);
const anid2 = await page.evaluate(() => ({
  cajas: document.querySelectorAll("#paletteList .ptools-box").length,
  filas: document.querySelectorAll("#paletteList .ptools-box .ptool code").length,
}));
ok(anid.hayToggle && anid.antes === 0, "las tools nacen ANIDADAS (nada desplegado por default)", String(anid.antes));
ok(anid2.cajas === 1 && anid2.filas > 0, "un toque despliega las tools de ESE MCP", `${anid2.cajas} caja · ${anid2.filas} tools`);

const busq = await page.evaluate(async () => {
  const inp = document.getElementById("palSearch");
  inp.value = "run_python";
  inp.dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 260));
  const chips = [...document.querySelectorAll("#paletteList .chip")];
  const hit = [...document.querySelectorAll("#paletteList .ptool.hit code")].map((e) => e.textContent);
  return { mcps: chips.map((c) => c.dataset.mcp), hit };
});
// `run_python` la declaran DOS MCPs (pysandbox y script_runner): los dos padres se revelan.
ok(busq.mcps.includes("pysandbox") && busq.mcps.length === 2,
   "buscar el nombre de una TOOL revela su(s) MCP padre", busq.mcps.join(" + "));
ok(busq.hit.includes("run_python"), "y la fila nace abierta con la tool encontrada marcada", busq.hit.join(","));

// ══ d · CONECTORES SIN TOOLS ═════════════════════════════════════════════════════════
console.log("\n§d · un conector sin tools lo dice");
const conn = await page.evaluate(async () => {
  const inp = document.getElementById("palSearch");
  inp.value = ""; inp.dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 260));
  const c = window.__catalog || {};
  const mudos = (c.entries || []).filter((e) => e.sinTools);
  const filas = [...document.querySelectorAll("#paletteList .chip.sin-tools")];
  const dicen = filas.filter((f) => /0 tools/.test(f.textContent)).length;
  return { mudos: mudos.length, filas: filas.length, dicen,
           equipable: mudos.filter((m) => !m.connectorOnly).length };
});
ok(conn.mudos > 0, `${conn.mudos} conectores sin ninguna tool`, "");
ok(conn.filas === conn.dicen && conn.dicen > 0, "TODOS declaran «0 tools todavía» en su fila", `${conn.dicen}/${conn.filas}`);
ok(conn.equipable === 0, "ninguno se ofrece como pieza equipable", String(conn.equipable));

// ══ + · caminoDe: UN diccionario ═════════════════════════════════════════════════════
console.log("\n§· caminoDe(causa) — un diccionario, cinco caminos");
const cam = await page.evaluate(() => {
  const S = window.CuartoSemaforo;
  const d = (estado, causa) => S.caminoDe({ estado, causa }) || {};
  return {
    sinProbar: d("detectado"),
    sinConexion: d("no_configurado"),
    sinKey: d("roto", "falta_key"),
    proveedor: d("roto", "error_upstream"),
    premium: d("premium"),
    nueva: d("roto", "una_causa_que_no_existe_todavia"),
    verde: S.caminoDe({ estado: "probado" }),
    esMismo: S.botonDe({ estado: "detectado" }).accion === S.caminoDe({ estado: "detectado" }).accion,
  };
});
ok(cam.sinProbar.es === "Probar ahora" && cam.sinProbar.accion === "probar", "🟡 sin probar → [Probar ahora]", cam.sinProbar.es);
ok(cam.sinConexion.es === "Conectar" && cam.sinConexion.accion === "configurar", "⚪ falta conexión → [Conectar]", cam.sinConexion.es);
/* ROJO PREEXISTENTE (verificado contra el árbol base con `git stash`): [FIX-P1B] cambió el
 * rótulo a «Poner la llave» —el humanizador saca las palabras de máquina— y esta vara se
 * quedó con «key». La ACCIÓN, que es el contrato, no cambió: `credencial` + inline. */
ok(cam.sinKey.es === "Poner la llave" && cam.sinKey.accion === "credencial" && cam.sinKey.inline === true,
   "🔴 falta credencial → [Poner la llave] inline", cam.sinKey.es);
/* [FIX-P3 · §2] LA FUSIÓN: «Probar» y «Reintentar» eran dos rótulos para el mismo disparo.
 * Queda uno, [Probar de nuevo]. La ACCIÓN sigue siendo `reintentar` (es el valor del
 * contrato y las superficies deciden con él) — lo que se unificó es lo que la persona lee.
 * La aserción se endurece: además del rótulo, se fija la acción. */
ok(cam.proveedor.es === "Probar de nuevo" && cam.proveedor.accion === "reintentar" &&
   cam.proveedor.extra && cam.proveedor.extra.es === "Ver error",
   "🔴 error proveedor → [Probar de nuevo] + [Ver error]", `${cam.proveedor.es}+${(cam.proveedor.extra || {}).es}`);
ok(cam.premium.es === "Ver planes" && cam.premium.accion === "premium", "🔒 premium → [Ver planes]", cam.premium.es);
ok(cam.nueva.accion === "ver_error" && cam.nueva.desconocida === true,
   "causa NUEVA → texto canónico + [Ver error], jamás un botón falso", cam.nueva.es);
ok(cam.verde === null, "🟢 probado no fuerza camino");
ok(cam.esMismo, "botonDe y caminoDe son EL MISMO diccionario (no dos tablas)");

// ══ b · PIEZA LOCAL SIN TRÁMITE ══════════════════════════════════════════════════════
console.log("\n§b · pieza local sin trámite");
const loc = await page.evaluate(async () => {
  const C = window.__cuarto, S = window.CuartoSemaforo;
  const cat = window.__catalog || {};
  const locales = ["pysandbox", "sqlite", "filesystem", "wikipedia"];   // filesystem = el server de la card "files"
  const out = [];
  for (const id of locales) {
    const e = (cat.entries || []).find((x) => x.mcp === id);
    if (!e) { out.push({ id, falta: true }); continue; }
    // ¿el predicado la reconoce como local? ¿y qué estado admite?
    const esLocal = S.esLocalSinTramite(e);
    const forzado = S.normalizarLocal({ estado: "no_configurado", evidencia: {} }, esLocal);
    const conKey = S.normalizarLocal({ estado: "roto", causa: "falta_key", evidencia: {} }, esLocal);
    out.push({ id, esLocal, estado: forzado.estado, causaKey: conKey.causa,
               camino: (S.caminoDe(forzado) || {}).es });
  }
  return out;
});
loc.forEach((l) => {
  ok(!l.falta && l.esLocal, `${l.id} · reconocida como pieza local sin trámite`, l.falta ? "no está en el catálogo" : "");
  ok(l.estado === "detectado", `${l.id} · NUNCA queda "sin configurar"`, l.estado);
  ok(l.causaKey !== "falta_key", `${l.id} · nunca pide llave`, String(l.causaKey));
  ok(l.camino === "Probar ahora", `${l.id} · su camino es [Probar ahora]`, String(l.camino));
});

// equipar una local y leer su semáforo REAL contra el motor
await page.evaluate(async () => {                     // abrir el closet que contiene pysandbox
  const inp = document.getElementById("palSearch");
  inp.value = "pysandbox"; inp.dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 260));
});
await page.click('#paletteList .chip[data-mcp="pysandbox"]', { position: { x: 8, y: 8 } }).catch(() => {});
await sleep(2200);
/* [FIX-P3 · §7] LA FILA MURIÓ: el estado de una pieza se lee en su ANILLO (el diorama) y en
 * el pie de su arco. Se re-apunta ahí, y de paso se ENDURECE: antes se buscaba «alguna fila
 * cuyo texto diga sandbox» —un match difuso que podía caer en la fila equivocada— y ahora se
 * busca LA PIEZA por su server en el piso, y se le lee el estado a ESA. */
const equip = await page.evaluate(async () => {
  const c = window.__cuarto;
  const mia = c.placedTiles().find((t) => /sandbox/i.test(String(t.server || t.label || t.id)));
  if (!mia) return { colocada: false };
  window.__openAbanico(c.pieceData(mia.id));
  await new Promise((r) => setTimeout(r, 250));
  const pie = window.__abanicoEstado();
  const anillo = c.tileVerdadState ? c.tileVerdadState(mia.id) : null;
  try { window.__closeAbanico(); } catch (e) {}
  return { colocada: true, id: mia.id, estado: (anillo && anillo.estado) || (pie && pie.estado) || null,
           txt: (pie && pie.txt) || "" };
});
ok(equip.colocada, "la pieza local se equipa desde la fila del MCP");
ok(equip.estado !== "no_configurado", "equipada, su semáforo NO dice «sin configurar»", String(equip.estado));
ok(!/llave|key/i.test(equip.txt || ""), "equipada, no pide llave", String(equip.txt));

// ══ c · MUERE EL BANNER DE PATH CRUDO ════════════════════════════════════════════════
console.log("\n§c · muere el banner de path crudo");
/* [CONECTORES RICA · paso 0] El Centro y su parser de slugs murieron. La garantía vigente
 * se mide donde ahora la ve la persona: una fila LOCAL real de la sección Conectores.
 * Nombre, anatomía y camino vienen de datos estructurados + el store P11 + caminoDe(P1B);
 * `api.*`/`cli.*` no se vuelven a inferir acá porque pertenecen a Modelos. */
const conectores = await browser.newPage({ viewport: { width: 1280, height: 820 } });
await conectores.goto(`${BASE}/Conectores.dc.html`, { waitUntil: "domcontentloaded" });
await conectores.waitForFunction(() =>
  !!window.__conectoresRica &&
  !window.__conectoresRica.MODELO.cargando &&
  document.querySelectorAll("#localRows .local-row").length > 0,
  null, { timeout: 30000 }).catch(() => {});
const humano = await conectores.evaluate(() => {
  const filas = [...document.querySelectorAll("#localRows .local-row")];
  const mcp = filas.find((r) => r.dataset.connectorId === "mcp:pysandbox");
  const nombre = ((mcp && mcp.querySelector(".cx-name")) || {}).textContent || "";
  const accion = ((mcp && mcp.querySelector("[data-action]")) || {}).dataset?.action || null;
  const texto = (mcp && mcp.innerText) || "";
  const fuera = filas.filter((r) => /\bGroq\b|\bClaude\b/i.test(r.innerText || "")).length;
  return { existe: !!mcp, nombre: nombre.trim(), accion, texto, cognicionFuera: fuera === 0 };
});
ok(humano.existe && humano.nombre.length > 0 && !/catalog|json|#|\//i.test(humano.nombre),
   "la fila LOCAL usa nombre humano estructurado — cero path", humano.nombre);
ok(humano.accion !== "credencial" && humano.accion !== "configurar",
   "una pieza local NO ofrece llave ni conexión falsa", String(humano.accion));
ok(humano.cognicionFuera, "API/CLI de cognición no se filtran dentro de Conectores");
await conectores.close();

// el reintento gastado sobre una pieza LOCAL no manda al Centro
const mut = await page.evaluate(async () => {
  const S = window.CuartoSemaforo;
  const el = document.createElement("div"); document.body.appendChild(el);
  S.pintarBadge(el, { tipo: "mcp", ref: "x", estado: "roto", causa: "sin_red", evidencia: { local: true } },
                { _gastado: true, ctx: { local: true }, onProbar: () => null });
  const b = el.querySelector(".sem-accion");
  const r = { accion: b && b.dataset.accion, txt: b && b.textContent };
  el.remove(); return r;
});
// [integración tanda-b2] LA LEY SUBIÓ, no bajó — séptima aserción de la clase que FIX-P1B
// declaró en su §9 (las otras seis las ajustó él; ésta se le pasó).
//   antes: el reintento gastado sobre una pieza local caía en [Ver error] — «no te mando al
//          Centro» era todo lo que se le podía pedir, y a la persona le quedaba mirar un
//          error sin nada que hacer.
//   ahora: abre EL WORKFLOW de su tipo (el de `programa`), que chequea la dependencia ANTES
//          de volver a reintentar — justo el «reintento al vacío» que §7 prohíbe.
// Se sigue midiendo lo que esta aserción defendía (NO navegar al catálogo) y se le agrega lo
// que antes no se podía ni preguntar: que la salida sea accionable.
ok(mut.accion === "wizard", "reintento gastado sobre pieza LOCAL → abre el workflow, no el Centro", `${mut.accion} · ${mut.txt}`);
ok(mut.txt === "Arreglarlo", "…y el rótulo de una pieza local es arreglarla, no «configurar» una conexión que no tiene", `${mut.txt}`);
ok(mut.accion !== "configurar" && mut.accion !== "catalogo", "…y JAMÁS es la navegación vieja al catálogo", mut.accion);

// ══ a · RECETAS VIEJAS CARGAN (migración) ════════════════════════════════════════════
console.log("\n§a · recetas viejas cargan (migración a MCP)");
const mig = await page.evaluate(() => {
  const M = window.CuartoCatalogo.migrarBloquesAMcp;
  const vieja = [
    { id: "b1", atom: "tool", card_id: "cad-freecad", ref: "freecad", tools: ["create_document", "create_object"], zone: "mesa", gridX: 1, gridY: 1 },
    { id: "b2", atom: "tool", card_id: "cad-script", ref: "freecad", tools: ["execute_code"], zone: "mesa", gridX: 2, gridY: 1 },
    { id: "b3", atom: "tool", card_id: "calc", ref: "calc", tools: ["add"], zone: "mesa", gridX: 3, gridY: 1 },
    { id: "b4", atom: "tool", card_id: "sec-edgar", ref: "sec-edgar", tools: ["get_filings"], zone: "fuentes", gridX: 4, gridY: 1 },
    { id: "n1", atom: "agente", agent_ref: "a/b.json", nucleo: true, gridX: 5, gridY: 1 },
  ];
  const r = M(vieja);
  const fc = r.blocks.find((b) => b.ref === "freecad");
  return { n: r.blocks.length, plegados: r.plegados, nativas: r.nativas,
           fcTools: (fc || {}).tools || [], agente: r.blocks.some((b) => b.atom === "agente") };
});
ok(mig.plegados === 1 && mig.fcTools.length === 3,
   "dos bloques del mismo MCP se pliegan en UNO con la unión de tools", mig.fcTools.join(","));
ok(mig.nativas === 1, "las nativas salen del piso al cargar", `${mig.nativas} retirada`);
ok(mig.n === 3 && mig.agente, "el resto del canvas queda intacto (el sub-agente sobrevive)", `${mig.n} bloques`);

const rt = await page.evaluate(() => {
  // round-trip real por el módulo de receta: una receta guardada vieja debe cargar
  const R = window.__recipeMod;
  const receta = {
    schema_version: "v1", meta: { name: "viejo" }, model: {},
    belt: { belt_refs: ["catalog/templates/ingenieria/belt-ingenieria.mcp.json"],
            tool_filters: { freecad: ["create_document", "execute_code"] } },
    canvas: { version: "v1", nucleos: [{ id: "nucleo", gridX: 3, gridY: 1, model: "opus" }],
      blocks: [
        { id: "b1", atom: "tool", card_id: "cad-freecad", ref: "freecad", tools: ["create_document"], zone: "mesa", gridX: 1, gridY: 1 },
        { id: "b2", atom: "tool", card_id: "cad-script", ref: "freecad", tools: ["execute_code"], zone: "mesa", gridX: 2, gridY: 1 },
      ], links: [] },
  };
  const tiles = R.recipeToTiles(receta, (window.__atoms || {}).list || []);
  const re = R.tilesToRecipe(tiles, { name: "viejo", model: "opus" });
  return { tiles: tiles.length, tools: (tiles[0] || {}).tools || [],
           filtros: (re.belt || {}).tool_filters || {}, mig: window.__ultimaMigracion };
});
ok(rt.tiles === 1 && rt.tools.length === 2, "una receta vieja carga como UNA pieza sin perder tools", rt.tools.join(","));
ok((rt.filtros.freecad || []).length === 2, "y se re-guarda con sus 2 tools (save/load intacto)", JSON.stringify(rt.filtros));
ok(rt.mig && rt.mig.plegados === 1, "la migración se REPORTA (no es silenciosa)", JSON.stringify(rt.mig));

await browser.close();
console.log(`\n${fails.length ? "✗ FALLOS: " + fails.length : "✓ TODO VERDE"}`);
fails.forEach((f) => console.log("   · " + f));
process.exit(fails.length ? 1 : 0);
