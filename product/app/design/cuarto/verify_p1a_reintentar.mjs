/* verify_p1a_reintentar.mjs — FIX-P1A · EL [REINTENTAR] QUE ACTÚA.
 *
 * La vara de la ola 2 de R probaba que el abanico ABRE con las acciones correctas. No probaba
 * que las acciones ACTÚAN. Ese hueco tiene nombre: PINTADO ≠ CABLEADO. Esta vara cierra el
 * hueco, y por eso:
 *   · NO usa element.click() para lo que mide un botón: usa el MOUSE REAL de WebKit, que
 *     respeta hit-testing (un botón de 0×0, tapado o deshabilitado NO se puede tocar);
 *   · mide EFECTO en la red (POST /v1/motor/probar) y en el DOM, no presencia de etiquetas;
 *   · rompe una pieza DE VERDAD (cfd: su servidor no levanta en esta máquina) — cero
 *     stubs, cero motor falso;
 *     [FIX-P1B] la fixture ERA `kicad-sch` y dejó de servir para medir el [Reintentar]: su
 *     intérprete no existe, y el motor ahora lo diagnostica ANTES de intentar (binario
 *     ausente → `cli_no_instalado` → [Instalarlo]). Ofrecerle un reintento a un programa que
 *     no está instalado es el «reintento al vacío» que §7 prohíbe. La pieza correcta para
 *     medir el reintento es una cuyo fallo SÍ pueda cambiar entre un intento y el siguiente:
 *     `cfd` (su servidor no arranca) da `error_upstream`, que es reintentable y falla en
 *     0,1 s. Ninguna aserción cambió: cambió la pieza que se rompe;
 *     [FIX-P11] y volvió a pasar, por el mismo motivo y con mejor diagnóstico: `cfd` corre
 *     sobre `docker run openfoam-mcp`, y el motor ahora chequea el SEGUNDO NIVEL — Docker
 *     instalado pero APAGADO (§5). Eso ya no es `error_upstream`: es `cli_no_instalado` con
 *     nivel `servicio_caido`, y su camino correcto es [Arrancar Docker], no [Reintentar]
 *     (reintentar contra un demonio apagado es el reintento al vacío que §7 prohíbe). La
 *     fixture pasa a `visor-segmentacion`, cuyo servidor SÍ arranca y SÍ falla de un modo
 *     que puede cambiar entre un intento y el siguiente. Ninguna aserción cambió;
 *   · trae su propia CALIBRACIÓN EN ROJO: con el cableado desconectado a propósito, las
 *     mismas aserciones tienen que FALLAR. Si pasan, la vara es ciega y esto sale en rojo.
 *
 * Las TRES entradas medidas (las tres del bug):
 *   1. el abanico de la pieza      → #abActs .ab-act[data-act="camino"]
 *   2. el panel de bloqueo         → #listoBtn  y  #preflightList .pf-fix
 *   3. el chip de LAS PIEZAS       → .prow .prow-sem .sem-accion
 *
 * Run:  SIDECAR=http://127.0.0.1:8271 node product/app/design/cuarto/verify_p1a_reintentar.mjs
 */
import { webkit } from "playwright";

const BASE = process.env.SIDECAR || "http://127.0.0.1:8271";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;
const PIEZA_ROTA = process.env.PIEZA || "visor-segmentacion";   // rojo REAL y REINTENTABLE

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

const browser = await webkit.launch();

// ══ el arnés: una página con la pieza rota equipada y ya probada (roja de verdad) ══════
async function montar() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const st = { posts: 0, errs: [], dialogos: [] };
  page.on("request", (r) => { if (/\/v1\/motor\/probar/.test(r.url())) st.posts++; });
  page.on("pageerror", (e) => st.errs.push(String(e)));
  page.on("dialog", async (d) => { st.dialogos.push(d.type() + ":" + d.message().slice(0, 60)); await d.dismiss(); });
  await page.goto(PAGE, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!window.__catalog && !!window.__preflight, null, { timeout: 60000 });
  await sleep(1200);
  const eq = await page.evaluate(async (id) => {
    window.__semLatidoInstante = false;               // el latido se mide de verdad
    const cat = window.__catalog, C = window.__cuarto;
    const list = cat.entries || cat.atoms || [];
    const e = list.find((x) => x.id === id);
    if (!e) return { ok: false };
    C.placeTile(Object.assign({}, e, { id: "t-roto" }));
    window.__sync && window.__sync();
    const S = window.CuartoSemaforo, H = window.__semHooks;
    const c = H.semCoordDe(C.pieceData("t-roto"));
    const r = await S.probar(c.tipo, c.ref, c.opts || {});        // la PRIMERA prueba: el rojo real
    if (S.reiniciarIntentos) S.reiniciarIntentos();               // (baseline: no existe)
    window.__renderPieces();
    if (window.__legendOpen) window.__legendOpen(true);           // LAS PIEZAS abierto
    await new Promise((x) => setTimeout(x, 2400));
    await window.__preflight();
    return { ok: true, estado: r.estado, causa: r.causa, detail: (r.evidencia || {}).detail };
  }, PIEZA_ROTA);
  return { page, st, eq };
}

