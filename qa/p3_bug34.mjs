/* p3_bug34.mjs — REPRO de BUG #34: el popup de mutación sale DUPLICADO.
 * Rompe una pieza de verdad, gasta el reintento, y CUENTA cuántas veces aparece
 * cada bloque del desenlace en todo el DOM.
 * Run: SIDECAR=http://127.0.0.1:8273 node qa/p3_bug34.mjs
 */
import { webkit } from "playwright";
const BASE = process.env.SIDECAR || "http://127.0.0.1:8273";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const b = await webkit.launch();
const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("  [pageerror]", String(e).slice(0, 300)));
await page.goto(PAGE, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => window.__cuarto && window.__probarPieza, null, { timeout: 30000 });
await page.evaluate(() => { window.__semLatidoInstante = true; });
await sleep(1000);

// pieza LOCAL rota de verdad: `cfd` no levanta su server en esta máquina
await page.evaluate(() => {
  const c = window.__cuarto;
  c.placedTiles().forEach((t) => c.removeTile(t.id));
  c.placeTile({ id: "t-roto", label: "CFD", server: "cfd", belt_ref: "cfd", atom: "tool",
                role: "mesa", auth: "keyless", tools: ["solve"] }, 1, 1);
  window.__renderPieces && window.__renderPieces();
});
await sleep(900);

// dos pruebas: la 1ª deja el rojo, la 2ª GASTA el reintento
for (const i of [1, 2]) {
  await page.evaluate(() => window.__probarPieza("t-roto", { motivo: "manual" }));
  await sleep(700);
  console.log(`  prueba ${i}:`, JSON.stringify(await page.evaluate(() => window.__desenlaces()[0])));
}

const cuenta = async (etiqueta) => page.evaluate((frase) => {
  const hits = [];
  document.querySelectorAll("*").forEach((el) => {
    if (el.children.length) return;                       // sólo hojas: no contar ancestros
    if ((el.textContent || "").trim() === frase) {
      const p = [];
      let n = el;
      while (n && n !== document.body) { p.unshift(n.tagName.toLowerCase() + (n.id ? "#" + n.id : "") + (n.className && typeof n.className === "string" ? "." + n.className.trim().split(/\s+/).join(".") : "")); n = n.parentElement; }
      hits.push(p.slice(-4).join(" > "));
    }
  });
  return hits;
}, etiqueta);

for (const frase of ["Probar el server a mano", "Quitar", "Ver el error completo", "Arreglarlo"]) {
  const h = await cuenta(frase);
  console.log(`\n«${frase}» ×${h.length}`);
  h.forEach((x) => console.log("   ", x));
}

// …y ahora el gesto que lo dispara: tocar [Ver error] del chip mutado
const sem = await page.evaluate(() => {
  const b = document.querySelector('.prow[data-id="t-roto"] .prow-sem .sem-extra')
         || document.querySelector('.prow[data-id="t-roto"] .prow-sem .sem-accion');
  if (!b) return null;
  b.click(); return b.className;
});
console.log("\n— tras tocar el 2º camino del chip (", sem, ") —");
await sleep(500);
for (const frase of ["Probar el server a mano", "Quitar", "Ver el error completo"]) {
  const h = await cuenta(frase);
  console.log(`«${frase}» ×${h.length}`);
  h.forEach((x) => console.log("   ", x));
}
console.log("\nsem-out en el DOM:", await page.evaluate(() => [...document.querySelectorAll(".sem-out")].map((e) => (e.parentElement.className || e.parentElement.id))));
await page.screenshot({ path: "/tmp/p3-bug34.png" });
await b.close();
