/* verify_step4_bridge.mjs — STEP 4 · 4A#5 · PUENTE DE CONTINUIDAD Cuarto→Sala.
 *
 * Página REAL (cuarto.html + sala.html) + bridge.js REAL, mismo origen (localhost) → el token de
 * sessionStorage cruza el page-nav como en producción. Backend stubeado por page.route.
 *
 * Verifica los requisitos de persona usuaria:
 *  A · CONTINUIDAD  — el frame de SALIDA del Cuarto (átomo mascota + nombre, held) ≡ el frame de
 *      ENTRADA de la Sala (mismo átomo SVG + mismo nombre). El overlay tapa la Sala mientras carga.
 *  A · REVELA-SÓLO-LISTA — mientras el belt no resuelve, el overlay AGUANTA; cuando la Sala está de
 *      verdad lista (belt pintado) → revela (overlay se remueve) y queda #stackPanel.on con piezas.
 *  B · FALLO HONESTO — puppet no encontrado → overlay QUEDA con nota honesta + retorno al Cuarto,
 *      NUNCA revela una Sala inline disfrazada de lista.
 *  C · SIN TOKEN — carga directa de la Sala (sin venir del Cuarto) → sin overlay, Sala normal.
 *  + estático: cuarto.html llama AlephBridge.raise · sala.html carga bridge.js y llama receive.
 *
 *   node product/app/design/sala/verify_step4_bridge.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;
const SALA = new URL(".", import.meta.url).pathname;
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const PID = "bridge-puppet-1";
const NAME = "Agente demo del puente";
const BREF = "platform/assembler/fixtures/belt-inline-rich.mcp.json";
const CARDS = [
  { id: "calc", label: "Calculadora", tools: ["add", "mul"], state: "ready", backed_by: "calc", connector: "calc" },
  { id: "pysandbox", label: "Python (cómputo)", tools: ["run_python"], state: "ready", backed_by: "pysandbox", connector: "pysandbox" },
];

function serve() {
  const srv = http.createServer((req, r) => {
    const p = path.join(DESIGN, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
    fs.createReadStream(p).pipe(r);
  });
  return new Promise((res) => srv.listen(0, "127.0.0.1", () => res(srv)));
}

const srv = await serve();
const base = "http://127.0.0.1:" + srv.address().port;
const browser = await chromium.launch();
fs.mkdirSync(SHOTS, { recursive: true });
const results = [];

function scen(name) {
  const fails = [];
  return { fails, check(n, ok, d) { if (!ok) fails.push(n); console.log((ok ? "  ✓ " : "  ✗ ") + n + (ok || !d ? "" : "  → " + d)); } };
}
async function newCtx(seedToken) {
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 820 }, reducedMotion: "no-preference" });
  await ctx.addInitScript((tok) => {
    try {
      if (window.top !== window) return;
      sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", session_token: "t1" }));
      localStorage.setItem("aleph-lang", "es");
      if (tok) sessionStorage.setItem("aleph_bridge", JSON.stringify({ name: tok, t: Date.now() }));
    } catch (e) {}
  }, seedToken || null);
  return ctx;
}
// rutas del backend de la Sala; belts/cards con delay opcional para observar el HELD antes de revelar
async function salaRoutes(page, { puppetFound = true, beltDelayMs = 0 } = {}) {
  const j = (r, json) => r.fulfill({ json });
  // Playwright: la ruta registrada MÁS TARDE gana. Registramos de MENOS a MÁS específica para que
  // la específica /puppets gane sobre el catch-all (si no, el catch-all "no encuentra" el puppet).
  await page.route("**/v1/**", (r) => j(r, {}));                                   // benigno (silencia 404 → sin json() uncaught)
  await page.route("**/v1/users/**", (r) => j(r, { puppets: [], keys: [], docs: [] }));
  await page.route("**/v1/sessions/**", (r) => r.request().method() === "GET" ? j(r, { artifacts: [] }) : j(r, { artifact: { id: "a1" } }));
  await page.route("**/v1/belts/cards*", async (r) => { if (beltDelayMs) await new Promise((x) => setTimeout(x, beltDelayMs)); return j(r, { ref: BREF, cards: CARDS, total: CARDS.length }); });
  await page.route("**/v1/users/*/puppets", (r) => j(r, puppetFound            // específica → gana (registrada última)
    ? { puppets: [{ id: PID, name: NAME, config: { meta: { output_type: "informe" }, belt: { belt_ref: BREF } } }] }
    : { puppets: [] }));
}
const grabFrame = (page) => page.evaluate(() => {
  const o = document.getElementById("ab-overlay");
  if (!o) return { present: false };
  const svg = o.querySelector(".ab-glyph");
  return { present: true, cls: o.className, name: (o.querySelector(".ab-name") || {}).textContent || "",
    atom: svg ? svg.outerHTML : "", note: (o.querySelector(".ab-note-t") || {}).textContent || "",
    back: !!(o.querySelector(".ab-back") && getComputedStyle(o.querySelector(".ab-back")).display !== "none"),
    backText: (o.querySelector(".ab-back") || {}).textContent || "" };
});