// caja + hit-test + click con MOUSE REAL. `null` si no se puede tocar.
async function tocar(page, sel) {
  const info = await page.evaluate((s) => {
    const el = document.querySelector(s); if (!el) return { falta: true };
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return { sinCaja: true, txt: el.textContent.trim() };
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    return { x: cx, y: cy, w: Math.round(r.width), h: Math.round(r.height),
             txt: el.textContent.trim(), disabled: !!el.disabled,
             tapado: !(top === el || el.contains(top)),
             quienRecibe: top ? (top.tagName.toLowerCase() + (top.className ? "." + String(top.className).split(/\s+/)[0] : "")) : null };
  }, sel);
  if (info.falta || info.sinCaja || info.tapado || info.disabled) return { info, tocado: false };
  await page.mouse.click(info.x, info.y);
  return { info, tocado: true };
}

// ¿el latido está EN el botón que se apretó, mientras la prueba corre?
async function latidoDe(page, sel) {
  return await page.evaluate((s) => {
    const el = document.querySelector(s); if (!el) return { falta: true };
    const t = el.querySelector(".ab-t") || el;
    return { probando: el.dataset.probando === "1", busy: el.getAttribute("aria-busy") === "true",
             disabled: !!el.disabled, txt: (t.textContent || "").trim() };
  }, sel);
}



const leerOut = (page, sel) => page.evaluate((s) => {
  const h = document.querySelector(s);
  if (!h) return { falta: true, hay: false, estado: null, titulo: null, sub: null, crudo: null,
                   crudoAbierto: null, mano: null, manoAbierto: null, salidas: [] };
  const q = (x) => h.querySelector(x);
  return {
    hay: !!q(".sem-out-linea"),
    estado: h.getAttribute("data-estado"),
    titulo: (q(".sem-out-tit") || {}).textContent || null,
    sub: (q(".sem-out-sub") || {}).textContent || null,
    crudo: q(".sem-out-crudo") ? (q(".sem-out-crudo pre").textContent || "") : null,
    crudoAbierto: q(".sem-out-crudo") ? q(".sem-out-crudo").open : null,
    mano: q(".sem-out-mano") ? (q(".sem-out-mano pre").textContent || "") : null,
    manoAbierto: q(".sem-out-mano") ? q(".sem-out-mano").open : null,
    salidas: [...h.querySelectorAll(".sem-salida")].map((b) => b.textContent.trim()),
  };
}, sel);

// ═════════════════════════════════════════════════════════════════════════════════════
// PASADA 1 · EL CABLEADO REAL
// ═════════════════════════════════════════════════════════════════════════════════════
console.log("══ PASADA 1 · el cableado real (WebKit, mouse real, motor real) ══");
let { page, st, eq } = await montar();
ok(eq.ok, `la pieza rota (${PIEZA_ROTA}) se equipa`, eq.estado ? `${eq.estado}/${eq.causa}` : "");
ok(eq.estado === "roto", "…y el MOTOR la declara roja de verdad (cero stub)", eq.detail || "");
ok(st.errs.length === 0, "la página carga sin errores de JS", st.errs.slice(0, 2).join(" | "));

// ── §0 · la función ÚNICA existe y es la que consumen P1B/P3/P7 ───────────────────────
console.log("\n§0 · probarPieza() — la función única");
const api = await page.evaluate(() => ({
  pagina: typeof window.__probarPieza,
  motor: typeof (window.CuartoSemaforo || {}).probarPieza,
  desenlace: typeof (window.CuartoSemaforo || {}).pintarDesenlace,
  limite: (window.CuartoSemaforo || {}).REINTENTOS_ANTES_DE_MUTAR,
}));
ok(api.pagina === "function", "window.__probarPieza(pieza, {boton, host}) existe", api.pagina);
ok(api.motor === "function" && api.desenlace === "function",
   "…y su máquina de estado compartida: Sem.probarPieza + Sem.pintarDesenlace");
ok(api.limite === 1, "el reintento se gasta a la PRIMERA vuelta roja (el rojo previo es el fallo nº1)", String(api.limite));

// ══ ENTRADA 1 · EL ARCO DE LA PIEZA ══════════════════════════════════════════════════
/* [FIX-P3 · §2] LA FUSIÓN. Acá había DOS botones para el MISMO disparo: el slot [Probar] y
 * el camino [Reintentar]. Se fusionaron en UNO: cuando la pieza está en rojo, el slot de
 * prueba se llama [Probar de nuevo]. La vara se re-apunta a esa entrada y se ENDURECE: ya no
 * alcanza con que exista un botón que reintente — se exige además que NO exista un segundo
 * botón «Reintentar» suelto en ninguna parte del Cuarto. */
