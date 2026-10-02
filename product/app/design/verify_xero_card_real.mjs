/* verify_xero_card_real.mjs — LLAVE A REAL de la card de Xero post-cierre.
 * Sin stubs: hace login real contra :8130, proxya TODO /v1 al backend vivo,
 * inyecta la sesión real y mira si la card de Xero muestra "Conectado" leyendo
 * el vault de verdad (GET /v1/users/{id}/keys con Bearer real).
 *   node product/app/design/verify_xero_card_real.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
const BACKEND = "http://127.0.0.1:8130";
const DESIGN = new URL(".", import.meta.url).pathname;
const SHOTS = new URL("./cuarto/screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp" };

// 1) login real → sesión
const login = await fetch(BACKEND + "/v1/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: "caso2-owner@aleph.test", password: "caso2-hypergod-2026" }) });
const sess = await login.json();
if (!sess.id || !sess.session_token) { console.error("login FAIL", sess); process.exit(1); }
console.log("login OK id", sess.id);

// 2) server: estáticos de design/ + PROXY /v1 → backend vivo (pasa headers, incl. Authorization)
const srv = http.createServer(async (req, r) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname.startsWith("/v1")) {
    const chunks = []; for await (const c of req) chunks.push(c);
    const body = chunks.length ? Buffer.concat(chunks) : undefined;
    const headers = { ...req.headers }; delete headers.host; delete headers["content-length"];
    const resp = await fetch(BACKEND + req.url, { method: req.method, headers, body: (req.method === "GET" || req.method === "HEAD") ? undefined : body });
    const buf = Buffer.from(await resp.arrayBuffer());
    r.writeHead(resp.status, { "Content-Type": resp.headers.get("content-type") || "application/json" });
    r.end(buf); return;
  }
  const p = path.join(DESIGN, decodeURIComponent(u.pathname));
  if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
  r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(r);
});
await new Promise((res) => srv.listen(0, "127.0.0.1", res));
const base = "http://127.0.0.1:" + srv.address().port;

const browser = await chromium.launch();
fs.mkdirSync(SHOTS, { recursive: true });
const ctx = await browser.newContext({ viewport: { width: 1100, height: 820 } });
const S = JSON.stringify({ id: sess.id, session_token: sess.session_token });
await ctx.addInitScript((s) => { try { sessionStorage.setItem("puppet_user", s); } catch {} }, S);
const page = await ctx.newPage();
const apiCalls = [];
page.on("response", (resp) => { const url = resp.url(); if (url.includes("/v1/")) apiCalls.push(resp.status() + " " + url.replace(base, "")); });
await page.goto(base + "/Conectar.dc.html", { waitUntil: "domcontentloaded" });
await page.waitForSelector("#grid .card", { timeout: 12000 }).catch(() => {});
await page.waitForTimeout(900);

const xeroCard = await page.evaluate(() => {
  const cards = [...document.querySelectorAll("#grid .card")];
  const c = cards.find((el) => /xero/i.test(el.querySelector(".nm")?.textContent || ""));
  if (!c) return { found: false, ncards: cards.length };
  return { found: true, text: c.textContent.replace(/\s+/g, " ").trim(),
           shows_connected: /conectad/i.test(c.textContent),
           has_manage: /gestionar/i.test(c.textContent),
           has_connect_btn: /conectar/i.test([...c.querySelectorAll("button")].map(b=>b.textContent).join(" ")) };
});
console.log("api /v1 calls:", JSON.stringify(apiCalls));
console.log("xero card (REAL vault):", JSON.stringify(xeroCard));
// scroll la card de Xero al viewport y capturar ESE pixel (element screenshot)
const cardHandle = await page.evaluateHandle(() => {
  const c = [...document.querySelectorAll("#grid .card")].find((el) => /xero/i.test(el.querySelector(".nm")?.textContent || ""));
  if (c) c.scrollIntoView({ block: "center" });
  return c;
});
await page.waitForTimeout(400);
const shot = SHOTS + "caso2-2b-xero-card-real.png";
await cardHandle.asElement()?.screenshot({ path: shot }).catch(async () => { await page.screenshot({ path: shot }); });
console.log("screenshot:", shot);
await browser.close(); srv.close();
console.log(xeroCard.found && xeroCard.shows_connected && !xeroCard.has_connect_btn ? "LLAVE_A_REAL: PASS" : "LLAVE_A_REAL: FAIL");
