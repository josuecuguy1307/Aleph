/* verify_capa0_offline.mjs — CAPA 0: la obra se RENDERIZA sin internet.
 *
 * Casa 2 · F1.c. El "wow base bundleado" es esto y sólo esto: el agente produce algo y
 * La Sala lo muestra, con el cerebro como única cosa que necesita red.
 *
 * Los renderers bajaban marked / dompurify / katex / hljs / three / xlsx de jsdelivr
 * BAJO DEMANDA — o sea el fallo no aparecía al abrir La Sala vacía, sino recién cuando
 * había algo real que mostrar. Por eso esta sonda NO abre una Sala vacía: monta un
 * artifact de CADA tipo y comprueba el DOM que produjo cada renderer.
 *
 * Cada caso se corre DOS veces (con red y sin red) y se exige el MISMO resultado. Un
 * renderer que falla igual en ambos lados no es una regresión de esto — se reporta como
 * roto-de-antes, no como falso verde.
 *
 *   node qa/verify_capa0_offline.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const DESIGN = path.join(ROOT, "product/app/design") + "/";
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
               ".css": "text/css", ".json": "application/json", ".png": "image/png",
               ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff",
               ".ttf": "font/ttf" };

let servidos = [];
const srv = http.createServer((q, r) => {
  const rel = decodeURIComponent(new URL(q.url, "http://x").pathname);
  const p = path.join(DESIGN, rel);
  if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) {
    servidos.push({ rel, status: 404 }); r.writeHead(404); r.end(); return;
  }
  servidos.push({ rel, status: 200 });
  r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(r);
});
await new Promise((res) => srv.listen(0, "127.0.0.1", res));
const base = "http://127.0.0.1:" + srv.address().port;

// ── LOS CASOS ─────────────────────────────────────────────────────────────────
// Cada uno: la obra que produciría el agente + qué tiene que aparecer en el DOM si el
// renderer REALMENTE corrió (no basta con que no explote).
const CASOS = [
  { id: "marked · markdown",
    lib: "marked.min.js",
    obra: { type: "informe", content: "# Título\n\nTexto con **negrita**.\n\n- uno\n- dos\n" },
    // marked convirtió el markdown a HTML de verdad: hay <h1> y <li>, no el texto crudo
    assert: (d) => d.h1 >= 1 && d.li >= 2 },

  { id: "hljs · código",
    lib: "highlight.min.js",
    // No hay renderer "codigo": el código viaja como fence markdown dentro de un
    // informe, que es como lo produce el agente, y highlightIn() lo resalta.
    obra: { type: "informe", content: "```python\ndef suma(a, b):\n    return a + b\n```\n" },
    // highlight.js mete <span class="hljs-…"> por token; sin él el <pre> queda pelado
    assert: (d) => d.hljsSpans >= 2 },

  { id: "katex · fórmula",
    lib: "katex/katex.min.js",
    obra: { type: "informe", content: "La energía: $$E = mc^2$$\n" },
    // KaTeX produce .katex con MathML dentro; el $$…$$ crudo desaparece
    assert: (d) => d.katex >= 1 && !d.textoCrudoFormula },

  { id: "three · 3D (STL)",
    lib: "three/three.min.js",
    obra: { type: "cad", format: "stl", content:
      "solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid t\n" },
    // el visor vive en un iframe: se comprueba que ADENTRO haya un <canvas> con WebGL
    assert: (d) => d.iframeCanvas === true },

  { id: "xlsx · planilla",
    lib: "xlsx.full.min.js",
    // xlsx se carga desde sala.html contra un .xlsx del backend; acá se prueba que la
    // LIB queda utilizable sin red (leer un libro que se arma en memoria).
    obra: null,
    assert: (d) => d.xlsxOk === true },
];

const browser = await chromium.launch();
let ok = 0, fail = 0, rotoDeAntes = 0;

async function correr(caso, { offline }) {
  servidos = [];
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e).split("\n")[0].slice(0, 80)));
  if (offline) {
    await page.route("**/*", (rt) => rt.request().url().startsWith(base)
      ? rt.continue() : rt.abort());
  }
  // página mínima que carga SOLO el renderer — sin backend, sin sesión, sin La Sala entera:
  // lo que se prueba es el renderer, no el resto de la app.
  await page.goto(`${base}/sala-v2/__probe_capa0_v2.html`, { waitUntil: "load", timeout: 25000 });
  await page.waitForFunction(() => !!window.SalaRender, null, { timeout: 15000 }).catch(() => {});
  const d = await page.evaluate(async (obra) => {
    const host = document.getElementById("host");
    const out = { h1: 0, li: 0, hljsSpans: 0, katex: 0, textoCrudoFormula: false,
                  iframeCanvas: false, xlsxOk: false };
    if (obra) {
      await window.SalaRender.renderArtifact(host, obra);
      await new Promise((r) => setTimeout(r, 2500));
      out.h1 = host.querySelectorAll("h1").length;
      out.li = host.querySelectorAll("li").length;
      out.hljsSpans = host.querySelectorAll('[class*="hljs-"]').length;
      out.katex = host.querySelectorAll(".katex").length;
      out.textoCrudoFormula = /\$\$/.test(host.innerText || "");
      out.hayIframe = !!host.querySelector("iframe");
    } else {
      // xlsx: se carga la lib y se lee un libro construido en memoria
      await new Promise((res, rej) => {
        const s = document.createElement("script");
        s.src = new URL("../vendor/xlsx.full.min.js", document.baseURI).href;
        s.onload = res; s.onerror = rej; document.head.appendChild(s);
      }).catch(() => {});
      try {
        const wb = window.XLSX.utils.book_new();
        window.XLSX.utils.book_append_sheet(wb, window.XLSX.utils.aoa_to_sheet([["a", 1], ["b", 2]]), "H");
        const buf = window.XLSX.write(wb, { type: "array", bookType: "xlsx" });
        const leido = window.XLSX.read(buf, { type: "array" });
        const celdas = window.XLSX.utils.sheet_to_json(leido.Sheets["H"], { header: 1 });
        out.xlsxOk = celdas.length === 2 && celdas[0][0] === "a" && celdas[1][1] === 2;
      } catch (e) { out.xlsxErr = String(e).slice(0, 60); }
    }
    return out;
  }, caso.obra);

  // El visor 3D vive en un iframe con sandbox="allow-scripts" y SIN allow-same-origin
  // (deliberado: protege BYOK/sesión). Por eso el padre NO puede leer su contentDocument
  // —da null, y eso NO es un fallo del renderer— y hay que mirarlo con la API de frames
  // de Playwright, que trabaja a nivel browser y no está atada al same-origin.
  if (d.hayIframe) {
    await page.waitForTimeout(3000);
    const fr = page.frames().find((f) => f !== page.mainFrame());
    if (fr) {
      d.iframeCanvas = await fr.evaluate(() => {
        const c = document.querySelector("canvas");
        return !!(c && c.width > 0);
      }).catch(() => false);
      d.iframeErr = await fr.evaluate(() => {
        const e = document.querySelector("#err");
        return e ? e.textContent.slice(0, 80) : null;
      }).catch(() => null);
    } else { d.iframeErr = "el iframe no apareció como frame"; }
  }
  await ctx.close();
  const libLocal = servidos.some((s) => s.rel.includes(caso.lib) && s.status === 200);
  return { ...d, libLocal, errs: [...new Set(errs)] };
}