// ══ A · CONTINUIDAD + REVELA-SÓLO-LISTA ══
{
  const chk = scen("A"); console.log("══ A · continuidad + revela-sólo-lista ══");
  const ctx = await newCtx();
  const page = await ctx.newPage();
  const cerr = []; page.on("pageerror", (e) => cerr.push(String(e)));
  // 1) Cuarto: levantá el puente (sin navegar: delay enorme) y capturá el frame de SALIDA (held).
  await salaRoutes(page, { beltDelayMs: 900 });
  await page.goto(base + "/cuarto/cuarto.html", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!window.AlephBridge, { timeout: 10_000 });
  await page.evaluate((n) => window.AlephBridge.raise({ name: n, href: "javascript:void(0)", delay: 100000 }), NAME);
  await page.waitForFunction(() => { const o = document.getElementById("ab-overlay"); return o && o.classList.contains("ab-in"); }, { timeout: 5_000 });
  await page.waitForTimeout(700);   // que ab-in llegue al pico
  const exit = await grabFrame(page);
  await page.screenshot({ path: SHOTS + "bridge-A1-cuarto-exit.png" });
  chk.check("A · overlay presente en el Cuarto (frame de salida)", exit.present && /Agente demo/.test(exit.name), JSON.stringify({ name: exit.name }));

  // 2) Sala: navegá (mismo origen → el token cruza) y capturá el frame de ENTRADA (held) antes de revelar.
  await page.goto(base + "/sala/sala.html?puppet=" + PID, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => { const o = document.getElementById("ab-overlay"); return o && o.classList.contains("ab-held"); }, { timeout: 5_000 });
  const entry = await grabFrame(page);
  await page.screenshot({ path: SHOTS + "bridge-A2-sala-entry.png" });
  chk.check("A · overlay presente en la Sala (frame de entrada, held)", entry.present && /ab-held/.test(entry.cls));
  // CONTINUIDAD: mismo átomo mascota + mismo nombre en los dos archivos → corte continuo
  chk.check("A · CUT FRAME continuo: átomo idéntico Cuarto≡Sala", exit.atom && exit.atom === entry.atom, "atoms differ");
  chk.check("A · CUT FRAME continuo: mismo nombre de agente", exit.name === entry.name && /Agente demo/.test(entry.name), exit.name + " | " + entry.name);
  // la Sala NO se reveló todavía (belt aún carga) → el overlay TAPA la Sala
  const shellHidden = await page.evaluate(() => {
    const o = document.getElementById("ab-overlay"); if (!o) return false;
    const rc = o.getBoundingClientRect();
    return getComputedStyle(o).opacity === "1" && rc.width >= window.innerWidth - 2 && rc.height >= window.innerHeight - 2;
  });
  chk.check("A · el overlay TAPA la Sala mientras carga (no revela a medias)", shellHidden);

  // 3) cuando la Sala está de verdad lista (belt pintado) → revela: overlay se remueve, stack poblado
  await page.waitForSelector("#ab-overlay", { state: "detached", timeout: 6_000 }).then(() => chk.check("A · REVELA al estar lista (overlay removido)", true)).catch(() => chk.check("A · REVELA al estar lista (overlay removido)", false, "overlay no se removió"));
  const ready = await page.evaluate(() => { const s = document.getElementById("stackPanel"); return { on: !!(s && s.classList.contains("on")), pieces: document.querySelectorAll("#stackRow .piece").length, agent: (document.getElementById("agentName") || {}).textContent || "" }; });
  chk.check("A · la Sala revelada está lista (stack poblado + nombre real)", ready.on && ready.pieces === 2 && /Agente demo/.test(ready.agent), JSON.stringify(ready));
  chk.check("A · consola limpia", cerr.length === 0, cerr.slice(0, 2).join(" | "));
  await page.screenshot({ path: SHOTS + "bridge-A3-sala-revealed.png" });
  results.push({ name: "A-continuidad", pass: chk.fails.length === 0, fails: chk.fails });
  await ctx.close();
}