console.log("\n§1 · ENTRADA 1 — el arco de la pieza");
await page.evaluate(async () => { if (window.CuartoSemaforo.reiniciarIntentos) window.CuartoSemaforo.reiniciarIntentos(); window.__openAbanico(window.__cuarto.pieceData("t-roto")); await new Promise((r) => setTimeout(r, 450)); });
const SEL_AB = '#abActs .ab-act[data-act="probar"]';
const ab0 = await page.evaluate((s) => { const b = document.querySelector(s); return b ? b.textContent.trim() : null; }, SEL_AB);
ok(/Probar de nuevo/.test(ab0 || ""), "§2 · la pieza rota ofrece [Probar de nuevo] (el mismo botón que [Probar])", ab0 || "no existe");
const sueltos = await page.evaluate(() =>
  [...document.querySelectorAll("button, a")].filter((b) => /reintentar/i.test((b.textContent || "").trim()))
    .map((b) => (b.id || b.className || b.tagName) + ":" + b.textContent.trim()));
ok(sueltos.length === 0, "§2 · CERO botón «Reintentar» separado en todo el Cuarto", sueltos.join(" | ") || "ninguno");
// §3 · el ARCO, no una pila: radios ~iguales y ángulos que avanzan alrededor de la pieza
const arco = await page.evaluate(() => window.__abanicoArco());
const radios = (arco.items || []).map((i) => i.radio);
const spread = radios.length ? Math.max(...radios) - Math.min(...radios) : 999;
const xs = new Set((arco.items || []).map((i) => i.dx));
ok(arco.items.length >= 3 && spread <= 6 && xs.size > 1,
   "§1 · es un ARCO (radios ~iguales, x que varía), no un card apilado",
   `n=${arco.items.length} radios=${JSON.stringify(radios)} dx únicos=${xs.size}`);
// §5 · ANTES de tocar nada: una pieza roja YA muestra su error real plegado. Se mide acá para
// que el «reintenté» de después sea atribuible AL CLICK y no al estado que ya estaba.
const antesAb = await leerOut(page, "#abMsg");
ok(!!antesAb.crudo && antesAb.crudo.length > 10, "§5 · el error real ya está plegado antes de tocar nada", (antesAb.crudo || "").slice(0, 60));
// [FIX-P3 · §6] …y SIN repetir el estado: eso lo dice el pie del arco. Antes de probar, el
// popup no tiene desenlace que contar — tiene un error que ofrecer.
ok(!antesAb.hay, "…sin repetir la línea de estado que ya dice el pie (una información, un dueño)");
ok(!/reintent/i.test(antesAb.sub || ""), "…y todavía NO dice «reintenté» (línea base del click)", antesAb.sub || "");
st.posts = 0;
const t1 = await tocar(page, SEL_AB);
ok(t1.tocado, "…y un MOUSE REAL lo alcanza (no 0×0, no tapado, no disabled)", JSON.stringify(t1.info));
const lat1 = await latidoDe(page, SEL_AB);
ok(lat1.probando && /Probando/i.test(lat1.txt),
   "LATIDO: el botón que se apretó dice «Probando…» mientras corre", JSON.stringify(lat1));
await sleep(2600);
ok(st.posts >= 1, "…y salió una prueba REAL al motor (POST /v1/motor/probar)", `posts=${st.posts}`);
const out1 = await leerOut(page, "#abMsg");
ok(out1.hay && out1.estado === "roto", "DESENLACE: el arco dice el resultado, no queda mudo", `${out1.titulo} · ${out1.sub}`);
ok(/reintent/i.test(out1.sub || ""), "…y dice que lo reintentó (no repite el mismo rótulo de antes)", out1.sub || "");
ok(/\d\d:\d\d:\d\d/.test(out1.sub || ""), "…con la hora del resultado", out1.sub || "");
ok(!!out1.crudo && out1.crudo.length > 10, "…y el ERROR REAL plegado debajo (§5)", (out1.crudo || "").slice(0, 70));
ok(out1.crudo !== "Error del proveedor" && !/^Error del proveedor$/.test(out1.titulo + out1.crudo),
   "«Error del proveedor» dejó de ser texto terminal", `titulo=${out1.titulo}`);
// §3 · la línea de ESTADO al pie del arco: el color, la causa y su [?]
const pie1 = await page.evaluate(() => window.__abanicoEstado());
ok(pie1 && pie1.estado === "roto" && /Roto/.test(pie1.txt || "") && pie1.ayuda,
   "§3 · el pie del arco dice «Roto · causa» y trae su [?]", JSON.stringify(pie1));
// §4 · SEGUNDA VUELTA: el camino MUTA al workflow (no a otro reintento)
const ab1 = await page.evaluate(() => {
  const acts = window.__abanicoActs();
  return { acts: acts.map((a) => a.act + ":" + a.label), reintentar: acts.some((a) => /Reintentar/.test(a.label)) };
});
ok(!ab1.reintentar, "§4 · gastado el reintento, el arco NO ofrece un [Reintentar] suelto", ab1.acts.join(" · "));
ok(ab1.acts.some((a) => /^camino:.*(Arreglarlo|Configurar)/.test(a)),
   "§4 · …y el CAMINO muta al workflow de su tipo ([Arreglarlo] local · [Configurar] cuenta)", ab1.acts.join(" · "));
