/* p3_candado.mjs — sonda de trabajo del §4: UNO por pieza, pegado al cable, sólo si toca afuera.
 * Run: SIDECAR=http://127.0.0.1:8273 node qa/p3_candado.mjs [shot]
 */
import { webkit } from "playwright";
const BASE = process.env.SIDECAR || "http://127.0.0.1:8273";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await webkit.launch();
const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("  [pageerror]", String(e).slice(0, 300)));
await page.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => window.__cuarto && window.__openCandado, null, { timeout: 30000 });
await sleep(1000);

const SEED = [
  { id: "mix", label: "correo", category: "write", server: "svc-mailer", tools: ["send_mail", "get_price"], gx: 1, gy: 1 },
  { id: "lec", label: "lector", category: "read", server: "svc-reader", tools: ["get_price", "list_files"], gx: 3, gy: 1 },
  { id: "pla", label: "banco", category: "write", server: "svc-bank", tools: ["transfer_funds"], gx: 5, gy: 1 },
];
await page.evaluate((seed) => {
  const c = window.__cuarto;
  c.placedTiles().forEach((t) => c.removeTile(t.id));
  for (const s of seed) c.placeTile(s, s.gx, s.gy);
  window.__sync();
}, SEED);
await page.waitForFunction(() => window.__cuarto.lidLock("mix") !== null, null, { timeout: 15000 }).catch(() => console.log("  (timeout esperando advisor)"));
await sleep(600);

const est = await page.evaluate(() => ({
  mix: window.__cuarto.lidLock("mix"), lec: window.__cuarto.lidLock("lec"), pla: window.__cuarto.lidLock("pla"),
  candados: window.__cuarto.candados(),
  detalle: window.__cuarto.candados().map((id) => ({ id, ...window.__cuarto.candado(id) })),
  ghosts: window.__cuarto.advisorGhosts(),
}));
console.log("ESTADOS:", JSON.stringify(est, null, 1));

// popup: solo-lectura no lo abre; el que toca afuera sí
const soloLee = await page.evaluate(() => { window.__openCandado(window.__cuarto.pieceData("lec")); return window.__candado(); });
console.log("popup sobre solo-lectura:", JSON.stringify(soloLee));
const tocaAf = await page.evaluate(() => { window.__openCandado(window.__cuarto.pieceData("mix")); return window.__candado(); });
console.log("popup sobre mix:", JSON.stringify(tocaAf));
const quitado = await page.evaluate(() => {
  document.querySelector('#cdReglas .cd-r[data-regla="auto"]').click();
  return window.__candado();
});
console.log("tras [Quitar]:", JSON.stringify(quitado));
console.log("arco de lec (¿ofrece Asegurar?):", await page.evaluate(() => {
  window.__openCandado && window.__openAbanico(window.__cuarto.pieceData("lec"));
  return window.__abanicoActs().map((a) => a.act);
}));
if (process.argv[2] === "shot") {
  await page.evaluate(() => { window.__closeAbanico(); document.getElementById("candado").hidden = true; window.__cuarto.cam.fit(); });
  await sleep(500);
  await page.screenshot({ path: "/tmp/p3-candado.png" });
  console.log("→ /tmp/p3-candado.png");
}
await b.close();
