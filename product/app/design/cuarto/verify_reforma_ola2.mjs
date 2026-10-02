/* verify_reforma_ola2.mjs — REFORMA DEL CUARTO · OLA 2 (EL CUARTO).
 *
 * Contra el SIDECAR FROZEN real (WebKit, :8261). Mide la ola entera:
 *   f · la pieza ES el logo · murió la silueta/arco de puerta (grep + visual)
 *   g · el anillo: existe si hay tools · color = PEOR estado del motor · número = cuántas
 *   h · el abanico de 5 acciones, con el camino correcto en los 5 estados
 *   i · el widget del MCP: sólo las tools de ESE MCP, con nombre real y frase humana
 *   j · el candado adosado (muere FU-1) · qué frena · regla · veces · las decisiones
 *   k · los dos modos: posiciones idénticas · cero flechas · el +N enfoca · punto vivo
 *   l · cero tab Código · cero código renderizado suelto · [Ver en VS Code] con path
 *   m · #gatebar y #unequipbar tokenizados (giran con el tema)
 *   + · cero <function=…> crudo en el chat del Guía
 *
 * Run:  SIDECAR=http://127.0.0.1:8261 node product/app/design/cuarto/verify_reforma_ola2.mjs
 */
import { webkit } from "playwright";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const BASE = process.env.SIDECAR || "http://127.0.0.1:8261";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (c, label, extra) => {
  console.log(`${c ? "✓" : "✗"} ${label}${extra != null && extra !== "" ? "  — " + extra : ""}`);
  if (!c) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

try {
  const r = await fetch(BASE + "/health");
  if (!r.ok) throw new Error("health " + r.status);
  console.log(`── sidecar ${BASE} vivo\n`);
} catch (e) {
  console.log(`✗ el sidecar ${BASE} no responde (${e.message})`);
  process.exit(1);
}

// ══ f · GREP: la silueta de puerta no existe en el renderer ══════════════════════════
console.log("§f · cero puertas — el grep");
const render = await readFile(join(HERE, "cuarto.render.js"), "utf8");
const grepPuerta = {
  hoja: /const leaf = new PIXI\.Graphics/.test(render),
  picaporte: /const knob = new PIXI\.Graphics/.test(render),
  vano: /quadraticCurveTo\(-15, -40, 0, -40\)/.test(render),
  propDelDecorado: /propsById\["mcp_door"\] = dn/.test(render),
};
ok(!grepPuerta.hoja && !grepPuerta.picaporte && !grepPuerta.vano,
   "el arco/hoja/picaporte de la puerta no está en el renderer", JSON.stringify(grepPuerta));
ok(!grepPuerta.propDelDecorado, "y la puerta MCP del decorado tampoco se instancia");

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errores = [];
page.on("pageerror", (e) => errores.push(String(e)));
await page.goto(PAGE, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => !!window.__catalog && !!window.__preflight, null, { timeout: 45000 }).catch(() => {});
await sleep(900);
ok(errores.length === 0, "la página carga sin errores de JS", errores.slice(0, 2).join(" | "));

// equipar tres piezas de prueba: local · MCP con 2 cuentas · conexión
const puestas = await page.evaluate(async () => {
  const cat = window.__catalog, C = window.__cuarto;
  const poner = (mcp, id) => {
    const e = (cat.entries || []).find((x) => x.mcp === mcp);
    if (!e) return null;
    return C.placeTile(Object.assign({}, e, { id }));
  };
  const a = poner("pysandbox", "t-local");
  const b = poner("maritime", "t-multi");
  const c = poner("gmail", "t-conn") || poner("github", "t-conn");
  window.__sync && window.__sync(); window.__renderPieces && window.__renderPieces();
  await new Promise((r) => setTimeout(r, 2000));
  return { a: !!a, b: !!b, c: !!c, ids: C.placedTiles().map((t) => t.id) };
});
ok(puestas.a && puestas.b, "piezas de prueba equipadas", puestas.ids.join(","));

// ══ f · VISUAL: la cara de la pieza es el símbolo funcional curado ═══════════════════
console.log("\n§f · la pieza usa el símbolo funcional del diorama");
const caras = await page.evaluate(async () => {
  await new Promise((r) => setTimeout(r, 900));   // el manifest de logos llega por red
  const C = window.__cuarto;
  return ["t-local", "t-multi", "t-conn"].map((id) => Object.assign({ id }, C.tileCara(id) || {}));
});
const conCara = caras.filter((c) => c.tieneCara);
ok(conCara.length === caras.filter((c) => c.id !== "t-conn" || true).length,
   "TODA pieza tiene una cara funcional",
   caras.map((c) => `${c.id}:${c.symbol || "—"}`).join(" · "));
ok(caras.every((c) => c.symbol), "cada pieza resuelve exactamente un símbolo");

// ══ g · EL ANILLO ═══════════════════════════════════════════════════════════════════
console.log("\n§g · el anillo: existe · color = peor estado · número = cuántas");
const anillo = await page.evaluate(() => {
  const C = window.__cuarto;
  return { local: C.tileAnillo("t-local"), multi: C.tileAnillo("t-multi"),
           nucleo: C.tileAnillo("nucleo") };
});
ok(anillo.local && anillo.local.visible && anillo.local.tools === 1, "una pieza con 1 tool trae anillo de 1", JSON.stringify(anillo.local));
ok(anillo.multi && anillo.multi.tools === 5, "un MCP plegado trae el número REAL de tools", String((anillo.multi || {}).tools));
const peor = await page.evaluate(() => {
  const S = window.CuartoSemaforo;
  const G = { probado: 0, detectado: 1, premium: 2, no_configurado: 3, roto: 4 };
  const peorDe = (l) => l.reduce((a, b) => ((G[b.estado] || 0) > (G[a.estado] || 0) ? b : a));
  return {
    sinKey: peorDe([{ estado: "probado" }, { estado: "no_configurado" }]).estado,
    proveedor: peorDe([{ estado: "probado" }, { estado: "roto", causa: "error_upstream" }]).estado,
    mezclado: peorDe([{ estado: "probado" }, { estado: "probado" }]).estado,
    colorRojo: S.colorDe("roto"), colorBlanco: S.colorDe("no_configurado"), colorVerde: S.colorDe("probado"),
  };
});
ok(peor.sinKey === "no_configurado", "sin key → el anillo entero va a ⚪ (no a medias)", peor.sinKey);
ok(peor.proveedor === "roto", "proveedor caído → el anillo entero va a 🔴", peor.proveedor);
ok(peor.mezclado === "probado", "todas las cuentas ok → 🟢 (la mezcla sólo baja, nunca sube)", peor.mezclado);
ok(peor.colorRojo !== peor.colorVerde && peor.colorBlanco !== peor.colorVerde, "los tres colores son distintos");
// sin segmentos ni nombres por tool: el anillo dibuja UN aro y UN número
const dibujo = await page.evaluate(() => {
  const src = window.__anilloSrc || null; return src;
});
// [FIX-P6] el semieje menor dejó de escribirse inline (`r * 0.62`) y sale de anilloRadii(n) → {a,b},
// la FUENTE ÚNICA que comparten dibujo y física (así el radio de colisión no puede desincronizarse
// del radio dibujado). El aro sigue siendo UNO y sigue sin segmentos: sólo cambió el nombre de la
// expresión. Que a = _auraR·0.78 y b = a·0.62 lo asierta verify_p6_anillos §1 sobre el dibujo VIVO,
// que es más fuerte que este grep.
ok(/g\.ellipse\(0, cy, r, rb\)\.stroke/.test(render) && !/segment/i.test(render.split("drawTileAnillo")[1] || ""),
   "el anillo es UN aro continuo: cero segmentos por tool");

// ══ h · EL ABANICO ══════════════════════════════════════════════════════════════════
console.log("\n§h · el abanico de 5 acciones");
const ab = await page.evaluate(async () => {
  const d = window.__cuarto.pieceData("t-local");
  window.__openAbanico(d);
  await new Promise((r) => setTimeout(r, 200));
  return { abierto: window.__abanicoAbierto(), acts: window.__abanicoActs() };
});
ok(ab.abierto, "tocar una pieza abre el abanico");
const ids = ab.acts.map((a) => a.act);
ok(ids.includes("tools") && ids.includes("probar") && ids.includes("asegurar") && ids.includes("quitar"),
   "trae [Ver tools] · [Probar] · [Asegurar] · [Quitar]", ids.join("·"));
/* [FIX-P3 · §2] LA FUSIÓN. La pieza no está verde, y su causa es REINTENTABLE: ese camino
 * ya lo ocupa el slot de prueba, que pasa a llamarse [Probar de nuevo]. Tener además un
 * [Reintentar] en el slot del camino era el mismo disparo con dos nombres. La aserción se
 * endurece: no basta con que haya «un camino» — se exige el rótulo fusionado Y que no exista
 * un segundo botón para lo mismo. */
const etProbar = (ab.acts.find((a) => a.act === "probar") || {}).label || "";
ok(!ids.includes("camino"),
   "🟡 sin probar → NO hay slot de camino aparte: [Probar] YA es ese camino", ids.join("·"));
ok(/Probar\b|Test\b/.test(etProbar) && !/de nuevo|again/.test(etProbar),
   "…y su rótulo es [Probar] (todavía no hubo nada que reintentar)", etProbar);
// …y en ROJO el MISMO botón cambia de nombre. Un disparo, dos momentos, un solo botón.
const enRojo = await page.evaluate(async () => {
  const C = window.__cuarto, d = C.pieceData("t-local");
  window.__registrarDesenlace("t-local", { res: { tipo: "mcp", ref: "x", estado: "roto", causa: "error_upstream",
                                                  evidencia: { detail: "forzado por la vara" }, ts: Math.floor(Date.now() / 1000) } });
  window.__closeAbanico(); window.__openAbanico(d);
  await new Promise((r) => setTimeout(r, 250));
  return window.__abanicoActs();
});
const etRojo = (enRojo.find((a) => a.act === "probar") || {}).label || "";
ok(/Probar de nuevo|Test again/.test(etRojo),
   "🔴 roto → el MISMO botón pasa a [Probar de nuevo] (la fusión)", etRojo);
ok(!enRojo.some((a) => /Reintentar|Retry/.test(a.label)),
   "…y NUNCA aparece un [Reintentar] aparte", enRojo.map((a) => a.act).join("·"));
// el camino correcto en los 5 estados
const cinco = await page.evaluate(() => {
  const S = window.CuartoSemaforo;
  const m = (estado, causa) => (S.caminoDe({ estado, causa }) || {}).es;
  return { probado: S.caminoDe({ estado: "probado" }), detectado: m("detectado"),
           no_configurado: m("no_configurado"), roto_key: m("roto", "falta_key"),
           roto_prov: m("roto", "error_upstream"), premium: m("premium") };
});
ok(cinco.probado === null, "🟢 probado → el abanico no ofrece camino (sólo 4 acciones)");
/* rótulos re-apuntados a dos cambios de contrato deliberados:
 *   [FIX-P1B] «Poner la key» → «Poner la llave» (el humanizador saca palabras de máquina);
 *   [FIX-P3 · §2] «Reintentar» → «Probar de nuevo» (la fusión: un disparo, un rótulo). */
ok(cinco.detectado === "Probar ahora" && cinco.no_configurado === "Conectar" &&
   cinco.roto_key === "Poner la llave" && cinco.roto_prov === "Probar de nuevo" && cinco.premium === "Ver planes",
   "los otros 4 estados traen su camino exacto", JSON.stringify(cinco));
const tarjeta = await page.evaluate(async () => {
  const st = {};
  window.__openInspector(window.__cuarto.pieceData("t-local"));           // pieza-TOOL
  await new Promise((r) => setTimeout(r, 250));
  st.tool = getComputedStyle(document.querySelector("#inspector .iactions")).display;
  st.expandido = document.getElementById("inspector").classList.contains("expanded");
  window.__openInspector(window.__cuarto.nucleoData());                   // NÚCLEO
  await new Promise((r) => setTimeout(r, 250));
  st.nucleo = getComputedStyle(document.querySelector("#inspector .iactions")).display;
  return st;
});
ok(tarjeta.tool === "none", "la tarjeta [Ajustar][Más ▾] murió para las piezas-tool", tarjeta.tool);
ok(tarjeta.expandido, "…y el inspector de una pieza abre DERECHO en lo que se pidió (sin peaje)");
ok(tarjeta.nucleo !== "none", "el Núcleo conserva su nivel-1 (no tiene abanico: su gesto es otro)", tarjeta.nucleo);

// ══ i · EL WIDGET DEL MCP ═══════════════════════════════════════════════════════════
console.log("\n§i · el widget: SÓLO las tools de ese MCP");
const w = await page.evaluate(async () => {
  const d = window.__cuarto.pieceData("t-multi");
  window.__openToolWidget(d);
  await new Promise((r) => setTimeout(r, 200));
  const st = window.__toolWidget();
  const filas = [...document.querySelectorAll("#twList .tw-row")].map((r) => ({
    n: (r.querySelector(".tw-n") || {}).textContent, f: (r.querySelector(".tw-f") || {}).textContent }));
  const otras = window.__cuarto.pieceData("t-local").tools || [];
  return { st, filas, otras, sub: (document.getElementById("twSub") || {}).textContent };
});
ok(w.st.abierto && w.st.de === "maritime", "el widget es del MCP que se tocó", w.st.de);
ok(w.st.tools.length === 5 && !w.st.tools.some((t) => w.otras.includes(t)),
   "lista SUS 5 tools y ninguna de otro MCP", w.st.tools.join(","));
ok(w.filas.every((f) => f.n && /^[a-z0-9_]+$/i.test(f.n)), "cada fila trae el nombre REAL de la tool",
   w.filas.map((f) => f.n).join(","));
ok(w.filas.some((f) => f.f && f.f.length > 3), "…con una frase humana al lado",
   (w.filas.find((f) => f.f) || {}).f);
ok(/sin probar|Probado|Sin probar|Roto|configurar/i.test(w.sub || ""), "…y el estado con su lectura", (w.sub || "").slice(0, 50));

// ══ j · EL CANDADO ══════════════════════════════════════════════════════════════════
console.log("\n§j · el candado: adosado, con qué frena · regla · veces · decisiones");
const cd = await page.evaluate(async () => {
  const d = window.__cuarto.pieceData("t-multi");
  /* [FIX-P3 · §4] el candado sólo existe sobre lo que TOCA AFUERA — y sin advisor (esta vara
   * corre sin backend) no hay evidencia de que toque nada, así que no se ofrece. La fixture
   * lo declara explícitamente: una pieza asegurada ES, por definición, una que toca afuera. */
  d.gated = true; try { window.__cuarto.setGated(d.id, true); } catch (e) {}
  window.__openCandado(d);
  await new Promise((r) => setTimeout(r, 200));
  const box = document.getElementById("candado");
  const st = window.__candado();
  const reglas = [...document.querySelectorAll("#cdReglas .cd-r")].map((b) => b.dataset.regla);
  // poner la regla "siempre" y volver a leer
  const bs = document.querySelector('#cdReglas .cd-r[data-regla="stop"]'); if (bs) bs.click();
  await new Promise((r) => setTimeout(r, 150));
  return { st, reglas, anclado: box.dataset.anchored, decisiones: !!document.getElementById("cdDecisiones"),
           href: (document.getElementById("cdDecisiones") || {}).getAttribute ? document.getElementById("cdDecisiones").getAttribute("href") : "",
           tras: window.__candado(), gated: !!window.__cuarto.pieceData("t-multi").gated };
});
ok(cd.st.abierto, "el candado abre desde el abanico");
ok(cd.anclado === "1", "…ANCLADO a la pieza (no flotando en el medio)", cd.anclado);
ok(JSON.stringify(cd.reglas) === JSON.stringify(["stop", "ok", "auto"]), "trae las 3 reglas", cd.reglas.join("/"));
ok(/frena|Frena|candado/.test(cd.st.que), "dice QUÉ frena", cd.st.que.slice(0, 60));
ok(/vez|veces|Todavía/.test(cd.st.veces), "dice CUÁNTAS veces frenó", cd.st.veces);
ok(cd.decisiones && /Historial/.test(cd.href), "…y trae el botón a las decisiones", cd.href);
ok(cd.tras.regla === "stop" && cd.gated, "elegir una regla la APLICA de verdad", cd.tras.regla);
/* ══ FU-1 · LA DOCTRINA SE INVIRTIÓ, A PROPÓSITO ═══════════════════════════════════════
 * Esta aserción defendía que el candado NO cayera sobre el cable: en la ola 2 el punto vivía
 * a mitad de camino del segmento RECTO Núcleo→pieza, o sea encima de la curva sin estar
 * sobre ella — flotando, custodiando aire. La cura de entonces fue mudarlo al hombro de la
 * pieza… donde siguió flotando, ahora al lado, y además convivía con el «candado-semáforo de
 * la tapa»: DOS candados sueltos por pieza en las capturas.
 *
 * La versión SELLADA (26-jul) dice lo contrario y es lo que se mide ahora: UNO por pieza,
 * PEGADO al cable. Y se mide de verdad, no con un grep del código fuente: se le pregunta al
 * render dónde cayó el candado y a qué distancia está de la bezier real del cable. */
const fu1 = await page.evaluate(() => {
  const C = window.__cuarto;
  const ids = C.candados();
  return { n: ids.length, unoPorPieza: ids.length === new Set(ids).size,
           det: ids.map((id) => Object.assign({ id }, C.candado(id))) };
});
ok(fu1.n >= 1 && fu1.unoPorPieza, "UNO por pieza: cero candados repetidos", `n=${fu1.n}`);
ok(fu1.det.every((c) => c.dCable <= 1.5),
   "FU-1 muerto al revés: el candado está PEGADO al cable, no flotando",
   fu1.det.map((c) => `${c.id}:${c.dCable.toFixed(2)}px`).join(" · "));
ok(fu1.det.every((c) => c.dPieza > 12 && c.dNucleo > 12),
   "…y sobre el CABLE, no encima de la pieza ni del Núcleo",
   fu1.det.map((c) => `${c.id}: pieza=${Math.round(c.dPieza)} núcleo=${Math.round(c.dNucleo)}`).join(" · "));

// ══ k · LOS DOS MODOS ═══════════════════════════════════════════════════════════════
console.log("\n§k · dos modos: MCPs (default) · Trabajo");
const modos = await page.evaluate(async () => {
  const C = window.__cuarto;
  const pos = () => C.placedTiles().map((t) => `${t.id}:${t.gridX},${t.gridY}`).sort().join("|");
  const antes = pos();
  const m0 = window.__modo();
  document.getElementById("modoBtn").click();
  await new Promise((r) => setTimeout(r, 400));
  const m1 = window.__modo();
  const despues = pos();
  document.getElementById("modoBtn").click();
  await new Promise((r) => setTimeout(r, 250));
  return { m0, m1, mismas: antes === despues, vuelta: window.__modo().modo,
           estado: (document.getElementById("modoState") || {}).textContent };
});
ok(modos.m0.modo === "mcps", "el modo por default es MCPs (compacto)", modos.m0.modo);
ok(modos.m1.modo === "trabajo" && modos.m1.tools.length >= 6,
   "modo trabajo: cada tool baja como pieza", `${modos.m1.tools.length} tools`);
ok(modos.mismas, "las piezas-MCP quedan en LA MISMA posición entre modos");
ok(modos.vuelta === "mcps", "y se vuelve");
ok(!/vivo|live/i.test(modos.estado || ""), "el modo NO se llama «en vivo»", modos.estado);
// cero flechas: el lazo de pertenencia no tiene punta ni dirección
const cuerpoWork = (render.match(/function drawWork\(t\) \{[\s\S]*?\n  \}/) || [""])[0];
ok(cuerpoWork.length > 100 && !/arrow|flecha|poly\(/i.test(cuerpoWork) &&
   /workTether\.moveTo\(p\.sx, p\.baseY\)\.lineTo/.test(cuerpoWork),
   "modo trabajo dibuja un lazo sin punta: cero flechas, cero orden (eso es Método)",
   `${cuerpoWork.length} chars`);
// el +N del anillo enfoca
const foco = await page.evaluate(() => /workMode = true; workFocus = srv/.test("") ? null : null);
ok(/onModoChange\(\{ modo: "trabajo", focus: workFocus, de: node\.id \}\)/.test(render),
   "el +N del anillo abre el modo trabajo ENFOCADO en ese MCP");
// punto vivo en modo MCPs
const vivo = await page.evaluate(async () => {
  const C = window.__cuarto;
  C.toolLive("t-local", "run_python", "calling");
  await new Promise((r) => setTimeout(r, 120));
  const a = C.piezaConActividad("t-local");
  C.toolLive("t-local", "run_python", null);
  return { a, b: C.piezaConActividad("t-local") };
});
ok(vivo.a === true && vivo.b === false, "punto vivo: la actividad es CAPA (se prende y se apaga en los dos modos)");

// ══ l · CERO CÓDIGO RENDERIZADO ═════════════════════════════════════════════════════
console.log("\n§l · el código se abre en VS Code; nada de editores en un popup");
const cod = await page.evaluate(async () => {
  const tabs = [...document.querySelectorAll("#inspector .tab")].map((t) => t.dataset.d);
  const d = window.__cuarto.pieceData("t-local");
  window.__openInspector(d);
  await new Promise((r) => setTimeout(r, 300));
  document.querySelector('#inspector .tab[data-d="viz"]').click();
  await new Promise((r) => setTimeout(r, 250));
  const dt = document.querySelector("#d-viz details.dt");
  const preSueltos = [...document.querySelectorAll("#inspector pre.code")]
    .filter((p) => !p.closest("details.dt")).length;
  return { tabs, code: !!document.getElementById("d-code"), gancho: typeof window.__cuartoAplicarReceta,
           dt: !!dt, dtAbierto: !!(dt && dt.open), preSueltos };
});
ok(!cod.code && !cod.tabs.includes("code"), "no hay tab Código", cod.tabs.join("·"));
ok(cod.gancho === "undefined", "no se construyó window.__cuartoAplicarReceta", cod.gancho);
ok(cod.dt && !cod.dtAbierto, "el detalle técnico existe y nace plegado");
ok(cod.preSueltos === 0, "cero código renderizado fuera del detalle técnico", String(cod.preSueltos));
const vsc = await page.evaluate(async () => {
  document.querySelector("#d-viz details.dt > summary").click();
  await new Promise((r) => setTimeout(r, 1600));
  const b = document.querySelector("#d-viz [data-abrir]");
  const p = document.querySelector("#d-viz .dt-path");
  return { boton: b ? b.textContent.trim() : null, path: p ? p.textContent : null };
});
ok(vsc.boton && /VS Code/.test(vsc.boton), "trae el botón al editor de verdad", vsc.boton);
ok(!!vsc.path, "…con el path visible debajo", vsc.path);

// ══ m · LAS DOS BARRAS, TOKENIZADAS ═════════════════════════════════════════════════
console.log("\n§m · #gatebar y #unequipbar giran con el tema");
const barras = await page.evaluate(async () => {
  const lee = () => {
    const g = document.getElementById("gatebar"), u = document.getElementById("unequipbar");
    g.hidden = false; u.hidden = false;
    const gh = getComputedStyle(document.getElementById("gateHead")).color;
    const un = getComputedStyle(document.getElementById("unequipName")).color;
    const go = getComputedStyle(document.getElementById("gateOk")).backgroundColor;
    g.hidden = true; u.hidden = true;
    return { gh, un, go };
  };
  const oscuro = lee();
  window.AlephTheme && window.AlephTheme.set && window.AlephTheme.set("light");
  await new Promise((r) => setTimeout(r, 250));
  const claro = lee();
  window.AlephTheme && window.AlephTheme.set && window.AlephTheme.set("dark");
  await new Promise((r) => setTimeout(r, 200));
  return { oscuro, claro };
});
ok(barras.oscuro.gh !== barras.claro.gh, "#gateHead cambia de color con el tema", `${barras.oscuro.gh} → ${barras.claro.gh}`);
ok(barras.oscuro.un !== barras.claro.un, "#unequipName cambia con el tema", `${barras.oscuro.un} → ${barras.claro.un}`);
ok(barras.oscuro.go !== barras.claro.go, "#gateOk cambia con el tema", `${barras.oscuro.go} → ${barras.claro.go}`);

// ══ + · CERO <function=…> CRUDO ═════════════════════════════════════════════════════
console.log("\n§+ · el chat del Guía no renderiza texto crudo de tool-call");
const crudo = await page.evaluate(() => {
  const f = window.__stripRawCalls || null;
  const txt = 'listo <function=equipar_catalogo{"servicio":"gmail"}></function> y sigo';
  return { hay: !!f, limpio: f ? f(txt) : null };
});
if (crudo.hay) ok(!/<function=/.test(crudo.limpio || ""), "stripRawCalls saca el <function=…> crudo", crudo.limpio);
else ok(!/copLine\("g", text\)/.test(render), "el render de mensajes del Guía pasa por el filtro (hook no expuesto)");

await browser.close();
console.log(`\n${fails.length ? "✗ FALLOS: " + fails.length : "✓ TODO VERDE"}`);
fails.forEach((f) => console.log("   · " + f));
process.exit(fails.length ? 1 : 0);