ok(ab1.acts.some((a) => /^quitar:/.test(a)), "§4 · …con [Quitar] siempre a mano", ab1.acts.join(" · "));
/* §5 · BUG #34 · UNICIDAD. El popup de mutación imprimía cada salida DOS veces: como
 * `<summary>` de su pliegue y otra vez como botón de `.sem-salidas`. La aserción vieja sólo
 * miraba `.sem-salida`, así que era ciega a su propio duplicado. Ahora se cuenta en TODO el
 * DOM: cada salida, exactamente una vez. */
const unicidad = await page.evaluate(() => {
  const pop = document.getElementById("abanico");
  const cuenta = (frase) => [...pop.querySelectorAll("*")]
    .filter((el) => !el.children.length && (el.textContent || "").trim() === frase).length;
  return { verError: cuenta("Ver el error completo"), aMano: cuenta("Probar el server a mano"),
           quitar: cuenta("Quitar"), arreglar: cuenta("Arreglarlo") + cuenta("Configurar") };
});
ok(unicidad.verError === 1 && unicidad.aMano === 1 && unicidad.quitar === 1 && unicidad.arreglar === 1,
   "§5 · #34 · cada salida aparece UNA vez DENTRO del popup de la pieza", JSON.stringify(unicidad));
// cada destino de la mutación FUNCIONA
const tVer = await tocar(page, "#abMsg .sem-out-crudo > summary");
await sleep(400);
const outVer = await leerOut(page, "#abMsg");
ok(tVer.tocado && outVer.crudoAbierto === true, "destino 1: [Ver el error completo] ABRE el error crudo", `abierto=${outVer.crudoAbierto}`);
ok(st.dialogos.length === 0, "…sin un window.alert() (en la .app un modal nativo es humo)", st.dialogos.join(" | "));
const tMano = await tocar(page, "#abMsg .sem-out-mano > summary");
await sleep(400);
const outMano = await leerOut(page, "#abMsg");
ok(tMano.tocado && outMano.manoAbierto === true, "destino 2: [Probar el server a mano] ABRE el cómo", `abierto=${outMano.manoAbierto}`);
ok(/curl -s -X POST/.test(outMano.mano || "") && /v1\/motor\/probar/.test(outMano.mano || ""),
   "…con el pedido EXACTO, copiable", (outMano.mano || "").split("\n").find((l) => /curl/.test(l)) || "");
const tQuitar = await tocar(page, '#abActs .ab-act[data-act="quitar"]');
await sleep(700);
const quitada = await page.evaluate(() => window.__cuarto.placedTiles().some((t) => t.id === "t-roto"));
ok(tQuitar.tocado && !quitada, "destino 3: [Quitar] SACA la pieza del cuarto", `sigue=${quitada}`);

// ══ ENTRADA 2 · EL PANEL DE BLOQUEO ══════════════════════════════════════════════════
console.log("\n§2 · ENTRADA 2 — el panel «N piezas frenan la entrega»");
await page.close();
({ page, st, eq } = await montar());
await page.evaluate(async () => { if (window.CuartoSemaforo.reiniciarIntentos) window.CuartoSemaforo.reiniciarIntentos(); await window.__preflight(); await new Promise((r) => setTimeout(r, 400)); });
const pf0 = await page.evaluate(() => ({
  listo: (document.getElementById("listoBtn") || {}).textContent,
  fila: (document.querySelector("#preflightList .pf-fix") || {}).textContent,
  visible: !document.getElementById("preflight").hidden,
}));
ok(pf0.visible && /Probar de nuevo/.test(pf0.fila || ""), "§2 · la fila de la pieza que frena ofrece [Probar de nuevo]", JSON.stringify(pf0));
st.posts = 0;
const t2 = await tocar(page, "#preflightList .pf-fix");
ok(t2.tocado, "…y un MOUSE REAL lo alcanza", JSON.stringify(t2.info));
const lat2 = await latidoDe(page, "#preflightList .pf-fix");
ok(lat2.probando && /Probando/i.test(lat2.txt), "LATIDO en el botón de la fila", JSON.stringify(lat2));
await sleep(2600);
ok(st.posts >= 1, "…prueba REAL al motor", `posts=${st.posts}`);
const out2 = await leerOut(page, "#preflightList .pf-item .pf-out");
ok(out2.hay && /reintent/i.test(out2.sub || ""), "DESENLACE en la fila: qué pasó, no el mismo rótulo", `${out2.titulo} · ${out2.sub}`);
/* [FIX-P3 · §6] …y el ERROR ya NO vive acá: el panel no es su dueño. La fila dice qué pasó
 * (ley 4) y ofrece [Ver error →], que enfoca la pieza y abre SU popup. La aserción se
 * endurece: antes bastaba con que el crudo estuviera; ahora se exige que NO esté Y que el
 * camino al dueño exista. */
