/* verify_t6_hammer.mjs — T6 · EXPERIENCE HAMMER (CUARTO-HONESTO.md §8+§9).
 * UNA disciplina, verificada parejo: presupuesto de texto · nivel-1 anidado · closet anclado ·
 * capas sin pisarse · barrido sin dead-ends · loops de solución (timeout SSE tipado, error del
 * Guía con [Reintentar], paredes de Conectar con botón).
 *
 * Motores: chromium + webkit · viewports wide(1440×900)/narrow(900×700) para layout.
 * El server de estáticos es NODE (no python) porque una parte necesita un SSE que CUELGA
 * de verdad (route.fulfill no puede colgar el body) — así se prueba el corte por inactividad.
 *
 * Run: node verify_t6_hammer.mjs
 */
import { chromium, webkit } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
// La integración comparte máquina con otras tandas (P11 ocupa :8281): permitir puerto
// propio sin cambiar el default histórico de la vara.
const PORT = Number(process.env.T6_PORT || 8281);
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const CONECTAR = `http://localhost:${PORT}/Conectar.dc.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── server node: estáticos + /v1/catalog/equip = SSE que CUELGA (1 frame y silencio) ──
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp", ".md": "text/markdown" };
const sockets = new Set();
const server = http.createServer(async (req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (path === "/v1/catalog/equip") {           // el HANG real: headers + 1 evento + silencio eterno
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    res.write('data: {"type":"resolver.buscando"}\n\n');
    return;                                      // jamás res.end() — el corte lo pone el cliente
  }
  if (path.startsWith("/v1/")) { res.writeHead(200, { "Content-Type": "application/json" }); res.end("{}"); return; }
  try {
    const body = await readFile(join(DESIGN_DIR, path.replace(/^\//, "")));
    res.writeHead(200, { "Content-Type": MIME[extname(path)] || "application/octet-stream" });
    res.end(body);
  } catch { res.writeHead(404); res.end("nf"); }
});
server.on("connection", (s) => { sockets.add(s); s.on("close", () => sockets.delete(s)); });
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

const SEED_SESSION = `try { sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u-t6", session_token: "tok-t6", email: "t6@aleph" })); } catch (e) {}`;

async function bootPage(browser, { width, height }) {
  const page = await browser.newPage({ viewport: { width, height } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 160)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errs.push(m.text().slice(0, 140)); });
  await page.addInitScript(SEED_SESSION);
  // stub de /v1 EXCEPTO catalog/equip (ese cae al server node que cuelga de verdad)
  await page.route("**/v1/**", (route) => {
    const u = route.request().url();
    if (u.includes("/v1/catalog/equip")) return route.fallback();
    if (u.includes("/v1/cuarto/guide")) return route.fallback();   // lo maneja cada sección
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__openInspector && window.__guide && window.__osecOpen, null, { timeout: 15000 });
  return { page, errs };
}

const box = (r) => ({ left: r.left, right: r.right, top: r.top, bottom: r.bottom });
const overlap = (a, b) => a && b && a.right > b.left && b.right > a.left && a.bottom > b.top && b.bottom > a.top;

async function runLayout(engine, nm, vp) {
  const browser = await engine.launch();
  const { page, errs } = await bootPage(browser, vp);
  const V = `${nm} ${vp.width}x${vp.height}`;

  // ── §8.2 · PRESUPUESTO ────────────────────────────────────────────────────────
  const bud = await page.evaluate(() => {
    const words = (s) => (s || "").trim().split(/\s+/).filter(Boolean);
    const pills = [...document.querySelectorAll("#topright .tbgroup > .pill")].map((p) => ({ id: p.id, w: words(p.textContent).length }));
    window.__openInspector(window.__cuarto.nucleoData());
    const lvl1 = (document.querySelector("#inspector .isummary").textContent || "").trim().length +
                 (document.querySelector("#inspector .ihead").textContent || "").trim().length;
    const vis = [...document.querySelectorAll("#inspector button, #inspector select, #inspector input")]
      .filter((el) => el.offsetParent !== null).length;
    return { pills, lvl1, vis };
  });
  ok(bud.pills.every((p) => p.w <= 3), `${V} · §8.2 pills de barra ≤2 palabras (+glifo)`, JSON.stringify(bud.pills.filter((p) => p.w > 3)));
  ok(bud.lvl1 <= 340, `${V} · §8.2 inspector nivel-1 ≤340 chars visibles`, `chars=${bud.lvl1}`);
  ok(bud.vis <= 6, `${V} · §8.3 nivel-1 = ≤6 elementos interactivos visibles`, `vis=${bud.vis}`);

  // ── §8.3 · NIVEL-1 · secciones del Núcleo colapsadas + presupuesto expandido ──
  const nuc = await page.evaluate(() => {
    window.__setInspectorExpanded(true);
    const secs = [...document.querySelectorAll("#d-opts .osec")];
    const bodiesHidden = [...document.querySelectorAll("#d-opts .osec-b")].every((b) => getComputedStyle(b).display === "none");
    const headChars = secs.reduce((n, s) => n + (s.querySelector(".osec-h").textContent || "").trim().length, 0);
    window.__setInspectorExpanded(false);
    return { n: secs.length, closed: secs.filter((s) => s.classList.contains("closed")).length, bodiesHidden, headChars };
  });
  ok(nuc.n >= 7 && nuc.closed === nuc.n && nuc.bodiesHidden, `${V} · §8.3 Núcleo abre con TODAS las secciones plegadas`, JSON.stringify(nuc));
  ok(nuc.headChars <= 620, `${V} · §8.2 panel plegado = solo encabezados (presupuesto)`, `chars=${nuc.headChars}`);

  // ── §8.3 · CLOSET ANCLADO a la pieza ──────────────────────────────────────────
  const anchor = await page.evaluate(async () => {
    window.__cuarto.placeTile({ id: "t6-anchor", atom: "tool", category: "process", label: "Ancla", tools: ["t"] }, 2, 2);
    await new Promise((r) => setTimeout(r, 250));
    window.__openInspector(window.__cuarto.pieceData("t6-anchor"));
    await new Promise((r) => setTimeout(r, 120));
    const insp = document.getElementById("inspector").getBoundingClientRect();
    const p = window.__cuarto.artScreenOf("t6-anchor"), cv = document.getElementById("cuarto").getBoundingClientRect();
    const cx = insp.left + insp.width / 2, cy = insp.top + insp.height / 2;
    const d = Math.round(Math.hypot(cx - (cv.left + p.x), cy - (cv.top + p.y)));
    const R = (id) => { const el = document.getElementById(id); const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, hidden: el.hidden || getComputedStyle(el).display === "none" }; };
    return { anchored: document.getElementById("inspector").dataset.anchored, d, w: Math.round(insp.width),
      insp: { left: insp.left, right: insp.right, top: insp.top, bottom: insp.bottom }, bar: R("topright"), run: R("listo") };
  });
  const noPisa = (a, b) => b.hidden || !overlap(a, b);
  ok(anchor.anchored === "1" && anchor.d < 420, `${V} · §8.3 closet ANCLADO a la esquina de la pieza`, `dist=${anchor.d}`);
  ok(anchor.w <= 320, `${V} · §8.3 closet chico (≤320px) — el panelón murió`, `w=${anchor.w}`);
  // [Cuarto entrega, no corre] la runbar se fue del lienzo; el vecino a respetar es el badge.
  ok(noPisa(anchor.insp, anchor.bar) && noPisa(anchor.insp, anchor.run), `${V} · §8.3 el closet no pisa barra ni badge`);

  // ── §8.3 · CAPAS: dock del cerebro · copiloto · respuesta vs cámara · teamtasks ──
  const capas = await page.evaluate(async () => {
    const R = (id) => { const el = document.getElementById(id); if (!el) return null; const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }; };
    const dockInMenu = !!document.querySelector("#metaMenu #cuartoBrainDock");
    const floatGone = !document.getElementById("aleph-floating-brain");
    document.getElementById("copBtn").click();                      // abre el copiloto (con auto-acomodo)
    await new Promise((r) => setTimeout(r, 160));
    const cop = R("copilot"), legend = R("legend"), runbar = R("listo"), cam = R("cam");
    const ap = document.getElementById("answerpanel"); ap.hidden = false;
    document.getElementById("stage").classList.add("answer-open");
    await new Promise((r) => setTimeout(r, 60));
    const camShift = R("cam"), apr = R("answerpanel");
    ap.hidden = true; document.getElementById("stage").classList.remove("answer-open");
    const tt = document.getElementById("teamtasks"); tt.hidden = false;
    await new Promise((r) => setTimeout(r, 40));
    const ttr = R("teamtasks"); tt.hidden = true;
    return { dockInMenu, floatGone, cop, legend, runbar, cam, camShift, apr, ttr, ih: innerHeight };
  });
  ok(capas.floatGone && capas.dockInMenu, `${V} · §8.3 chip del cerebro DOCKEADO en menú meta (float muerto)`);
  ok(!overlap(capas.cop, capas.legend) && !overlap(capas.cop, capas.runbar) && !overlap(capas.cop, capas.cam),
    `${V} · §8.3 el chat del Guía abre SIN tapar leyenda/badge/cámara`);
  ok(!overlap(capas.camShift, capas.apr), `${V} · §8.3 respuesta abierta → la cámara se corre (no queda tapada)`);
  ok(capas.ttr.bottom <= capas.ih - 116, `${V} · §8.3 teamtasks libre de la zona del launcher`, `bottom=${Math.round(capas.ttr.bottom)} ih=${capas.ih}`);

  ok(errs.length === 0, `${V} · 0 errores JS`, errs.slice(0, 2).join(" | "));
  await browser.close();
}