console.log("\n  Cada caso: obra real → ¿el renderer produjo el DOM que debe producir?\n");
for (const c of CASOS) {
  const con = await correr(c, { offline: false });
  const sin = await correr(c, { offline: true });
  const pasaCon = c.assert(con), pasaSin = c.assert(sin);
  let marca, nota = "";
  if (pasaSin && pasaCon) { marca = "✓"; ok++; }
  else if (!pasaCon && !pasaSin) { marca = "⚠"; rotoDeAntes++; nota = " ROTO TAMBIÉN CON RED (no es de esto)"; }
  else { marca = "✗"; fail++; nota = " sólo falla SIN red → sigue atado al CDN"; }
  const det = sin.iframeErr ? ` · iframe: ${sin.iframeErr}` : (sin.xlsxErr ? ` · ${sin.xlsxErr}` : "");
  console.log(`  ${marca} ${c.id.padEnd(20)} con red:${pasaCon ? "ok" : "no"}  sin red:${pasaSin ? "ok" : "no"}  lib local:${sin.libLocal ? "sí" : "NO"}${nota}${det}`);
}

await browser.close();
srv.close();
console.log(`\n  ${ok}/${CASOS.length} tipos de obra renderizan SIN INTERNET` +
            (rotoDeAntes ? `  ·  ${rotoDeAntes} roto de antes (con red tampoco anda)` : ""));
process.exit(fail ? 1 : 0);
