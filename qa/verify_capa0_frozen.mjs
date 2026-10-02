/* verify_capa0_frozen.mjs — CAPA 0: la obra se RENDERIZA DENTRO DEL BINARIO.
 *
 * Casa 2 · Fase 4 · 4.4.1. Gemelo de qa/verify_capa0_offline.mjs pero contra el SIDECAR
 * CONGELADO (dist/aleph_sidecar) — el `.exe` sirviéndose a sí mismo desde _MEIPASS. El
 * criterio NO es "el archivo se sirve" sino "la obra RENDERIZA": se monta obra real de
 * cada tipo y se comprueba el DOM que produjo cada renderer.
 *
 * Dos pasadas por caso:
 *   NORMAL      — sólo el origen del sidecar permitido (cero CDNs): la obra DEBE renderizar.
 *   FALSIFICADA — igual pero abortando la lib del caso: la obra DEBE fallar. Esto prueba
 *                 que el test mide RENDER, no serving (esconder la lib → rojo, como en F1).
 * Verde por caso = NORMAL pasa (con la lib servida 200 por el sidecar) Y FALSIFICADA falla.
 *
 * El visor 3D va en iframe sandbox="allow-scripts" SIN allow-same-origin (protege BYOK):
 * contentDocument da null POR DISEÑO → se mide con la API de frames de Playwright.
 *
 *   node qa/verify_capa0_frozen.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "./lib/frozen_guard.mjs";
import net from "node:net";
import path from "node:path";
import fs from "node:fs";

const ROOT = new URL("..", import.meta.url).pathname;
// Por defecto el sidecar onedir de dev; override con ALEPH_SIDECAR_BIN para apuntar al
// binario CONGELADO que ships en el .app (Contents/MacOS/aleph_sidecar) — así el 5/5 se
// mide contra el bundle RELEASE, no contra dev (criterio 4.4.2).
const SIDECAR = process.env.ALEPH_SIDECAR_BIN || path.join(ROOT, "dist/aleph_sidecar/aleph_sidecar");

if (!fs.existsSync(SIDECAR)) {
  console.error(`\n  ✗ no existe el sidecar congelado: ${SIDECAR}\n` +
    `    construílo: pyinstaller --distpath dist deploy/fase4/aleph_sidecar.spec\n`);
  process.exit(2);
}

function freePort() {
  return new Promise((res, rej) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); });
    s.on("error", rej);
  });
}
function waitReady(port, ms) {
  const t0 = Date.now();
  return new Promise((res) => {
    (function tick() {
      const sock = net.connect(port, "127.0.0.1");
      sock.on("connect", () => { sock.destroy(); res(true); });
      sock.on("error", () => {
        sock.destroy();
        if (Date.now() - t0 > ms) return res(false);
        setTimeout(tick, 150);
      });
    })();
  });
}

// ── LOS CASOS (idénticos a verify_capa0_offline.mjs — la obra real por tipo) ──────
const CASOS = [
  { id: "marked · markdown",
    lib: "marked.min.js",
    obra: { type: "informe", content: "# Título\n\nTexto con **negrita**.\n\n- uno\n- dos\n" },
    assert: (d) => d.h1 >= 1 && d.li >= 2 },

  { id: "hljs · código",
    lib: "highlight.min.js",
    obra: { type: "informe", content: "```python\ndef suma(a, b):\n    return a + b\n```\n" },
    assert: (d) => d.hljsSpans >= 2 },

  { id: "katex · fórmula",
    lib: "katex/katex.min.js",
    obra: { type: "informe", content: "La energía: $$E = mc^2$$\n" },
    assert: (d) => d.katex >= 1 && !d.textoCrudoFormula },

  { id: "three · 3D (STL)",
    lib: "three/three.min.js",
    obra: { type: "cad", format: "stl", content:
      "solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid t\n" },
    assert: (d) => d.iframeCanvas === true },

  { id: "xlsx · planilla",
    lib: "xlsx.full.min.js",
    obra: null,
    assert: (d) => d.xlsxOk === true },
];

const port = await freePort();
const child = spawnFrozen(SIDECAR, ["--port", String(port)], { stdio: "ignore", env: { ...process.env, ALEPH_ROLE: "client" } });
const up = await waitReady(port, 40000);
if (!up) { console.error("  ✗ el sidecar congelado no respondió"); matarFrozen(child); process.exit(2); }
const base = "http://127.0.0.1:" + port;
console.log(`\n  sidecar congelado en ${base} (pid ${child.pid})`);

const browser = await chromium.launch();

async function correr(caso, { blockLib }) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errs = [];
  const responses = [];
  page.on("pageerror", (e) => errs.push(String(e).split("\n")[0].slice(0, 80)));
  page.on("response", (r) => responses.push({ url: r.url(), status: r.status() }));
  // Sólo el origen del sidecar (cero red externa). En falsificación, además abortar la lib.
  await page.route("**/*", (rt) => {
    const u = rt.request().url();
    if (!u.startsWith(base)) return rt.abort();
    if (blockLib && u.includes(caso.lib)) return rt.abort();
    return rt.continue();
  });
  await page.goto(`${base}/sala-v2/__probe_capa0_v2.html`, { waitUntil: "load", timeout: 25000 });
  await page.waitForFunction(() => !!window.SalaRender, null, { timeout: 15000 }).catch(() => {});
  const d = await page.evaluate(async (obra) => {
    const host = document.getElementById("host");
    const out = { h1: 0, li: 0, hljsSpans: 0, katex: 0, textoCrudoFormula: false,
                  hayIframe: false, iframeCanvas: false, xlsxOk: false };
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
        return e ? e.textContent.slice(0, 90) : null;
      }).catch(() => null);
    } else { d.iframeErr = "el iframe no apareció como frame"; }
  }
  await ctx.close();
  const libLocal = responses.some((s) => s.url.includes(caso.lib) && s.status === 200);
  return { ...d, libLocal, errs: [...new Set(errs)] };
}