async function runSweepAndLoops(engine, nm) {
  const browser = await engine.launch();
  const { page, errs } = await bootPage(browser, { width: 1440, height: 900 });

  // ── §8.4 · BARRIDO: cada elemento interactivo tiene DESENLACE ─────────────────
  const sweep = await page.evaluate(async () => {
    const out = [];
    const test = (name, fn) => { try { out.push({ name, ok: !!fn() }); } catch (e) { out.push({ name, ok: false, err: String(e).slice(0, 60) }); } };
    const $id = (i) => document.getElementById(i);

    test("metaBtn abre menú", () => { $id("metaBtn").click(); const o = !$id("metaMenu").hidden; return o; });
    test("metaBtn cierra menú", () => { $id("metaBtn").click(); return $id("metaMenu").hidden; });
    // [identidad visual 6/6] "manualBtn conmuta estado" se fue con el toggle. El desenlace que
    // importaba (revisar tools antes de equipar) ya no depende de un modo: se mide en la sonda de
    // identidad visual (§d) sobre el panel real, con todas las casillas marcadas.
    test("sin toggle de modo en el ⋯", () => !$id("manualBtn") && !$id("manualState"));
    test("cuartoThemeBtn cambia tema", () => { const t0 = document.documentElement.getAttribute("data-theme"); $id("cuartoThemeBtn").click(); const t1 = document.documentElement.getAttribute("data-theme"); if (t1 !== t0) { $id("cuartoThemeBtn").click(); return true; } return false; });
    test("copBtn abre chat", () => { if ($id("copilot").dataset.open !== "1") $id("copBtn").click(); return $id("copilot").dataset.open === "1"; });
    test("copMin cierra chat", () => { $id("copMin").click(); return $id("copilot").dataset.open === "0"; });
    test("lensBtn ON", () => { $id("lensBtn").click(); return $id("lensState").textContent === "ON"; });
    test("lensBtn OFF", () => { $id("lensBtn").click(); return $id("lensState").textContent === "OFF"; });
    // [ola C · item 6] la leyenda de formas SALIÓ del diorama: es glosario, no operación. Ahora vive
    // detrás del "?" del ⋯ (mismo desenlace verificable, otra puerta).
    test("glosarioBtn abre el glosario", () => { $id("glosarioBtn").click(); const o = !$id("glosario").hidden; $id("glosarioBtn").click(); return o; });
    test("equipBtn abre paleta", () => { if (!$id("palette").classList.contains("open")) $id("equipBtn").click(); return $id("palette").classList.contains("open"); });
    test("closet del palette abre al toque", () => {
      const head = document.querySelector('#paletteList .lbl[data-grp]'); if (!head) return false;
      const grp = head.closest(".grp"), was = grp.classList.contains("collapsed");
      head.click();
      const now = document.querySelector(`#paletteList .lbl[data-grp="${head.dataset.grp}"]`).closest(".grp").classList.contains("collapsed");
      return was !== now;
    });
    test("mineBtn abre Mis agentes", () => { $id("mineBtn").click(); return $id("mineOverlay").classList.contains("open"); });
    test("mineClose cierra", () => { $id("mineClose").click(); return !$id("mineOverlay").classList.contains("open"); });
    // [ola C · item 7] el modal murió: ＋ Tu MCP NAVEGA a la pantalla propia de Inspección. No se
    // dispara el click acá — navegar destruiría el contexto y se llevaría el barrido entero por
    // delante; el desenlace se comprueba en su handler (y la navegación real, en
    // qa/verify_cuarto_limpio.mjs, que carga la pantalla y la ejerce).
    test("byoBtn navega a Inspección", () => typeof $id("byoBtn").onclick === "function");
    // [ola C · item 7] el selector de transporte y el cierre del modal DEJARON de ser controles del
    // Cuarto: viven en inspeccion/inspeccion.html. Su desenlace se verifica allá
    // (qa/verify_cuarto_limpio.mjs · "la pantalla tiene los 3 transportes" y el handoff por query).
    // Acá el barrido cubre lo que el Cuarto SÍ tiene: la puerta que lleva a esa pantalla (arriba).
    test("creset encuadra (estado)", () => { $id("creset").click(); return typeof window.__cuarto.cam.state.scale === "number"; });
    test("zout aleja (cam.state.scale)", () => { const z0 = window.__cuarto.cam.state.scale; $id("zout").click(); return window.__cuarto.cam.state.scale < z0; });
    test("zin acerca", () => { const z0 = window.__cuarto.cam.state.scale; $id("zin").click(); return window.__cuarto.cam.state.scale > z0; });
    test("rotl rota", () => { const r0 = window.__cuarto.cam.state.rot; $id("rotl").click(); return window.__cuarto.cam.state.rot !== r0; });
    test("rotr rota de vuelta", () => { const r0 = window.__cuarto.cam.state.rot; $id("rotr").click(); return window.__cuarto.cam.state.rot !== r0; });
    test("answerclose cierra respuesta", () => { const ap = $id("answerpanel"); ap.hidden = false; $id("answerclose").click(); return ap.hidden; });

    // inspector: primaria abre la PRIMERA sección · osec conmuta en el lugar
    window.__openInspector(window.__cuarto.nucleoData());
    test("iexpand expande", () => { $id("iexpand").click(); return $id("inspector").classList.contains("expanded"); });
    test("tab Opciones conmuta", () => { document.querySelector('#inspector .tab[data-d="opts"]').click(); return $id("d-opts").classList.contains("on"); });
    test("osec abre al toque", () => { const s = document.querySelector("#d-opts .osec.closed"); if (!s) return false; s.querySelector(".osec-h").click(); return !s.classList.contains("closed"); });
    test("osec cierra al toque", () => { const s = document.querySelector("#d-opts .osec:not(.closed)"); if (!s) return false; s.querySelector(".osec-h").click(); return s.classList.contains("closed"); });
    test("iprimary abre la 1ª sección", () => {
      [...document.querySelectorAll("#d-opts .osec")].forEach((x) => x.classList.add("closed"));
      window.__osecOpen.clear();
      $id("iprimary").click();
      const first = document.querySelector("#d-opts .osec");
      return !first.classList.contains("closed");
    });
    test("modelcard elegible selecciona", () => {
      const c = document.querySelector('#d-opts .modelcard:not(.lock)'); if (!c) return false; c.click();
      return document.querySelector('#d-opts .modelcard.on') !== null;
    });
    test("iclose cierra el closet", () => { $id("iclose").click(); return !$id("inspector").classList.contains("open"); });
    test("guideModeSel persiste", () => { $id("copBtn").click(); const s = $id("guideModeSel"); s.value = "explicar"; s.dispatchEvent(new Event("change")); const okv = localStorage.getItem("aleph.cuarto.guideMode") === "explicar"; s.value = "delegar"; s.dispatchEvent(new Event("change")); $id("copMin").click(); return okv; });
    return out;
  });
  const dead = sweep.filter((s) => !s.ok);
  ok(dead.length === 0, `${nm} · §8.4 barrido sin dead-ends (${sweep.length} controles con desenlace)`, JSON.stringify(dead).slice(0, 220));

  // ── §8.1 · TIMEOUT SSE tipado (el 'curando…' congelado muere) ─────────────────
  const t0 = Date.now();
  const timeoutRes = await page.evaluate(async () => {
    globalThis.__catalogEquipInactivityMs = 700;
    const m = await import("./catalog_equip.js");
    const states = [];
    const res = await m.curateAndEquipRegistry({ service: "T6Hang", onState: (h) => states.push(h) });
    return { cause: res.cause, retry: res.retry, lastState: states[states.length - 1] || "" };
  });
  ok(timeoutRes.cause === "timeout" && timeoutRes.retry === true, `${nm} · §8.1 SSE colgado → corte TIPADO {cause:timeout, retry}`, JSON.stringify(timeoutRes).slice(0, 140));
  ok(/tard/i.test(timeoutRes.lastState) && Date.now() - t0 < 8000, `${nm} · §8.1 el corte narra la causa y llega en segundos`, `${Date.now() - t0}ms`);

  // ── §9 · ERROR DEL GUÍA: auto-retry + causa + [Reintentar] ────────────────────
  let guideHits = 0, guideOk = false;
  await page.route("**/v1/cuarto/guide", (route) => {
    guideHits++;
    if (guideOk) route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ content: "listo t6", tool_calls: [] }) });
    else route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "explota t6" }) });
  });
  await page.evaluate(() => { document.getElementById("copBtn").click(); window.__guiaChat.send("hola t6"); });
  await page.waitForFunction(() => window.__guiaQ(".errcard .acts button"), null, { timeout: 10000 });
  const err1 = await page.evaluate(() => { const errsEl = window.__guiaQA(".errcard");
    return { txt: (errsEl[errsEl.length - 1] || {}).textContent.slice(0, 140) }; });
  ok(guideHits === 2, `${nm} · §9 auto-retry UNA vez antes de rendirse (hits=2)`, `hits=${guideHits}`);
  ok(/no pude guiar|couldn't guide/i.test(err1.txt) && /explota t6|HTTP 500/.test(err1.txt), `${nm} · §9 el error trae la CAUSA humana`, err1.txt);
  guideOk = true;
  await page.evaluate(() => { const bs = window.__guiaQA(".errcard .acts button"); bs[0].click(); });
  await page.waitForFunction(() => window.__guiaQA(".ac-md, .cop-msg.g").some((m) => /listo t6/.test(m.textContent)), null, { timeout: 8000 });
  ok(true, `${nm} · §9 [Reintentar] re-manda el turno y esta vez guía`);
  const strip = await page.evaluate(() => ({
    a: window.__stripRawCalls("<function=equipar>{\"s\":1}</function>listo"),
    b: window.__stripRawCalls("hola <function=ver_cuarto>"),
    c: window.__stripRawCalls("normal"),
  }));
  ok(strip.a === "listo" && strip.b === "hola" && strip.c === "normal", `${nm} · §9 <function=…> crudo JAMÁS se pinta como chat`, JSON.stringify(strip));

  ok(errs.length === 0, `${nm} · 0 errores JS en sweep/loops`, errs.slice(0, 2).join(" | "));
  await browser.close();
}