ok(!out2.crudo, "§6 · …y el panel NO copia el error (su dueño es la pieza)");
const verEnFila = await page.evaluate(() => !!document.querySelector('#preflightList .pf-out [data-salida="ir_error"]'));
ok(verEnFila, "§6 · …pero SÍ ofrece el camino: [Ver error →]");
const pf1 = await page.evaluate(() => {
  const b = document.querySelector("#preflightList .pf-fix");
  return { txt: b ? b.textContent.trim() : null, mutado: b ? b.dataset.mutado : null, accion: b ? b.dataset.accion : null,
           listo: (document.getElementById("listoBtn") || {}).textContent.trim() };
});
ok(pf1.mutado === "1" && !/Probar de nuevo/.test(pf1.txt || ""), "§4 · la fila MUTA: deja de reintentar", JSON.stringify(pf1));
ok(!/Probar de nuevo/.test(pf1.listo || ""), "…y el badge de arriba también (el reintento se gastó, no por botón)", pf1.listo);
const t2b = await tocar(page, "#preflightList .pf-fix");
await sleep(700);
const out2b = await page.evaluate(() => {
  const c = document.querySelector("#abMsg .sem-out-crudo");
  return { arco: window.__abanicoAbierto(), crudoAbierto: c ? c.open : null };
});
ok(t2b.tocado && out2b.arco && out2b.crudoAbierto === true,
   "§6 · el botón mutado de la fila LLEVA al dueño: abre el popup de la pieza con el error destapado", JSON.stringify(out2b));
// el badge del panel: su CTA también prueba de verdad (era el camino más mudo)
await page.evaluate(async () => { if (window.CuartoSemaforo.reiniciarIntentos) window.CuartoSemaforo.reiniciarIntentos(); await window.__preflight(); await new Promise((r) => setTimeout(r, 350)); });
const badge0 = await page.evaluate(() => (document.getElementById("listoBtn") || {}).textContent.trim());
ok(/Probar de nuevo/.test(badge0), "§2 · el badge de listo-para-la-Sala vuelve a ofrecer [Probar de nuevo]", badge0);
st.posts = 0;
const t2c = await tocar(page, "#listoBtn");
const lat2c = await latidoDe(page, "#listoBtn");
ok(t2c.tocado && lat2c.probando, "LATIDO en el CTA del badge (antes no tenía ninguno)", JSON.stringify(lat2c));
await sleep(2600);
ok(st.posts >= 1, "…y su prueba también es REAL", `posts=${st.posts}`);

/* ══ ENTRADA 3 · EL REGISTRO → EL POPUP DE LA PIEZA ═══════════════════════════════════
 * [FIX-P3 · §6 §7] La tercera entrada ERA el chip de la lista de piezas. Esa lista murió: el
 * error tenía DOS dueños (el panel lo incrustaba entero y el popup de la pieza lo mostraba a
 * la vez) y el dictado del 27-jul dice que el dueño es la pieza. Lo que queda en el panel es
 * el REGISTRO: una línea por evento y un [Ver error →] que no muestra nada — ENFOCA la pieza
 * y abre SU popup.
 *
 * Así que la tercera entrada es ésa, y la vara se ENDURECE en tres cosas que antes no podía
 * ni preguntar:
 *   · el panel NO puede contener el texto del error (unicidad en todo el DOM);
 *   · [Ver error →] tiene que ABRIR el arco de ESA pieza y destapar su crudo;
 *   · y desde ahí, [Probar de nuevo] sigue teniendo latido, prueba real y desenlace.        */
console.log("\n§3 · ENTRADA 3 — el registro lleva al popup de la pieza");
await page.close();
({ page, st, eq } = await montar());
const reg = await page.evaluate(async () => {
  if (window.CuartoSemaforo.reiniciarIntentos) window.CuartoSemaforo.reiniciarIntentos();
  window.__limpiarLogs();
  window.__legendOpen(true);
  await window.__probarPieza("t-roto", { motivo: "manual" });     // falla → entra al registro
  await new Promise((r) => setTimeout(r, 900));
  const fila = document.querySelector("#logList .logrow.bad");
  return { filas: document.querySelectorAll("#logList .logrow").length,
           pieza: fila ? (fila.querySelector(".logp") || {}).textContent : null,
           hora: fila ? (fila.querySelector(".logt") || {}).textContent : null,
           hayVer: !!(fila && fila.querySelector("[data-ver]")),
           txt: fila ? fila.textContent.trim() : null };
});
ok(reg.filas >= 1 && reg.pieza && /^\d\d:\d\d$/.test(reg.hora || ""),
   "§6 · la falla deja UNA línea en el registro: pieza · qué pasó · hora", JSON.stringify(reg));
ok(reg.hayVer, "…con su [Ver error →] (el único camino al error desde el registro)", reg.txt || "");
/* §6 · UNICIDAD DEL ERROR: con la pieza rota, el texto del error tiene que aparecer UNA sola
 * vez en TODO el DOM. Antes aparecía dos: incrustado en el panel y en el popup de la pieza. */
const crudoReal = await page.evaluate(() => {
  const d = (window.__desenlaces() || [])[0];
  return d ? String(d.crudo || "").split("\n")[0].trim() : null;
});
const antesDeAbrir = await page.evaluate((frag) => {
  if (!frag || frag.length < 8) return -1;
  return [...document.querySelectorAll("*")].filter((el) => !el.children.length &&
    (el.textContent || "").includes(frag)).length;
}, crudoReal);
ok(antesDeAbrir === 0, "§6 · el panel NO incrusta el error: con el popup cerrado, cero copias en el DOM",
   `«${(crudoReal || "").slice(0, 46)}» ×${antesDeAbrir}`);
