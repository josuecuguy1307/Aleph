/* verify_2c_bioacustica.mjs — LLAVE A del hilo 2C (head-start): el espectrograma REAL de
 * scikit-maad (obra capturada del run b5917c7b, spinetail.wav) se RINDE en La Sala real.
 *
 * Página REAL (sala.html) + renderer REAL (render.js) — el mismo código que ve el usuario.
 * El backend se stubea SÓLO como transporte: devuelve como out.obra el fixture
 * spinetail.fieldplot.json, que ES la obra real capturada del backend vivo (Llave B, run
 * b5917c7b, 128×64, ACI 723.3953). Llave A prueba que esa obra real se hace VISIBLE como
 * heatmap; Llave B (aparte) ya probó que el backend la produjo de verdad.
 *
 *   node product/app/design/sala/verify_2c_bioacustica.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;
const FIX = new URL("./fixtures/", import.meta.url).pathname;
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };

function serveDesign() {
  return new Promise((res) => {
    const srv = http.createServer((req, r) => {
      const p = path.join(DESIGN, decodeURIComponent(new URL(req.url, "http://x").pathname));
      if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
      r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
      fs.createReadStream(p).pipe(r);
    });
    srv.listen(0, "127.0.0.1", () => res(srv));
  });
}

function routesFor(obra) {
  const out = { ok: true, run_id: "b5917c7b-real-obra", answer: "Analicé spinetail.wav: ACI 723.3953. Espectrograma abajo.",
    record: { tool_calls: [], model_final: "claude-code-opus-4.8", degraded: null }, outputs_captured: [], held_actions: [], obra };
  return [
    { url: "**/v1/classify-turn", handler: (r) => r.fulfill({ json: { turn: "obra" } }) },
    { url: "**/v1/artifacts/classify-action", handler: (r) => r.fulfill({ json: { action: "new" } }) },
    { url: "**/v1/puppets/run", handler: (r) => r.fulfill({ json: out }) },
    { url: "**/v1/sessions/**", handler: (r) => r.request().method() === "GET" ? r.fulfill({ json: { artifacts: [] } }) : r.fulfill({ json: { id: "a-fx" } }) },
    { url: "**/v1/users/**", handler: (r) => r.fulfill({ json: { puppets: [], keys: [], docs: [] } }) },
    { url: "**/v1/obra-caption", handler: (r) => r.fulfill({ json: {} }) },
    { url: "**/v1/belts/**", handler: (r) => r.fulfill({ json: { cards: [] } }) },
    { url: "**/v1/chats", handler: (r) => r.fulfill({ json: { chats: [] } }) },
    { url: "**/v1/spaces/**/stream", handler: (r) => r.fulfill({ status: 200, contentType: "text/event-stream", body: "" }) },
    { url: "**/v1/spaces/**", handler: (r) => r.fulfill({ json: { id: "sala-gen", artifacts: [] } }) },
  ];
}

const srv = await serveDesign();
const base = "http://127.0.0.1:" + srv.address().port;
const browser = await chromium.launch();
fs.mkdirSync(SHOTS, { recursive: true });
const obra = JSON.parse(fs.readFileSync(FIX + "spinetail.fieldplot.json", "utf8"));

const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, reducedMotion: "reduce" });
await ctx.addInitScript(() => {
  try {
    if (window.top !== window) return;
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "caso2-user", session_token: "fx-token" }));
    localStorage.setItem("aleph-lang", "es");
  } catch {}
});
const page = await ctx.newPage();
const consoleErrors = [];
const notFound = [];
page.on("response", (resp) => { if (resp.status() === 404) notFound.push(resp.url().replace(base, "")); });
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
page.on("pageerror", (e) => consoleErrors.push(String(e)));
for (const r of routesFor(obra)) await page.route(r.url, r.handler);

await page.goto(base + "/sala/sala.html", { waitUntil: "domcontentloaded" });
await page.waitForSelector("#composer", { timeout: 15000 });
await page.fill("#composer", "Analizá spinetail.wav y mostrame el espectrograma");
await page.press("#composer", "Enter");
await page.waitForFunction(() => {
  const send = document.getElementById("send"), badge = document.getElementById("bbadge");
  return send && !send.disabled && (!badge || badge.style.display === "none");
}, { timeout: 20000 }).catch(() => {});
await page.waitForFunction(() => /sala-rich-fieldplot/.test((document.getElementById("canvas") || {}).className || ""), { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(500);

const st = await page.evaluate(() => ({
  cls: document.getElementById("canvas").className,
  canvas: !!document.querySelector("#canvas .ar-field-canvas"),
  fieldNode: !!document.querySelector("#canvas .aleph-render"),
}));
console.log("404s:", notFound.length ? notFound.join(", ") : "(none)");
const errs = consoleErrors.filter((t) => !/favicon/i.test(t));
const checks = [
  ["canvas → sala-rich-fieldplot", /sala-rich-fieldplot/.test(st.cls), st.cls],
  ["heatmap real en canvas (.ar-field-canvas)", st.canvas, JSON.stringify(st)],
  ["consola limpia", errs.length === 0, errs.slice(0, 2).join(" | ")],
];
for (const [n, ok, d] of checks) console.log((ok ? "  ✓ " : "  ✗ ") + n + (ok || !d ? "" : "  → " + d));

const shot = SHOTS + "caso2-2c-spinetail-espectrograma.png";
await page.screenshot({ path: shot });
console.log("screenshot:", shot);
const pass = checks.every((c) => c[1]);
await ctx.close(); await browser.close(); srv.close();
console.log(pass ? "\n✓ LLAVE A 2C VERDE — espectrograma real visible en La Sala" : "\n✗ LLAVE A 2C ROJA");
process.exit(pass ? 0 : 1);
