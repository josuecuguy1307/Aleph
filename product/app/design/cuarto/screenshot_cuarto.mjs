/* screenshot_cuarto.mjs — headless verification (dev tool, not shipped).
 * Targets the live Aleph dev server (:8091, which proxies /v1 → :8080), so the
 * recipe is validated by the REAL backend. Exercises: idle, drag→drop→place,
 * live serialize+validate, rehydrate round-trip, and persists a real puppet.
 * Run (serve.py + :8080 must be up):  node screenshot_cuarto.mjs
 */
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const OUT = join(fileURLToPath(new URL(".", import.meta.url)), "screenshots");
const BASE = process.env.ALEPH_BASE || "http://localhost:8091";
const PAGE_URL = BASE + "/cuarto/cuarto.pixi.html";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 820 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

await page.goto(PAGE_URL, { waitUntil: "load" });
await page.waitForFunction(() => window.__cuarto, null, { timeout: 8000 });
const stage = await page.$("#stage");
const shot = (name) => page.screenshot({ path: join(OUT, name) });

await page.waitForTimeout(400);
await shot("01-idle.png");

const cellClient = (gx, gy) => page.evaluate(({ gx, gy }) => {
  const c = window.__cuarto, g = c.scene.grid, o = c.origin;
  const r = c.app.canvas.getBoundingClientRect();
  return { x: r.left + (gx - gy) * (g.tileWidth / 2) + o.x,
           y: r.top + (gx + gy) * (g.tileHeight / 2) + o.y };
}, { gx, gy });

// real drag: "Buscar web" chip → Fuentes cell (2,4)
const chip = await page.$('.chip[data-tool="buscar_web"]');
const cb = await chip.boundingBox();
const tgt = await cellClient(2, 4);
await page.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2);
await page.mouse.down();
await page.mouse.move(tgt.x, tgt.y, { steps: 12 });
await page.waitForTimeout(200);
await shot("02-drag-ghost.png");
await page.mouse.up();
await page.waitForTimeout(350);

// fill the rest programmatically (process→mesa, write→entrega)
await page.evaluate(() => {
  const c = window.__cuarto;
  c.placeTile({ id: "redactar-1", key: "redactar", label: "Convertir / redactar", category: "process" }, 4, 3);
  c.placeTile({ id: "guardar-1", key: "guardar", label: "Guardar archivo", category: "write" }, 6, 5);
  window.__sync();
});
// wait for the backend validation badge to turn green
await page.waitForFunction(() => document.getElementById("badge").textContent.includes("✓"), null, { timeout: 8000 })
  .catch(() => {});
await page.mouse.move(20, 20);
await page.waitForTimeout(600);
await shot("03-recipe-valid.png");

const recipe = await page.evaluate(() => JSON.parse(document.getElementById("recipe").textContent));
const cellsBefore = await page.evaluate(() =>
  window.__cuarto.placedTiles().map((t) => `${t.key}@${t.gridX},${t.gridY}`).sort());
const badge = await page.$eval("#badge", (el) => el.textContent);

// ▶ Correr → REAL run; eco driven by live tool_call events from /spaces SSE
// [Cuarto entrega, no corre] el Cuarto ya no tiene botón de Ejecutar: correr es de La Sala.
  // El PIPELINE quedó intacto y sigue siendo lo que esta vara prueba — se dispara por código.
  await page.evaluate(() => window.__ejecutarTurno());
await page.waitForFunction(() => window.__cuarto && !window.__cuarto.running, null, { timeout: 60000 }).catch(() => {});
await shot("04-after-run.png");
const ecoTools = await page.evaluate(() => window.__ecoTools ?? null);
const ecoReal = await page.evaluate(() => !!window.__lastRun);

// full-loop visual (inferred) for the token/link screenshot
await page.evaluate(() => window.__cuarto.playEco());
await page.waitForTimeout(520);
await shot("05-eco-loop.png");
await page.waitForFunction(() => !window.__cuarto.running, null, { timeout: 12000 }).catch(() => {});

// rehydrate round-trip
await page.click("#rehydr");
await page.waitForTimeout(700);
await shot("06-rehydrated.png");
const cellsAfter = await page.evaluate(() =>
  window.__cuarto.placedTiles().map((t) => `${t.key}@${t.gridX},${t.gridY}`).sort());

await browser.close();

// ── independent persistence proof: save a real puppet via the proxy ──────────
// Off by default so the test doesn't leave rows in the DB. Run with CUARTO_PERSIST=1
// to re-verify that config.canvas (gridX/gridY) round-trips through puppets.config.
let persist = "skipped (set CUARTO_PERSIST=1 to verify DB persistence)";
if (process.env.CUARTO_PERSIST) try {
  const login = await (await fetch(BASE + "/v1/auth/login", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "cuarto-pixi@dev.local" }) })).json();
  const auth = { "Content-Type": "application/json", "Authorization": "Bearer " + login.session_token };
  const created = await (await fetch(BASE + "/v1/puppets", { method: "POST", headers: auth,
    body: JSON.stringify({ owner_id: login.id, name: recipe.meta.name, nicho: recipe.meta.nicho, config: recipe }) })).json();
  const list = await (await fetch(BASE + "/v1/users/" + login.id + "/puppets", { headers: auth })).json();
  const arr = Array.isArray(list) ? list : (list.puppets || []);
  const got = arr.find((x) => x.id === created.id);
  const blk = got?.config?.canvas?.blocks?.find((b) => b.gridX != null);
  persist = `puppet ${created.id?.slice(0, 8)} · canvas.block gridX=${blk?.gridX},gridY=${blk?.gridY}`;
} catch (e) { persist = "FAILED: " + e.message; }

console.log("badge        :", badge);
console.log("belt.belt_refs:", JSON.stringify(recipe.belt?.belt_refs));
console.log("tool_filters :", JSON.stringify(recipe.belt?.tool_filters));
console.log("roundtrip    :", JSON.stringify(cellsBefore) === JSON.stringify(cellsAfter) ? "STABLE " + JSON.stringify(cellsAfter) : `DRIFT ${JSON.stringify(cellsBefore)} -> ${JSON.stringify(cellsAfter)}`);
console.log("eco live     :", `tool_calls from real run = ${ecoTools}; run record = ${ecoReal ? "yes" : "no"}`);
console.log("persistence  :", persist);
console.log(errors.length ? "PAGE ERRORS:\n" + errors.join("\n") : "OK — no page errors");