const t3 = await tocar(page, "#logList .logrow.bad [data-ver]");
ok(t3.tocado, "…y un MOUSE REAL alcanza el [Ver error →]", JSON.stringify(t3.info));
await sleep(600);
const trasVer = await page.evaluate((frag) => {
  const abierto = window.__abanicoAbierto && window.__abanicoAbierto();
  const acts = window.__abanicoActs ? window.__abanicoActs().map((a) => a.act) : [];
  const cru = document.querySelector("#abMsg .sem-out-crudo");
  const copias = frag && frag.length >= 8
    ? [...document.querySelectorAll("*")].filter((el) => !el.children.length && (el.textContent || "").includes(frag)).length : -1;
  return { abierto, acts, crudoAbierto: cru ? cru.open : null, copias };
}, crudoReal);
ok(trasVer.abierto && trasVer.acts.includes("probar"),
   "§6 · [Ver error →] ENFOCA la pieza y abre SU popup (no muestra el error en el panel)", JSON.stringify(trasVer.acts));
ok(trasVer.crudoAbierto === true, "…con el error crudo DESTAPADO (el clic pidió verlo, no buscarlo)");
ok(trasVer.copias === 1, "§6 · VARA DE UNICIDAD: el texto del error aparece UNA vez en todo el DOM", `copias=${trasVer.copias}`);
// …y desde esta tercera entrada, la prueba sigue siendo real
st.posts = 0;
const SEL_CHIP = '#abActs .ab-act[data-act="probar"]';
const chip0 = await page.evaluate((s) => { const b = document.querySelector(s); return b ? b.textContent.trim() : null; }, SEL_CHIP);
ok(/Probar de nuevo/.test(chip0 || ""), "el arco abierto desde el registro ofrece [Probar de nuevo]", chip0 || "no existe");
const t3b = await tocar(page, SEL_CHIP);
ok(t3b.tocado, "…y un MOUSE REAL lo alcanza", JSON.stringify(t3b.info));
const lat3 = await latidoDe(page, SEL_CHIP);
ok(lat3.probando && /Probando/i.test(lat3.txt), "LATIDO en el botón del arco", JSON.stringify(lat3));
await sleep(2800);
ok(st.posts >= 1, "…prueba REAL al motor", `posts=${st.posts}`);
const out3 = await leerOut(page, "#abMsg");
ok(out3.hay && /reintent/i.test(out3.sub || ""), "DESENLACE bajo el arco", `${out3.titulo} · ${out3.sub}`);
ok(!!out3.crudo && out3.crudo.length > 10, "…con el error real plegado", (out3.crudo || "").slice(0, 60));
/* §4 · el camino mutado + las salidas cubren los destinos reales, SIN repetir ninguno.
 * [FIX-P1B · §1] El botón mutado abre EL WORKFLOW de su tipo. [FIX-P3 · §5] Y la aserción de
 * «sin repetirse» se endurece: ya no se compara el botón contra `.sem-salida` solamente —se
 * cuenta en TODO el popup, que es donde vivía el #34. */
const chipMut = await page.evaluate(() => {
  const acts = window.__abanicoActs();
  const cam = acts.find((a) => a.act === "camino");
  const pop = document.getElementById("abanico");
  const cuenta = (f) => [...pop.querySelectorAll("*")].filter((el) => !el.children.length && (el.textContent || "").trim() === f).length;
  return { txt: cam ? cam.label.replace(/^→\s*/, "") : null, acts: acts.map((a) => a.act),
           salidas: [...document.querySelectorAll("#abMsg .sem-salida")].map((b) => b.textContent.trim()),
           dupVer: cuenta("Ver el error completo"), dupMano: cuenta("Probar el server a mano") };
});
ok(/Arreglarlo|Configurar/.test(chipMut.txt || "") && chipMut.acts.includes("quitar"),
   "§4 · el camino MUTA a un WORKFLOW y [Quitar] sigue disponible", JSON.stringify(chipMut.acts) + " · " + chipMut.txt);
ok(chipMut.dupVer === 1 && chipMut.dupMano === 1,
   "§4 · …sin repetir ningún destino DENTRO del popup (#34 cerrado)", JSON.stringify(chipMut));
ok(st.dialogos.length === 0, "la tercera entrada nunca cae en un window.alert()", st.dialogos.join(" | "));

// ── §4 · el desenlace SOBREVIVE al repintado (era la mitad silenciosa del bug) ────────
console.log("\n§4 · el desenlace sobrevive al repintado de la superficie");
/* [FIX-P3 · §7 §8] la fila murió, así que el desenlace se mide donde vive: el ARCO. Y de
 * paso se mide la CARRERA: `renderPieces()` dispara el barrido de lecturas baratas, y ese
 * barrido NO puede degradar a «sin probar» una pieza que se acaba de probar. */