console.log("\n  Cada caso: obra real → ¿el renderer produjo su DOM DENTRO del binario? (+ falsificación)\n");
let ok = 0, fail = 0;
for (const c of CASOS) {
  const normal = await correr(c, { blockLib: false });
  const falso = await correr(c, { blockLib: true });
  const pasaNormal = c.assert(normal);
  const pasaFalso = c.assert(falso);
  // Verde: renderiza normal (con lib servida 200) Y la falsificación lo rompe.
  const verde = pasaNormal && !pasaFalso && normal.libLocal;
  let marca = verde ? "✓" : "✗";
  if (verde) ok++; else fail++;
  let nota = "";
  if (pasaNormal && !normal.libLocal) nota = " (¡renderizó sin servir la lib? sospechoso)";
  if (!pasaNormal) nota = " NO RENDERIZA en frozen";
  else if (pasaFalso) nota = " la falsificación NO lo rompió (test ciego)";
  const det = normal.iframeErr ? ` · iframe:${normal.iframeErr}` : (normal.xlsxErr ? ` · ${normal.xlsxErr}` : "");
  console.log(`  ${marca} ${c.id.padEnd(20)} render:${pasaNormal ? "sí" : "NO"}  lib-servida-200:${normal.libLocal ? "sí" : "NO"}  falsificado-rompe:${!pasaFalso ? "sí" : "NO"}${nota}${det}`);
}

// ── DIAGNÓSTICO (no cuenta en el 5/5): el visor .gltf/.obj/.glb — confirmar fallo EXPLÍCITO ──
console.log("\n  Diagnóstico visor .gltf/.obj/.glb (roto de antes por three r160 — se confirma explícito):");
{
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.route("**/*", (rt) => rt.request().url().startsWith(base) ? rt.continue() : rt.abort());
  await page.goto(`${base}/sala-v2/__probe_capa0_v2.html`, { waitUntil: "load", timeout: 25000 });
  await page.waitForFunction(() => !!window.SalaRender, null, { timeout: 15000 }).catch(() => {});
  await page.evaluate(async () => {
    const host = document.getElementById("host");
    await window.SalaRender.renderArtifact(host, { type: "cad", format: "gltf",
      content: '{"asset":{"version":"2.0"},"scenes":[{"nodes":[]}],"nodes":[]}' });
    await new Promise((r) => setTimeout(r, 1500));
  });
  await page.waitForTimeout(2000);
  const fr = page.frames().find((f) => f !== page.mainFrame());
  let err = null, canvas = false;
  if (fr) {
    err = await fr.evaluate(() => { const e = document.querySelector("#err"); return e ? e.textContent.trim().slice(0, 140) : null; }).catch(() => null);
    canvas = await fr.evaluate(() => { const c = document.querySelector("canvas"); return !!(c && c.width > 0); }).catch(() => false);
  }
  const explicito = !!err && /loader|clásico|distribuye|formato|three|no cargó/i.test(err);
  console.log(`  ${explicito ? "✓" : "✗"} gltf: canvas:${canvas ? "sí" : "no"}  #err: ${err ? JSON.stringify(err) : "(vacío)"}`);
  console.log(`     → ${explicito ? "falla EXPLÍCITO (esperado, no se arregla en 4.4.1)" : "OJO: fallo NO explícito o cambió de forma"}`);
  await ctx.close();
}

await browser.close();
matarFrozen(child);   // grupo entero: SIGKILL al bootloader deja vivo el fork
console.log(`\n  ${ok}/${CASOS.length} tipos de obra RENDERIZAN dentro del binario (con falsificación)\n`);
process.exit(fail ? 1 : 0);
