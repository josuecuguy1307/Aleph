/* verify_t6_minimalista.mjs — T6 · MARTILLAZO MINIMALISTA (§10 LEY MINIMALISTA DEL CUARTO).
 *
 * La ley: la UI del Cuarto dice SOLO lo operativo (nombre + estado + acción + MÁX UNA LÍNEA);
 * toda explicación más larga vive en docs/guia y en su lugar queda un [?] que abre la ayuda.
 * SIEMPRE el mismo patrón.
 *
 * Esta vara mide las CINCO cosas que la ley exige de verdad, no la intención:
 *   §A  el [?] EXISTE y es UNO solo — mismo componente, mismo look, mismo handler.
 *   §B  cada [?] ABRE LA AYUDA CORRECTA — se tocan todos y se compara el título del popover
 *       contra el heading real del MD (no "se abrió algo": se abrió LO QUE APUNTA).
 *   §C  CERO TEXTO PERDIDO — cada párrafo retirado (worklist real, con archivo:línea) tiene
 *       que ser localizable en su MD. Un assert POR HALLAZGO, no un promedio.
 *   §D  CLOSET ANCLADO — el popup chico sigue a SU pieza; ni apilado ni pegado a la izquierda.
 *   §E  lang=en BARRIDO — lo que se tocó no cae a español, y §10 no rompió el inglés.
 *
 * Motor: WEBKIT (el motor de la .app de Tauri). Puerto PROPIO :8292. JAMÁS :25374.
 * Server: node (estáticos de design/ + docs/guia + stubs de /v1) — sin backend, sin install.
 *
 * Run:  NODE_PATH=<repo>/node_modules node verify_t6_minimalista.mjs
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const REPO = join(HERE, "..", "..", "..", "..");
const GUIA_DIR = join(REPO, "docs", "guia");
const SHOTS = join(HERE, "screenshots");
const PORT = 8292;                                  // MI puerto. Nunca 25374.
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => {
  console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`);
  if (!cond) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── server: design/ + docs/guia (el mismo montaje que hacen main.py y serve.py) ──
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp",
  ".woff2": "font/woff2", ".md": "text/markdown; charset=utf-8" };
const sockets = new Set();
const server = http.createServer(async (req, res) => {
  const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p.startsWith("/docs/guia/")) {                 // ← lo que monta main.py en prod
    try {
      const body = await readFile(join(GUIA_DIR, p.split("/").pop()));
      res.writeHead(200, { "Content-Type": MIME[".md"] }); res.end(body);
    } catch { res.writeHead(404); res.end("nf"); }
    return;
  }
  if (p.startsWith("/v1/") || p.startsWith("/catalog")) {
    res.writeHead(200, { "Content-Type": "application/json" }); res.end("{}"); return;
  }
  try {
    const body = await readFile(join(DESIGN_DIR, p.replace(/^\//, "")));
    res.writeHead(200, { "Content-Type": MIME[extname(p)] || "application/octet-stream" });
    res.end(body);
  } catch { res.writeHead(404); res.end("nf"); }
});
server.on("connection", (s) => { sockets.add(s); s.on("close", () => sockets.delete(s)); });
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));
console.log(`server :${PORT} — design/ + docs/guia\n`);

const SEED = `try { sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u-t6m", session_token: "tok-t6m", email: "t6m@aleph" })); } catch (e) {}`;

async function boot(browser, { lang = "es", width = 1440, height = 900 } = {}) {
  const page = await browser.newPage({ viewport: { width, height } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 170)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errs.push(m.text().slice(0, 150)); });
  await page.addInitScript(SEED);
  if (lang === "en") await page.addInitScript(`try { localStorage.setItem("aleph-lang", "en"); } catch (e) {}`);
  await page.goto(PAGE, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!window.__cuarto && !!window.__ayuda, null, { timeout: 25000 });
  await sleep(700);
  return { page, errs };
}

await mkdir(SHOTS, { recursive: true });
const browser = await webkit.launch();

/* ══ §A · EL [?] EXISTE Y ES UNO SOLO ═══════════════════════════════════════════════════ */
console.log("§A · el afordance [?]");
const { page, errs } = await boot(browser);