const sobrevive = await page.evaluate(async () => {
  window.__renderPieces(); await new Promise((r) => setTimeout(r, 2400));
  window.__openAbanico(window.__cuarto.pieceData("t-roto"));
  await new Promise((r) => setTimeout(r, 450));
  return { estadoTrasBarrido: (window.__abanicoEstado() || {}).estado,
           abanico: !!document.querySelector("#abMsg .sem-out-linea"),
           guardados: (window.__desenlaces ? window.__desenlaces() : []).length };
});
ok(sobrevive.estadoTrasBarrido === "roto",
   "§8 · tras renderPieces() el barrido NO pisó el resultado de la prueba", sobrevive.estadoTrasBarrido);
ok(sobrevive.abanico, "…y el arco sigue mostrando el desenlace, sin volver a probar");
ok(sobrevive.guardados >= 1, "una sola fuente de verdad del desenlace por pieza", `n=${sobrevive.guardados}`);
// la MUTACIÓN también sobrevive: un repintado no puede devolver un [Reintentar] flamante
// sobre un reintento ya gastado — sería el botón que te deja igual, otra vez.
const mutSobrevive = await page.evaluate(async () => {
  window.__closeAbanico && window.__closeAbanico();
  window.__renderPieces(); await new Promise((r) => setTimeout(r, 2400));
  window.__openAbanico(window.__cuarto.pieceData("t-roto"));
  await new Promise((r) => setTimeout(r, 450));
  const acts = window.__abanicoActs();
  const cam = acts.find((a) => a.act === "camino");
  return { txt: cam ? cam.label.replace(/^→\s*/, "") : null,
           salidas: [...document.querySelectorAll("#abMsg .sem-salida")].map((x) => x.textContent.trim()) };
});
ok(/Arreglarlo|Configurar/.test(mutSobrevive.txt || ""),
   "…y la MUTACIÓN sobrevive al repintado (el camino sigue siendo el workflow, no otro reintento)", JSON.stringify(mutSobrevive));
ok(!mutSobrevive.salidas.some((s) => s === mutSobrevive.txt),
   "…sin repetir el mismo destino en el camino y en las salidas", `camino=${mutSobrevive.txt} · salidas=${mutSobrevive.salidas.join("·")}`);

// ── §5 · verde con evidencia + hora (el desenlace no es sólo para el rojo) ────────────
console.log("\n§5 · el desenlace del VERDE: evidencia + hora");
const verde = await page.evaluate(async () => {
  const host = document.createElement("div"); host.id = "vhost"; document.body.appendChild(host);
  const S = window.CuartoSemaforo;
  if (!S.probarPieza) return { sinApi: true };
  // Verde REAL y determinista: el MCP local no depende de una llave personal del entorno.
  const belt = "catalog/templates/kit/belt-kit.mcp.json";
  const out = await S.probarPieza({
    coord: { tipo: "mcp", ref: belt, opts: { belt_ref: belt, backed_by: "pysandbox" } },
    host
  });
  return { estado: out.res.estado, titulo: out.texto.titulo, sub: out.texto.sub, gastado: out.gastado,
           salidas: [...host.querySelectorAll(".sem-salida")].map((b) => b.textContent) };
});
if (verde.estado === "probado") {
  ok(/Probado/.test(verde.titulo) && /\d\d:\d\d:\d\d/.test(verde.sub), "verde → «Probado» + hora", `${verde.titulo} · ${verde.sub}`);
  ok(/ms/.test(verde.sub), "…y evidencia del motor (latencia)", verde.sub);
  ok(!verde.gastado && verde.salidas.length === 0, "…y el verde NO muta nada (no hay reintento que gastar)");
} else {
  ok(false, "no pude conseguir un verde real del motor para medir su desenlace", JSON.stringify(verde));
}

// ── §6 · sin coordenada: el botón DICE por qué, no calla ─────────────────────────────
console.log("\n§6 · una pieza sin nada probable NO cae en silencio");
const sinCoord = await page.evaluate(async () => {
  const host = document.createElement("div"); document.body.appendChild(host);
  if (!window.CuartoSemaforo.probarPieza) { host.remove(); return { sinApi: true }; }
  const out = await window.CuartoSemaforo.probarPieza({ coord: null, host });
  const r = { estado: out.res.estado, crudo: out.crudo, hay: !!host.querySelector(".sem-out-linea") };
  host.remove(); return r;
});
ok(sinCoord.hay && sinCoord.estado === "roto" && /no declara|no hay qu/i.test(sinCoord.crudo),
   "probarPieza() sin coordenada devuelve un rojo honesto (jamás un no-op)", (sinCoord.crudo || "").slice(0, 80));

const errsFinal = st.errs.slice();
await page.close();

// ═════════════════════════════════════════════════════════════════════════════════════
// PASADA 2 · CALIBRACIÓN EN ROJO — con el cableado cortado, esto TIENE que fallar
// ═════════════════════════════════════════════════════════════════════════════════════
console.log("\n══ PASADA 2 · CALIBRACIÓN EN ROJO (cableado cortado a propósito) ══");
// El sabotaje es EL BUG, reproducido a mano: el botón queda PINTADO y sin handler. Clonar
// un nodo copia atributos y texto pero NO los listeners (ni onclick), así que el botón se ve
// idéntico y no hace nada — exactamente el «botón pintado» que hay que cazar. Se hace en las
// TRES entradas: si alguna aserción de efecto sobrevive, esa aserción es ciega.
const descablear = (page, sel) => page.evaluate((s) => {
  const b = document.querySelector(s); if (!b) return false;
  const clon = b.cloneNode(true); clon.onclick = null; b.replaceWith(clon); return true;
}, sel);

