/* verify_xero_card.mjs — LLAVE A del estado post-cierre de la card de conector (Xero).
 * Carga Conectar.dc.html REAL, con el user teniendo la key 'xero' guardada, y mira si la
 * card muestra "Conectado" (persistente desde las keys) o revierte a "Conectar" (false-negative).
 *   node product/app/design/verify_xero_card.mjs [before|after]
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
const TAG = process.argv[2] || "after";
const DESIGN = new URL(".", import.meta.url).pathname;
const SHOTS = new URL("./cuarto/screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const srv = http.createServer((req, r) => {
  const p = path.join(DESIGN, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
  r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(r);
});
await new Promise((res) => srv.listen(0, "127.0.0.1", res));
const base = "http://127.0.0.1:" + srv.address().port;
const browser = await chromium.launch();
fs.mkdirSync(SHOTS, { recursive: true });
const ctx = await browser.newContext({ viewport: { width: 1100, height: 780 } });
await ctx.addInitScript(() => {
  try { sessionStorage.setItem("puppet_user", JSON.stringify({ id: "6b558dd2-f315-4f56-b476-b16b4804f7fe", session_token: "fx-token" })); } catch {}
});
const page = await ctx.newPage();
// backend stub: lista incluye xero (oauth); el user YA tiene la key 'xero' guardada.
await page.route("**/v1/connectors", (r) => r.fulfill({ json: { connectors: [
  { connector: "xero", auth_method: "oauth", tier: "good", capability_line: "Registros societarios/financieros de tu Xero." },
  { connector: "gmail", auth_method: "oauth", tier: "good", capability_line: "Borradores y lectura de tu correo." },
] } }));
await page.route("**/v1/users/**/keys", (r) => r.fulfill({ json: { keys: [{ provider: "xero", last4: "jpOA" }] } }));
await page.route("**/v1/connectors/xero", (r) => r.fulfill({ json: { connector: "xero", auth_method: "oauth", capability_line: "Xero" } }));
await page.route("**/v1/auth/login", (r) => r.fulfill({ json: { id: "6b558dd2-f315-4f56-b476-b16b4804f7fe", session_token: "fx-token" } }));
await page.goto(base + "/Conectar.dc.html", { waitUntil: "domcontentloaded" });
await page.waitForSelector("#grid .card", { timeout: 10000 }).catch(() => {});
await page.waitForTimeout(600);
// leer el estado textual de la card de xero
const xeroCard = await page.evaluate(() => {
  const cards = [...document.querySelectorAll("#grid .card")];
  const c = cards.find((el) => /xero/i.test(el.querySelector(".nm")?.textContent || ""));
  if (!c) return { found: false };
  return { found: true, text: c.textContent.replace(/\s+/g, " ").trim(),
           shows_connected: /conectad/i.test(c.textContent), shows_connect_btn: !!c.querySelector("button") };
});
console.log(`[${TAG}] xero card:`, JSON.stringify(xeroCard));
const shot = SHOTS + `caso2-2b-xero-card-${TAG}.png`;
await page.screenshot({ path: shot });
console.log("screenshot:", shot);
await browser.close(); srv.close();