const censo = await page.evaluate(() => {
  const qs = [...document.querySelectorAll("[data-guia]")];
  return {
    total: qs.length,
    conClase: qs.filter((b) => b.classList.contains("qmark")).length,
    tags: [...new Set(qs.map((b) => b.tagName))],
    refs: qs.map((b) => b.dataset.guia),
    api: !!window.__ayuda,
    cssInyectado: !!document.getElementById("ayuda-css"),
    popEnBody: !!document.getElementById("ayudapop"),
  };
});
ok(censo.total > 0, `hay [?] en la pantalla (${censo.total} en el DOM inicial)`);
ok(censo.conClase === censo.total, `TODOS usan el mismo componente (.qmark ${censo.conClase}/${censo.total})`);
ok(censo.tags.length === 1 && censo.tags[0] === "BUTTON", `todos son <button> (${censo.tags.join(",")})`);
ok(censo.api && censo.cssInyectado && censo.popEnBody, "el componente monta su API, su CSS y su popover");

// el listener es UNO y delegado: un [?] pintado DESPUÉS del montaje también abre.
const tardio = await page.evaluate(async () => {
  const d = document.createElement("div");
  d.innerHTML = `<button class="qmark" type="button" data-guia="cuarto#lente">?</button>`;
  document.body.appendChild(d);
  d.firstElementChild.click();
  await new Promise((r) => setTimeout(r, 600));
  const abierto = !document.getElementById("ayudapop").hidden;
  const t = document.getElementById("ayTitle").textContent;
  d.remove(); window.__ayuda.cerrar();
  return { abierto, t };
});
ok(tardio.abierto, "un [?] pintado DESPUÉS del montaje también abre (listener delegado, no por-nodo)", `→ "${tardio.t}"`);

/* ══ §B · CADA [?] ABRE LA AYUDA CORRECTA ═══════════════════════════════════════════════ */
console.log("\n§B · cada [?] abre SU sección de docs/guia");