async function calibrar(nombre, prepara, sel, hostOut, medirActs) {
  const m = await montar();
  await m.page.evaluate(() => { const R = window.CuartoSemaforo.reiniciarIntentos; if (R) R(); });
  if (prepara) await prepara(m.page);
  const cortado = await descablear(m.page, sel);
  m.st.posts = 0;
  const t = await tocar(m.page, sel);
  const lat = await latidoDe(m.page, sel);
  await sleep(2200);
  const out = await leerOut(m.page, hostOut);
  const acts = medirActs ? await m.page.evaluate(() => window.__abanicoActs().map((a) => a.label)) : null;
  const txt = await m.page.evaluate((s) => { const b = document.querySelector(s); return b ? b.textContent.trim() : null; }, sel);
  await m.page.close();
  const cazado = [];
  if (!cortado) cazado.push("no encontré el botón para descablear");
  if (!t.tocado) cazado.push("el mouse no pudo tocarlo (el sabotaje cambió la geometría)");
  if (m.st.posts >= 1) cazado.push("la prueba REAL siguió saliendo (mido la red equivocada)");
  if (lat.probando) cazado.push("el latido apareció sin handler (mido CSS, no el cableado)");
  // el bloque de desenlace EXISTE desde antes (una pieza roja muestra su error plegado sin
  // que nadie toque nada — eso es §5). Lo que sólo un reintento REAL puede producir es la
  // frase «lo reintenté y sigue igual». Si eso aparece sin handler, la aserción es ciega.
  if (/reintent/i.test(out.sub || "")) cazado.push("el desenlace dijo «reintenté» sin handler (aserción ciega)");
  // [FIX-P3 · §2] el arco YA no muta su rótulo de prueba (la fusión: siempre [Probar de
  // nuevo]); lo que muta es el CAMINO. Sin handler el camino no puede aparecer.
  if (acts && acts.some((a) => /Arreglarlo|Configurar/.test(a))) cazado.push("el camino del arco mutó sin handler");
  if (!acts && /Ver el error|Configurar/.test(txt || "")) cazado.push("el botón mutó sin handler");
  ok(cazado.length === 0,
     `CALIBRACIÓN ${nombre}: descableado el botón, las aserciones de efecto CAEN`,
     cazado.length ? cazado.join(" | ") : `0 posts · 0 latido · 0 desenlace · sigue «${txt}»`);
  return cazado.length === 0;
}

await calibrar("abanico",
  async (p) => { await p.evaluate(async () => { window.__openAbanico(window.__cuarto.pieceData("t-roto")); await new Promise((r) => setTimeout(r, 450)); }); },
  SEL_AB, "#abMsg", true);

await calibrar("panel · fila",
  async (p) => { await p.evaluate(async () => { await window.__preflight(); await new Promise((r) => setTimeout(r, 400)); }); },
  "#preflightList .pf-fix", "#preflightList .pf-item .pf-out", false);

/* [FIX-P3 · §6 §7] la tercera entrada dejó de ser el chip de la lista (murió) y es el arco
 * abierto DESDE el registro. Se calibra igual: descableado el [Probar de nuevo] de ese arco,
 * las aserciones de efecto tienen que caer. */
await calibrar("registro → popup de la pieza",
  async (p) => { await p.evaluate(async () => {
    window.__limpiarLogs(); window.__legendOpen(true);
    await window.__probarPieza("t-roto", { motivo: "manual" });
    await new Promise((r) => setTimeout(r, 900));
    const b = document.querySelector("#logList .logrow.bad [data-ver]"); if (b) b.click();
    await new Promise((r) => setTimeout(r, 500));
    /* …y se BORRAN los rastros de la preparación: el reintento gastado y el desenlace que
     * ella produjo. Si no, la calibración mediría lo que dejó el `probarPieza` de arriba en
     * vez de lo que hizo (nada) el click saboteado — y siempre daría "ciega". */
    window.CuartoSemaforo.reiniciarIntentos();
    window.__olvidarDesenlace("t-roto");
    window.__closeAbanico(); window.__openAbanico(window.__cuarto.pieceData("t-roto"));
    await new Promise((r) => setTimeout(r, 450));
  }); },
  '#abActs .ab-act[data-act="probar"]', "#abMsg", true);

await browser.close();

console.log("\n" + "─".repeat(72));
if (errsFinal.length) console.log("errores de JS en la corrida:", errsFinal.slice(0, 4).join(" | "));
if (fails.length) { console.log(`✗ ${fails.length} FALLA(S):\n  - ` + fails.join("\n  - ")); process.exit(1); }
console.log("✓ TODO VERDE — el [Reintentar] actúa en las tres entradas, con latido, desenlace y mutación.");
