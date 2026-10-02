/* p3_carga.mjs — CONTENCIÓN A PROPÓSITO, para correr la vara de P1A bajo carga.
 *
 * §8 del mandato: la carrera del repintado «es reproducible bajo carga». Una vara que sólo
 * corre en una máquina ociosa mide un Cuarto que no existe: sin contención la ventana entre
 * la lectura barata y la prueba cara es de milisegundos y casi nunca se cruza. Esto FABRICA
 * la contención mientras la vara corre:
 *   · CPU     — N workers quemando ciclos (el render y los timers se atrasan);
 *   · RED     — M navegadores WebKit martillando el mismo sidecar (los GET se encolan).
 * No toca el producto ni la vara: sólo hace que la máquina se parezca a la mala.
 *
 * Run:  node qa/p3_carga.mjs &                    (queda cargando hasta que lo bajen)
 *       SIDECAR=http://127.0.0.1:8273 node product/app/design/cuarto/verify_p1a_reintentar.mjs
 */
import { webkit } from "playwright";
import { Worker, isMainThread } from "node:worker_threads";

const BASE = process.env.SIDECAR || "http://127.0.0.1:8273";
const CPUS = Number(process.env.P3_CPU || 6);
const NAVS = Number(process.env.P3_NAV || 3);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!isMainThread) {                       // worker: quema CPU hasta que lo maten
  // eslint-disable-next-line no-constant-condition
  for (let x = 0; true;) { x = Math.sqrt(x + Math.random() * 1e6) | 0; }
}

const workers = [];
for (let i = 0; i < CPUS; i++) workers.push(new Worker(new URL(import.meta.url)));
console.log(`── carga: ${CPUS} workers de CPU`);

const browser = await webkit.launch();
const pages = [];
for (let i = 0; i < NAVS; i++) {
  const p = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await p.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" }).catch(() => {});
  pages.push(p);
}
console.log(`── carga: ${NAVS} navegadores martillando ${BASE}`);

let vivo = true;
const bajar = async () => {
  if (!vivo) return; vivo = false;
  for (const w of workers) { try { await w.terminate(); } catch {} }
  try { await browser.close(); } catch {}
  process.exit(0);
};
process.on("SIGINT", bajar); process.on("SIGTERM", bajar);

// martilleo continuo del motor: los GET se encolan y las lecturas tardan de verdad
while (vivo) {
  await Promise.all(pages.map((p) => p.evaluate(() => {
    const C = window.__cuarto; if (!C) return;
    try { window.__renderPieces && window.__renderPieces(); } catch (e) {}
    return fetch("/v1/motor/estado?tipo=mcp&ref=carga").catch(() => {});
  }).catch(() => {})));
  await sleep(120);
}