async function runConectar(engine, nm) {
  const browser = await engine.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
  await page.addInitScript(SEED_SESSION);
  // 1) catálogo caído → la pared tiene botón [↻ Reintentar]
  let catFail = true;
  await page.route("**/v1/**", (route) => {
    const u = route.request().url();
    if (u.includes("/v1/catalog/search")) {
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ items: [{ source: "registry", server_name: "t6-srv", name: "T6Srv", description: "x", badge: { kind: "community", label: "community" } }] }) });
    }
    if (u.includes("/v1/catalog/equip")) {
      return route.fulfill({ status: 200, contentType: "text/event-stream",
        body: 'data: {"type":"resolver.registry_down"}\n\ndata: {"type":"cerrado","ok":false,"cause":"registry_unreachable","retry":true}\n\n' });
    }
    if (catFail && (u.includes("/v1/belts/cards") || u.includes("/v1/atoms") || u.includes("/v1/catalog/cards"))) return route.abort();
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.goto(CONECTAR, { waitUntil: "load" });
  await page.waitForSelector("#gridRetry", { timeout: 12000 }).catch(() => {});
  const wall = await page.evaluate(() => ({ retry: !!document.getElementById("gridRetry"), txt: (document.querySelector("#grid .sub") || {}).textContent || "" }));
  ok(wall.retry && /no responde/i.test(wall.txt), `${nm} · §8.1 Conectar: catálogo caído = causa + [↻ Reintentar] (no pared)`, wall.txt.slice(0, 80));

  // 2) registro → curar → registry_unreachable = botón de reintento EN la card
  catFail = false;
  await page.evaluate(() => { const s = document.getElementById("catalogSearch"); s.value = "t6"; s.dispatchEvent(new Event("input")); });
  await page.waitForSelector('#regGrid button[data-eq]', { timeout: 9000 });
  await page.click('#regGrid button[data-eq]');
  await page.waitForFunction(() => { const c = document.querySelector("#regGrid .cur"); return c && /Reintentar/.test(c.textContent); }, null, { timeout: 9000 });
  const card = await page.evaluate(() => (document.querySelector("#regGrid .cur") || {}).textContent || "");
  ok(/no responde/.test(card) && /Reintentar/.test(card), `${nm} · §8.1 curación caída = causa + botón EN la card`, card.slice(0, 90));
  await browser.close();
}

try {
  await runLayout(chromium, "chromium", { width: 1440, height: 900 });
  await runLayout(chromium, "chromium", { width: 900, height: 700 });
  await runLayout(webkit, "webkit", { width: 1440, height: 900 });
  await runLayout(webkit, "webkit", { width: 900, height: 700 });
  await runSweepAndLoops(chromium, "chromium");
  await runSweepAndLoops(webkit, "webkit");
  await runConectar(chromium, "chromium");
  await runConectar(webkit, "webkit");
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  server.close();
  for (const s of sockets) { try { s.destroy(); } catch {} }
}

console.log("");
if (fails.length === 0) {
  console.log("RESULTADO: VERDE — T6 martillo: presupuesto · nivel-1 · closet anclado · capas · barrido sin dead-ends · loops (timeout SSE, Guía, Conectar) — chromium+webkit × wide/narrow");
  process.exit(0);
}
console.log(`RESULTADO: ROJO (${fails.length})`);
fails.forEach((f) => console.log(" - " + f));
process.exit(1);
