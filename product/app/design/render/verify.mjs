/* verify.mjs — DONE-BAR real del módulo render (no self-report).
 *
 * Sirve product/app/design/ por http efímero (el demo carga ../i18n.js — la raíz
 * DEBE ser design/ o el 404 silencioso devuelve claves crudas), abre render.demo.html
 * en Chromium headless y endurece el verde:
 *   · TODO type de TYPES tiene sample (un card sin payload = ROJO, no vacío que cuenta ✓)
 *   · ningún stage con .ar-empty / .ar-err
 *   · asserts ESTRUCTURALES por tipo (grilla con filas, heatmap canvas, stepper de
 *     convergencia con dots + veredicto PASA, charts del informe)
 *   · adentro de los iframes: cad/volume3d con canvas three y sin #err; web con botón
 *   · anti-claves-crudas: ningún "render.*" literal visible (i18n resuelto de verdad)
 * Salida JSON + screenshot + exit code. Uso: node verify.mjs */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const DIR = dirname(fileURLToPath(import.meta.url));          // …/render
const ROOT = resolve(DIR, "..");                              // …/design (por ../i18n.js)
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png" };

const server = createServer(async (req, res) => {
  try {
    const p = decodeURIComponent(req.url.split("?")[0]);
    const file = resolve(join(ROOT, p));
    if (!file.startsWith(ROOT)) throw new Error("fuera de raíz");
    const buf = await readFile(file);
    res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
    res.end(buf);
  } catch { res.writeHead(404); res.end("nope"); }
});
await new Promise((r) => server.listen(0, r));
const port = server.address().port;
const URL = `http://localhost:${port}/render/render.demo.html`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1340, height: 1700 }, deviceScaleFactor: 1 });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

