#!/usr/bin/env node
/**
 * chart-inline.mjs — spec de gráfico en la burbuja → SVG, no JSON crudo.
 *
 * ROJO sin el arreglo: marked deja ```json / fence sin lenguaje como <pre><code>
 * y nadie llama renderInlineFigures en el hilo v2.
 * VERDE: spec válida (raíz o Chart.js) se vuelve .sala-chart-fig; JSON de schema,
 * python y spec rota siguen siendo código.
 *
 * Run: node product/app/design/sala-v2/verify/chart-inline.mjs
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DESIGN = join(HERE, "..", "..");
const PORT = Number(process.env.CHART_INLINE_PORT || 8251);
const PAGE = `http://127.0.0.1:${PORT}/sala-v2/verify/chart-inline.html`;
const SHOT = join(HERE, "screenshots", "chart-inline.png");

const fails = [];
const ok = (n) => console.log(`  ✅ ${n}`);
const bad = (n, d) => {
  fails.push(`${n}${d ? " — " + d : ""}`);
  console.log(`  ❌ ${n}${d ? " — " + d : ""}`);
};

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const file = join(DESIGN, decodeURIComponent(url.pathname));
  if (!file.startsWith(DESIGN)) { res.writeHead(403).end("no"); return; }
  try {
    const body = await readFile(file);
    res.writeHead(200, { "Content-Type": MIME[extname(file)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404).end("404");
  }
});
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 900, height: 1400 } });
await page.goto(PAGE, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => window.__despues, { timeout: 20000 });
const st = await page.evaluate(() => ({ mdOnly: window.__mdOnly, despues: window.__despues }));

console.log("\nROJO (solo markdown, sin renderInlineFigures)");
if (st.mdOnly.figs === 0 && st.mdOnly.jsonVisible) ok("sin figures: el JSON sigue en el DOM (el defecto)");
else bad("el rojo no se reproduce", JSON.stringify(st.mdOnly));

console.log("\nVERDE (después de renderInlineFigures)");
if (st.despues.figs === 2) ok("2 gráficos SVG (line raíz + bar Chart.js)");
else bad("figs != 2", JSON.stringify(st.despues));
if (st.despues.paths >= 1) ok("el line tiene path");
else bad("sin path de línea", JSON.stringify(st.despues));
if (st.despues.python) ok("el bloque python sigue siendo código");
else bad("python se comió");
if (st.despues.schema) ok("JSON Schema {type:object} NO se dibuja como chart");
else bad("schema se dibujó como chart");
if (st.despues.specRotaComoCodigo) ok("spec inválida queda como código, no rompe");
else bad("spec rota no quedó como código");
if (!st.despues.jsonLineVisible) ok("el JSON interno del line no queda a la vista como spec");
else bad("el JSON del line sigue visible");

await mkdir(join(HERE, "screenshots"), { recursive: true });
await page.screenshot({ path: SHOT, fullPage: true });
console.log("\n  screenshot", SHOT);

await browser.close();
server.close();
if (fails.length) {
  console.log("\nROJO ×" + fails.length);
  process.exit(1);
}
console.log("\nVERDE");
process.exit(0);