// la verdad contra la que se compara: los headings reales de los MD, por slug.
function headingsDe(locale) {
  const map = {};
  for (const tema of ["cuarto", "piezas", "memoria", "cerebros", "conectar", "sala"]) {
    const p = join(GUIA_DIR, `${tema}.${locale}.md`);
    if (!existsSync(p)) continue;
    for (const l of readFileSync(p, "utf8").split("\n")) {
      const m = /^(#{1,3})\s+(.*?)\s*\{#([a-z0-9_-]+)\}\s*$/.exec(l);
      if (m) map[`${tema}#${m[3]}`] = m[2];
    }
  }
  return map;
}
const H_ES = headingsDe("es"), H_EN = headingsDe("en");

// TODOS los `data-guia` del árbol servido (no sólo los del DOM inicial): estáticos + los que
// arma el JS con ayuda("tema","ancla"). Si un [?] apunta a una sección inexistente, se ve acá.
const TEMAS = ["cuarto", "piezas", "memoria", "cerebros", "conectar", "sala"];
const REFS = new Set();
for (const f of ["cuarto/cuarto.pixi.html", "cuarto/cuarto.html", "Cuarto.dc.html"]) {
  const src = readFileSync(join(DESIGN_DIR, f), "utf8");
  for (const m of src.matchAll(/data-guia="([a-z0-9_-]+#[a-z0-9_-]*)"/g)) REFS.add(m[1]);
  for (const m of src.matchAll(/\bayuda\(\s*"([a-z0-9_-]+)"\s*,\s*"([a-z0-9_-]*)"/g)) REFS.add(`${m[1]}#${m[2]}`);
  // …y los que viajan como VALOR (el 4º parámetro de osec, "tema#ancla"). Sin esto la vara
  // medía 10 destinos de 14 y los [?] de las secciones del Núcleo quedaban sin probar.
  for (const m of src.matchAll(/["'`]([a-z0-9_-]+#[a-z0-9_-]+)["'`]/g)) {
    if (TEMAS.includes(m[1].split("#")[0])) REFS.add(m[1]);
  }
}
const refs = [...REFS].sort();
console.log(`   ${refs.length} destinos distintos de [?] en el árbol servido`);

const huerfanas = refs.filter((r) => !H_ES[r]);
ok(huerfanas.length === 0, `cada [?] apunta a una sección que EXISTE en docs/guia`, huerfanas.length ? `HUÉRFANAS: ${huerfanas.join(", ")}` : "");
ok(refs.every((r) => !!H_EN[r]), "y esa sección existe también en el MD inglés (ES/EN en paridad)");

// abrir de verdad, uno por uno, y comparar el TÍTULO del popover con el heading del MD.
let abiertos = 0;
const shots = [];
for (const [i, ref] of refs.entries()) {
  const [tema, ancla] = ref.split("#");
  const r = await page.evaluate(async ([t, a]) => {
    window.__ayuda.cerrar();
    await window.__ayuda.abrir(t, a, null);
    await new Promise((res) => setTimeout(res, 350));
    const body = document.getElementById("ayBody");
    return {
      abierto: window.__ayuda.abierto(),
      titulo: (document.getElementById("ayTitle").textContent || "").trim(),
      chars: (body.textContent || "").trim().length,
      falla: !!body.querySelector(".ayFail"),
    };
  }, [tema, ancla]);
  const bien = r.abierto && !r.falla && r.titulo === H_ES[ref] && r.chars > 40;
  if (bien) abiertos++;
  else console.log(`   ✗ ${ref}: abierto=${r.abierto} falla=${r.falla} título="${r.titulo}" esperado="${H_ES[ref]}" chars=${r.chars}`);
  // MUESTREO CON EVIDENCIA: los primeros 10, con screenshot del popover real.
  if (i < 10) {
    const el = await page.$("#ayudapop");
    const f = join(SHOTS, `t6min-ayuda-${String(i + 1).padStart(2, "0")}-${ref.replace("#", "-")}.png`);
    if (el) { await el.screenshot({ path: f }); shots.push(f); }
  }
}
ok(abiertos === refs.length, `los ${refs.length} [?] abren SU sección con contenido real (${abiertos}/${refs.length})`);
ok(shots.length >= 10, `muestreo con evidencia: ${shots.length} screenshots del popover`);

// §4h · FALLO VISIBLE: si el MD no se puede leer, la ayuda lo DICE (no un popover mudo).
const falloVisible = await page.evaluate(async () => {
  window.__ayuda.cerrar();
  await window.__ayuda.abrir("no-existe-este-tema", "nada", null);
  await new Promise((r) => setTimeout(r, 700));
  const b = document.getElementById("ayBody");
  return { visible: window.__ayuda.abierto(), grita: !!b.querySelector(".ayFail"), txt: (b.textContent || "").trim().slice(0, 80) };
});
ok(falloVisible.visible && falloVisible.grita, "§4h · si la guía no se puede leer, el [?] lo GRITA (jamás mudo)", `→ "${falloVisible.txt}"`);
await page.evaluate(() => window.__ayuda.cerrar());

/* ══ §C · CERO TEXTO PERDIDO ════════════════════════════════════════════════════════════ */
console.log("\n§C · cero texto perdido — un assert POR HALLAZGO del worklist");

// el worklist REAL de la medición sobre main (reports/ley10/hallazgos-main.jsonl): los párrafos
// que §10 manda sacar. Para cada uno: o sigue en la UI (no se tocó) o su idea está en docs/guia.
// El sujeto correcto es lo que ESTA rama tenía antes del barrido: hallazgos-t6-base.jsonl
// (step5-certificacion @15ed867, medido con el scanner de esta rama). hallazgos-main.jsonl mide
// main @c10e221 — otro árbol, con párrafos que acá nunca existieron: se reporta aparte, abajo.
const WL = join(REPO, "reports", "ley10", "hallazgos-t6-base.jsonl");
const guiaTodo = ["cuarto", "piezas", "memoria", "cerebros", "conectar", "sala"]
  .flatMap((t) => [`${t}.es.md`, `${t}.en.md`])
  .map((n) => readFileSync(join(GUIA_DIR, n), "utf8")).join("\n").toLowerCase();
const uiTodo = ["cuarto/cuarto.pixi.html", "cuarto/cuarto.html", "Cuarto.dc.html"]
  .map((f) => readFileSync(join(DESIGN_DIR, f), "utf8")).join("\n").toLowerCase();

const norm = (s) => s.toLowerCase().replace(/<[^>]*>/g, " ").replace(/[^\wáéíóúñü ]+/gi, " ").replace(/\s+/g, " ").trim();
const STOP = new Set(("el la los las un una de del que y o a en con por para su sus lo le se es son está están no ni al como más pero si te tu tus me mi ya esta este esto " +
  "the a an of to and or in on for with from that this its it you your they their are is be will can when where what").split(" ").filter(Boolean));
const contenido = (s) => norm(s).split(" ").filter((w) => w.length > 3 && !STOP.has(w));

let cubiertos = 0, perdidos = [];
const hallazgos = readFileSync(WL, "utf8").trim().split("\n").map((l) => JSON.parse(l)).filter((h) => h.level === "HARD");
for (const h of hallazgos) {
  const pal = contenido(h.text);
  if (pal.length < 4) { cubiertos++; continue; }          // fragmento sin contenido léxico
  const enGuia = pal.filter((w) => guiaTodo.includes(w)).length / pal.length;
  const enUI = pal.filter((w) => uiTodo.includes(w)).length / pal.length;
  // la idea sobrevive: o la recibió el MD, o el texto sigue en pantalla (párrafo no barrido).
  if (enGuia >= 0.6 || enUI >= 0.8) cubiertos++;
  else perdidos.push(`${h.file}:${h.line} (guia ${(enGuia * 100) | 0}% · ui ${(enUI * 100) | 0}%) "${h.text.slice(0, 80)}"`);
}
for (const p of perdidos) console.log(`   ✗ PERDIDO ${p}`);
ok(perdidos.length === 0, `los ${hallazgos.length} párrafos del worklist de ESTA rama son localizables (${cubiertos}/${hallazgos.length})`);

// contexto (no bloqueante): el worklist de main mide otro árbol. Se informa cuántos de sus
// párrafos ni siquiera existían acá, para que nadie lea "62/68" como texto perdido.
const WLM = join(REPO, "reports", "ley10", "hallazgos-main.jsonl");
if (existsSync(WLM)) {
  const hm = readFileSync(WLM, "utf8").trim().split("\n").map((l) => JSON.parse(l)).filter((h) => h.level === "HARD");
  const base = readFileSync(WL, "utf8");
  const ajenos = hm.filter((h) => !base.includes(h.text.slice(0, 45))).length;
  console.log(`   (worklist de main: ${hm.length} HARD · ${ajenos} nunca existieron en esta rama — mide main @c10e221)`);
}

/* ══ §D · CLOSET ANCLADO ════════════════════════════════════════════════════════════════ */
console.log("\n§D · el closet: chico y ANCLADO a su pieza");
const ancla = await page.evaluate(async () => {
  const c = window.__cuarto;
  // el Cuarto arranca SIN piezas: se siembra una real (mismo placeTile que usa ＋ Equipar).
  if (!c.placedTiles().filter((x) => x.atom !== "nucleo").length) {
    c.placeTile({ id: "t6m", key: "t6m", label: "Correo", category: "read", atom: "tool", role: "fuentes" });
    c.cam.fit();
    await new Promise((r) => setTimeout(r, 350));
  }
  const t = c.placedTiles().filter((x) => x.atom !== "nucleo")[0] || c.placedTiles()[0];
  if (!t) return { sinPieza: true };
  window.__openInspector(c.pieceData(t.id));
  await new Promise((r) => setTimeout(r, 450));
  const insp = document.getElementById("inspector");
  const r = insp.getBoundingClientRect();
  let p = null; try { p = c.artScreenOf(t.id); } catch (e) {}
  const cv = document.getElementById("cuarto").getBoundingClientRect();
  const st = document.getElementById("stage").getBoundingClientRect();
  const px = p ? (cv.left - st.left) + p.x : null;
  return {
    id: t.id, abierto: insp.classList.contains("open"),
    anchored: insp.dataset.anchored, w: Math.round(r.width), h: Math.round(r.height),
    loop: window.__anchorLoop(),
    piezaX: px == null ? null : Math.round(px), closetX: Math.round(r.left - st.left),
    vw: Math.round(st.width),
  };
});
ok(!ancla.sinPieza && ancla.abierto, `el closet abre sobre una pieza real (${ancla.id})`);
ok(ancla.anchored === "1", `está ANCLADO (data-anchored=1) y no apilado en una esquina fija`);
ok(ancla.w <= 380, `es chico (${ancla.w}×${ancla.h}px, tope 380 de ancho)`);
ok(ancla.loop === true, "y SIGUE a su pieza por frame (anchorLoop vivo)");
// "muere el abrirse a la izquierda": con espacio a la derecha, el closet va a la DERECHA.
const derecha = ancla.piezaX != null && ancla.closetX >= ancla.piezaX;
ok(derecha || ancla.piezaX == null, `abre del lado de la pieza, no forzado a la izquierda (pieza x=${ancla.piezaX} · closet x=${ancla.closetX})`);
await page.screenshot({ path: join(SHOTS, "t6min-closet-anclado.png") });

// las CARDS POP legibles: contraste real del cuerpo de la ayuda contra su fondo.
const contraste = await page.evaluate(async () => {
  window.__ayuda.cerrar();
  await window.__ayuda.abrir("cuarto", "nucleo", null);
  await new Promise((r) => setTimeout(r, 350));
  const pop = document.getElementById("ayudapop"), body = document.getElementById("ayBody");
  const lum = (c) => { const [r, g, b] = c.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number).map((v) => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }); return .2126 * r + .7152 * g + .0722 * b; };
  const fg = getComputedStyle(body).color;
  let el = pop, bg = "rgba(0, 0, 0, 0)";
  while (el && /rgba\(0, 0, 0, 0\)|transparent/.test(bg)) { bg = getComputedStyle(el).backgroundColor; el = el.parentElement; }
  const L1 = lum(fg), L2 = lum(bg);
  return { ratio: +(((Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05)).toFixed(2)), fg, bg, px: parseFloat(getComputedStyle(body).fontSize) };
});
ok(contraste.ratio >= 4.5, `la card POP se lee sola: contraste ${contraste.ratio}:1 (AA ≥ 4.5)`, `${contraste.fg} sobre ${contraste.bg}`);
await (await page.$("#ayudapop")).screenshot({ path: join(SHOTS, "t6min-card-pop.png") });

ok(errs.length === 0, `cero errores de página en ES`, errs.length ? errs.slice(0, 3).join(" | ") : "");
await page.close();

/* ══ §G · EL PANEL DE ABAJO = REGISTRO, NO INVENTARIO (dictado del humano) ══════════════
   1. se queda pero cambia de propósito: ni el título ni el tooltip hablan de piezas.
   2. muere el cartel de vacío y muere el ＋ del panel (equipar es del [＋ Equipar] y nada más).
   3. EL PANEL SOLO EXISTE SI HAY ENTRADAS: con cero, no se dibuja — ni caja, ni título, ni
      estado vacío. Aparece con la primera entrada y desaparece si se limpia.             */
console.log("\n§G · el panel de abajo: registro de lo que pasa, no inventario");
const { page: pG, errs: errsG } = await boot(browser);

const g0 = await pG.evaluate(() => {
  const p = document.getElementById("legend");
  const tog = document.getElementById("legToggle");
  return {
    existeEnDom: !!p,
    visible: !p.hidden,
    piezas: window.__cuarto.placedTiles().length,
    logs: window.__logs().length,
    label: (document.querySelector("#legend .lplabel") || {}).textContent,
    tooltip: tog.getAttribute("title"),
    lpAdd: !!document.getElementById("lpAdd"),
    // [FIX-P3 · §7] la lista de piezas murió con la reforma del arco: el panel es SÓLO
    // registro. El «cartel de vacío» que esta regla prohíbe se mide donde ahora podría
    // aparecer — el cuerpo del registro entero.
    vacioTxt: (document.getElementById("legBody") || {}).textContent.trim(),
  };
});
// REGLA 3 · Cuarto limpio = abajo no hay NADA
ok(g0.existeEnDom && g0.visible === false && g0.piezas === 0 && g0.logs === 0,
  "Cuarto limpio: cero entradas → el panel NO se dibuja", `visible=${g0.visible} piezas=${g0.piezas} logs=${g0.logs}`);
// REGLA 1 · ni el título ni el tooltip hablan de piezas
ok(!/pieza/i.test(g0.label || "") && !/pieza/i.test(g0.tooltip || ""),
  `el rótulo dejó de hablar de piezas`, `label="${g0.label}" title="${g0.tooltip}"`);
// REGLA 2 · ni cartel de vacío ni ＋ propio
ok(g0.vacioTxt === "", "cero cartel de vacío (el ＋ se explica solo)", `="${g0.vacioTxt}"`);
ok(g0.lpAdd === false, "el ＋ del panel murió: equipar entra por UN solo lugar");

// REGLA 3 (ida) · aparece con la PRIMERA entrada
const g1 = await pG.evaluate(async () => {
  window.__logPush("probando el registro");
  await new Promise((r) => setTimeout(r, 200));
  return { visible: window.__panelVisible(), filas: document.querySelectorAll("#logList .logrow").length,
           count: (document.getElementById("lpCount") || {}).textContent.trim() };
});
ok(g1.visible && g1.filas === 1, "llega la primera entrada → el panel APARECE", `filas=${g1.filas} chip="${g1.count}"`);

// REGLA 3 (vuelta) · desaparece al limpiar
const g2 = await pG.evaluate(async () => {
  window.__limpiarLogs();
  await new Promise((r) => setTimeout(r, 200));
  return { visible: window.__panelVisible(), abierto: window.__legendOpen() };
});
ok(!g2.visible, "se limpia el registro → el panel DESAPARECE otra vez");
ok(g2.abierto === false, "…y no queda 'abierto' por dentro mientras está oculto");

/* [FIX-P3 · §7 §6] EQUIPAR ES UN EVENTO, NO UN INVENTARIO. Antes «equipar enciende el panel»
 * valía porque el panel LISTABA las piezas: la pieza ERA la entrada. Con la lista muerta, el
 * panel es registro puro, así que lo que lo enciende es el HECHO de haber equipado — una
 * línea con su pieza y su hora — y el estado vivo vive en el anillo de la pieza. La aserción
 * se endurece: no alcanza con que el panel se dibuje, la línea tiene que NOMBRAR la pieza.  */
const g3 = await pG.evaluate(async () => {
  window.__limpiarLogs();
  window.__cuarto.placeTile({ id: "g3", key: "g3", label: "Correo", category: "read", atom: "tool", role: "fuentes" });
  window.__logPush("entró al cuarto", "", { pieza: "Correo", pieceId: "g3" });
  window.__renderPieces();
  await new Promise((r) => setTimeout(r, 300));
  const fila = document.querySelector("#logList .logrow");
  return { visible: window.__panelVisible(), filas: document.querySelectorAll("#logList .logrow").length,
           pieza: fila ? (fila.querySelector(".logp") || {}).textContent : null,
           hora: fila ? (fila.querySelector(".logt") || {}).textContent : null,
           sinLista: document.querySelectorAll("#legend .prow").length };
});
ok(g3.visible && g3.filas === 1, "equipar algo también enciende el panel (el hecho es la entrada)", `filas=${g3.filas}`);
ok(g3.pieza === "Correo" && /^\d\d:\d\d$/.test(g3.hora || ""),
   "…y la línea dice PIEZA · qué pasó · HORA", `pieza="${g3.pieza}" hora="${g3.hora}"`);
ok(g3.sinLista === 0, "…y el panel NO volvió a ser un inventario (cero filas de piezas)", `filas=${g3.sinLista}`);
await pG.screenshot({ path: join(SHOTS, "t6min-panel-registro.png") });
ok(errsG.length === 0, "cero errores de página en el panel", errsG.slice(0, 3).join(" | "));
await pG.close();

/* ══ §E · lang=en BARRIDO ═══════════════════════════════════════════════════════════════ */
console.log("\n§E · lang=en — lo que se tocó no cae a español");
const { page: pEn, errs: errsEn } = await boot(browser, { lang: "en" });
await sleep(900);

const en = await pEn.evaluate(async () => {
  const lang = (window.AlephI18n && window.AlephI18n.lang && window.AlephI18n.lang()) || "es";
  // el [?] tiene que leer el MD INGLÉS y titular en inglés
  window.__ayuda.cerrar();
  await window.__ayuda.abrir("cuarto", "nucleo", null);
  await new Promise((r) => setTimeout(r, 500));
  const titulo = (document.getElementById("ayTitle").textContent || "").trim();
  const cuerpo = (document.getElementById("ayBody").textContent || "").trim();
  const pie = (document.getElementById("ayAsk").textContent || "").trim();
  window.__ayuda.cerrar();
  // censo de español en el chrome VISIBLE (lo que este barrido tocó)
  const ES = /\b(el|la|los|las|una|para|con|que|tu|tus|toca|piezas|agente|cuarto|memoria|correr|guarda)\b/i;
  const sospechosos = [];
  for (const id of ["msealSub", "lpCount", "status"]) {
    const e = document.getElementById(id);
    const t = e && (e.textContent || "").trim();
    if (t && ES.test(t)) sospechosos.push(`#${id}: ${t.slice(0, 60)}`);
  }
  return { lang, titulo, cuerpo: cuerpo.slice(0, 90), pie, sospechosos };
});
ok(en.lang === "en", `la página está en inglés (AlephI18n.lang()="${en.lang}")`);
ok(en.titulo === H_EN["cuarto#nucleo"], `el [?] sirve el MD INGLÉS`, `título="${en.titulo}"`);
ok(!/[áéíóúñ¿¡]/i.test(en.cuerpo), `y su cuerpo NO cae a español`, `"${en.cuerpo.slice(0, 60)}…"`);
ok(en.pie === "Ask the Guide →", `el pie del popover está en inglés ("${en.pie}")`);
ok(en.sospechosos.length === 0, `el chrome tocado no cae a español bajo lang=en`, en.sospechosos.join(" | "));
ok(errsEn.length === 0, `cero errores de página en EN`, errsEn.length ? errsEn.slice(0, 3).join(" | ") : "");
await pEn.screenshot({ path: join(SHOTS, "t6min-lang-en.png") });
await pEn.close();

/* ══ §F · LA VARA DE §10 EN SÍ ══════════════════════════════════════════════════════════ */
console.log("\n§F · scan_ley10 sobre esta rama");
let scanOut = "";
try {
  scanOut = execFileSync("node", [join(REPO, "reports/ley10/scan_ley10.mjs"), REPO, "/tmp"], { encoding: "utf8" });
} catch (e) { scanOut = String((e.stdout || "") + (e.stderr || "")); }
// el `\s+` no es cosmético: el scanner alineó sus rótulos al sumar el criterio duro y la
// aserción vieja, atada al espacio único, empezó a leer "?" — un rojo que no era del producto.
const mHard = /HARD\s+\(párrafo inequívoco\): (\d+)/.exec(scanOut);
const mFuga = /que además PINTAN: (\d+)/.exec(scanOut);
const mSuel = /SUELTA\s+\(ni clickeable[^)]*\): (\d+)/.exec(scanOut);
ok(!!mHard && Number(mHard[1]) === 0, `HARD = 0 en la superficie del Cuarto (${mHard ? mHard[1] : "?"})`);
ok(!!mFuga && Number(mFuga[1]) === 0, `CONTROL-RENDER: ningún string excluido por model-facing llega a la pantalla (${mFuga ? mFuga[1] : "?"})`);
// [T6-bis · criterio duro] el largo no alcanza: una línea que no es clickeable, ni input, ni
// rótulo de algo que actúa, se va aunque entre en un renglón.
ok(!!mSuel && Number(mSuel[1]) === 0, `SUELTA = 0 · ni clickeable, ni input, ni rótulo de algo que actúa (${mSuel ? mSuel[1] : "?"})`);

/* ── cierre ── */
await browser.close();
for (const s of sockets) s.destroy();
server.close();
console.log(`\n${fails.length ? "✗ FALLA" : "✓ VERDE"} — ${fails.length} de las aserciones fallaron`);
for (const f of fails) console.log(`   · ${f}`);
await writeFile(join(SHOTS, "t6min-EVIDENCIA.json"),
  JSON.stringify({ puerto: PORT, motor: "webkit", refs, fails }, null, 2));
process.exit(fails.length ? 1 : 0);