let result = { ok: false, fails: [] };
const fail = (name, detail) => result.fails.push(name + (detail ? " → " + detail : ""));
try {
  await page.goto(URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__AR_DEMO_DONE, null, { timeout: 30000 });
  await page.waitForTimeout(2500); // three/CDN dentro de los iframes

  const st = await page.evaluate(() => {
    const S = window.AlephRenderSamples || {};
    const T = (window.AlephRender && window.AlephRender.TYPES) || [];
    const missing = T.filter((t) => !S[t]);
    const cards = [...document.querySelectorAll(".card")].map((c) => {
      const type = c.querySelector(".badge").textContent;
      const stage = c.querySelector(".stage");
      const conv = stage.querySelector(".ar-conv");
      let verdictPass = null;
      if (conv) {
        const node = stage.querySelector(".aleph-render");
        if (node && node._convShow) { node._convShow((node._convCount || 1) - 1); }
        verdictPass = /pass/.test((stage.querySelector(".ar-conv-verdict") || {}).className || "");
      }
      return {
        type,
        ok: c.querySelector(".status").classList.contains("ok"),
        empty: !!stage.querySelector(".ar-empty"),
        err: !!stage.querySelector(".ar-err"),
        rows: stage.querySelectorAll("table tbody tr").length,
        canvases: stage.querySelectorAll("canvas").length,
        charts: stage.querySelectorAll(".ar-chart-fig").length,
        candleUp: stage.querySelectorAll('rect[data-candle="up"]').length,
        candleDown: stage.querySelectorAll('rect[data-candle="down"]').length,
        sortable: stage.querySelectorAll("th.ar-sortable").length,
        convDots: stage.querySelectorAll(".ar-conv-dot").length,
        verdictPass,
      };
    });
    // claves i18n crudas visibles = i18n roto (p.ej. ../i18n.js 404). Se excluyen
    // nombres de archivo (el footer cita render.js) — una CLAVE jamás termina en extensión.
    const rawKeys = (document.body.innerText.match(/render\.[a-z_.]+/gi) || [])
      .filter((k) => !/\.(js|mjs|html|css|json)$/i.test(k)).slice(0, 5);
    return { demo: window.__AR_DEMO_DONE, cards, missing, rawKeys, total: T.length };
  });
  result = { ...result, ...st };

  if (st.missing.length) fail("samples faltantes para TYPES", st.missing.join(","));
  if (!(st.demo && st.demo.ok === st.demo.total)) fail("demo.ok !== total", JSON.stringify(st.demo));
  if (st.rawKeys.length) fail("claves i18n crudas visibles", st.rawKeys.join(","));
  for (const c of st.cards) {
    if (!c.ok) fail(c.type + ": status err");
    if (c.empty) fail(c.type + ": estado vacío (sample no hidrató)");
    if (c.err) fail(c.type + ": renderError");
  }
  const by = Object.fromEntries(st.cards.map((c) => [c.type, c]));
  if (!(by.planilla && by.planilla.rows > 0)) fail("planilla sin filas");
  if (!(by.planilla && by.planilla.sortable > 0)) fail("planilla sin cabeceras ordenables");
  if (!(by.informe && by.informe.charts === 4)) fail("informe: se esperan 4 charts (bar/area/scatter/candlestick)", String(by.informe && by.informe.charts));
  if (!(by.informe && by.informe.candleUp > 0 && by.informe.candleDown > 0))
    fail("candlestick sin velas up+down reales", JSON.stringify({ up: by.informe && by.informe.candleUp, down: by.informe && by.informe.candleDown }));
  if (!(by.fieldplot && by.fieldplot.canvases >= 1)) fail("fieldplot sin canvas");
  if (!(by.dicom && by.dicom.canvases >= 1)) fail("dicom sin canvas");
  if (!(by.convergence && by.convergence.convDots === 3)) fail("convergence sin sus 3 dots", JSON.stringify(by.convergence));
  if (!(by.convergence && by.convergence.verdictPass === true)) fail("convergence: veredicto final no es PASA");
  if (!(by.linechart && by.linechart.charts >= 1)) fail("linechart sin serie real (ar-chart-fig)", JSON.stringify(by.linechart));

  // sort interactivo de la planilla: click asc → click desc sobre la col numérica
  const sortProbe = await page.evaluate(() => {
    const stage = [...document.querySelectorAll(".card")]
      .find((c) => c.querySelector(".badge").textContent === "planilla")?.querySelector(".stage");
    const table = stage && stage.querySelector("table");
    if (!table) return { ok: false, why: "sin tabla" };
    const th = table.tHead.rows[0].cells[1];               // col numérica (PIB)
    const colVals = () => [...table.tBodies[0].rows].map((r) => parseFloat(r.cells[1].textContent.replace(/[^\d.-]/g, "")));
    th.click(); const asc = colVals();
    th.click(); const desc = colVals();
    const isAsc = asc.every((v, i) => !i || asc[i - 1] <= v);
    const isDesc = desc.every((v, i) => !i || desc[i - 1] >= v);
    return { ok: isAsc && isDesc, asc, desc, aria: th.getAttribute("aria-sort") };
  });
  if (!sortProbe.ok) fail("sort de planilla no ordena asc/desc", JSON.stringify(sortProbe));

  // adentro de los iframes: cad + volume3d (canvas three, sin #err), web (botón)
  let iframeCanvases = 0, iframeErrs = 0, webButton = false;
  for (const f of page.frames()) {
    if (f === page.mainFrame()) continue;
    const probe = await f.evaluate(() => ({
      hasCanvas: !!document.querySelector("canvas"),
      hasErr: !!document.querySelector("#err"),
      hasButton: !!document.querySelector("button"),
    })).catch(() => null);
    if (!probe) continue;
    if (probe.hasCanvas) iframeCanvases++;
    if (probe.hasErr) iframeErrs++;
    if (probe.hasButton) webButton = true;
  }
  result.iframes = { iframeCanvases, iframeErrs, webButton };
  if (iframeCanvases < 2) fail("iframes 3D: se esperan ≥2 canvas (cad+volume3d)", String(iframeCanvases));
  if (iframeErrs) fail("iframe con #err", String(iframeErrs));
  if (!webButton) fail("web: sin botón dentro del iframe");

  await page.screenshot({ path: join(DIR, "screenshots", "render-donebar.png"), fullPage: true });
  result.screenshot = "screenshots/render-donebar.png";
} catch (e) {
  result.error = String(e);
  fail("excepción", String(e));
}
result.consoleErrors = errors.filter((t) => !/favicon/i.test(t)).slice(0, 20);
if (result.consoleErrors.length) fail("consola con errores", result.consoleErrors[0]);
result.pass = result.fails.length === 0;

console.log(JSON.stringify(result, null, 2));
await browser.close();
server.close();
process.exit(result.pass ? 0 : 1);
