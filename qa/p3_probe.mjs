/* p3_probe.mjs — sonda de trabajo de FIX-P3 (no es la vara: es el microscopio).
 * Abre el Cuarto en WebKit, siembra piezas y devuelve lo que se le pida.
 * Run: SIDECAR=http://127.0.0.1:8273 node qa/p3_probe.mjs [shot]
 */
import { webkit } from "playwright";
const BASE = process.env.SIDECAR || "http://127.0.0.1:8273";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const b = await webkit.launch();
const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => { if (m.type() === "error") console.log("  [console]", m.text().slice(0, 200)); });
page.on("pageerror", (e) => console.log("  [pageerror]", String(e).slice(0, 300)));
await page.goto(PAGE, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => window.__cuarto && window.__openAbanico, null, { timeout: 30000 });
await sleep(1200);

const SEED = [
  { id: "t-gh", label: "GitHub", server: "github", atom: "tool", role: "mesa",
    connector: "github", tools: ["create_issue", "list_repos"], gx: 1, gy: 1 },
  { id: "t-solo", label: "Dicom", server: "orthanc", atom: "tool", role: "fuentes",
    tools: ["find_study", "get_series"], gx: -2, gy: 0 },
];
await page.evaluate((seed) => {
  const c = window.__cuarto;
  c.placedTiles().forEach((t) => c.removeTile(t.id));
  for (const s of seed) c.placeTile(s, s.gx, s.gy);
  window.__renderPieces && window.__renderPieces();
}, SEED);
await sleep(900);

await page.evaluate(() => window.__openAbanico(window.__cuarto.pieceData("t-gh")));
await sleep(600);
console.log("ARCO:", JSON.stringify(await page.evaluate(() => window.__abanicoArco()), null, 1));
console.log("ACTS:", JSON.stringify(await page.evaluate(() => window.__abanicoActs())));
console.log("tocaAfuera gh:", await page.evaluate(() => window.__tocaAfuera("t-gh")),
            "· dicom:", await page.evaluate(() => window.__tocaAfuera("t-solo")));

if (process.argv[2] === "shot") {
  await page.screenshot({ path: "/tmp/p3-arco.png" });
  console.log("→ /tmp/p3-arco.png");
}
await b.close();