// ══ B · FALLO HONESTO (puppet no encontrado) ══
{
  const chk = scen("B"); console.log("══ B · fallo honesto ══");
  const ctx = await newCtx(NAME);   // sembramos el token → simula venir del Cuarto
  const page = await ctx.newPage();
  await salaRoutes(page, { puppetFound: false });
  await page.goto(base + "/sala/sala.html?puppet=" + PID, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => { const o = document.getElementById("ab-overlay"); return o && o.classList.contains("ab-fail"); }, { timeout: 8_000 }).catch(() => {});
  await page.waitForTimeout(300);
  const f = await grabFrame(page);
  await page.screenshot({ path: SHOTS + "bridge-B-fail.png" });
  chk.check("B · overlay QUEDA (no revela)", f.present && /ab-fail/.test(f.cls), JSON.stringify({ present: f.present, cls: f.cls }));
  chk.check("B · nota honesta (no 'cobrando vida')", /no encontramos|no es tuyo|borrado/i.test(f.note), f.note);
  chk.check("B · ofrece 'Volver al Cuarto'", f.back && f.backText === "Volver al Cuarto", f.backText);
  // la Sala inline NO se revela: el overlay sigue tapando
  const stillCovering = await page.evaluate(() => { const o = document.getElementById("ab-overlay"); return !!o && getComputedStyle(o).opacity === "1"; });
  chk.check("B · NO revela una Sala inline disfrazada", stillCovering);
  results.push({ name: "B-fallo-honesto", pass: chk.fails.length === 0, fails: chk.fails });
  await ctx.close();
}

// ══ C · SIN TOKEN → carga directa, sin overlay ══
{
  const chk = scen("C"); console.log("══ C · sin token (carga directa) ══");
  const ctx = await newCtx();   // sin token
  const page = await ctx.newPage();
  await salaRoutes(page, {});
  await page.goto(base + "/sala/sala.html?puppet=" + PID, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#composer", { timeout: 10_000 });
  await page.waitForTimeout(300);
  const hasOverlay = await page.evaluate(() => !!document.getElementById("ab-overlay"));
  chk.check("C · sin token → NO hay overlay (carga directa)", !hasOverlay);
  chk.check("C · la Sala carga normal (#composer)", await page.$("#composer") !== null);
  results.push({ name: "C-sin-token", pass: chk.fails.length === 0, fails: chk.fails });
  await ctx.close();
}

// ══ estático · wiring ══
{
  console.log("══ estático · wiring ══");
  const cuarto = fs.readFileSync(DESIGN + "cuarto/cuarto.html", "utf8");
  const sala = fs.readFileSync(DESIGN + "sala/sala.html", "utf8");
  const c1 = /AlephBridge\.raise\(/.test(cuarto) && /src="\.\.\/bridge\.js"/.test(cuarto);
  const c2 = /AlephBridge\.receive\(/.test(sala) && /src="\.\.\/bridge\.js"/.test(sala);
  console.log((c1 ? "  ✓ " : "  ✗ ") + "cuarto.html carga bridge.js y llama AlephBridge.raise");
  console.log((c2 ? "  ✓ " : "  ✗ ") + "sala.html carga bridge.js y llama AlephBridge.receive");
  results.push({ name: "estatico-wiring", pass: c1 && c2, fails: (c1 && c2) ? [] : ["wiring"] });
}

await browser.close();
srv.close();
const allok = results.every((r) => r.pass);
fs.writeFileSync(SALA + "EVIDENCE-step4-bridge.json", JSON.stringify({ ok: allok, results }, null, 2));
console.log("\nevidence → " + SALA + "EVIDENCE-step4-bridge.json");
console.log(allok ? "\x1b[32m\x1b[1mALL GREEN ✓\x1b[0m" : "\x1b[31m\x1b[1mRED ✗\x1b[0m  " + results.filter((r) => !r.pass).map((r) => r.name).join(", "));
process.exit(allok ? 0 : 1);
