/* verify_catalog_equip_ui.mjs — el CABLEADO de UI del carril libre equipar-desde-registro.
 *
 * Backend probado REAL por el done-bar (selftest_catalog_equip.py, 7/7 contra role=client + MCP
 * local stdio). Acá se verifica el WIRING de las dos superficies contra el CONTRATO SSE EXACTO que
 * ese backend emite (stub fiel del contrato ya probado real — mismo patrón stub+real de brandface):
 *
 *   Cuarto:  pick confiable → curación EN VIVO en el HUD → tile REAL colocado (equipResolvedMcp) ·
 *            registry_down → retry honesto, sin tile · no_confiable → honesto, sin tile ·
 *            el carril libre NUNCA pega a /v1/inspect/dispatch (desacoplado del Motor B/forge).
 *   (el carril de Conectar se fue a la sección de Conectores · Obra 4 · qa/verify_seccion.mjs)
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL(".", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8//8/AwAI/AL+X7nBTAAAAABJRU5ErkJggg==", "base64");

const failures = [];
const ok = (v, label, detail = "") => { console.log(`${v ? "  ✓" : "  ✗"} ${label}${!v && detail ? " -> " + detail : ""}`); if (!v) failures.push(label); };

function serve() {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://local");
    if (/favicon|apple-touch-icon/i.test(url.pathname)) { res.writeHead(204); res.end(); return; }
    const file = path.join(DESIGN, decodeURIComponent(url.pathname));
    if (!file.startsWith(DESIGN) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end("nf"); return; }
    res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r(server)));
}

const sse = (frames) => frames.map((f) => `event: ${f.type}\ndata: ${JSON.stringify(f)}\n\n`).join("");

// contrato SSE EXACTO del backend (los mismos frames que catalog_equip_router emite):
const EQUIP_OK = sse([
  { type: "dispatch.iniciado", service: "stripe", server_name: "com.stripe/mcp", free: true },
  { type: "resolver.buscando", service: "stripe" },
  { type: "resolver.encontrado", origin: "registry", server_name: "com.stripe/mcp", vendor_kind: "dns", verified: true, from_cache: false, ranked: [] },
  { type: "curacion.probando", server: "com.stripe/mcp", detail: "arranco el MCP y verifico sus tools" },
  { type: "mcp.equipado", origin: "registry", server: "com.stripe/mcp", tools: ["get_account", "list_charges"], belt_ref: "synth_belts/x/belt.mcp.json", registered: true, tools_detail: [{ name: "get_account", description: "" }, { name: "list_charges", description: "" }] },
  { type: "cerrado", path: "registry", ok: true, encontrado: true, forjado: false, server: "com.stripe/mcp" },
]);
const EQUIP_DOWN = sse([
  { type: "dispatch.iniciado", service: "zzz" }, { type: "resolver.buscando", service: "zzz" },
  { type: "resolver.registry_down", reason: "registro público inalcanzable", retry: true },
  { type: "cerrado", path: "registry_down", ok: false, retry: true, cause: "registry_unreachable" },
]);
const EQUIP_MISS = sse([
  { type: "dispatch.iniciado", service: "evil" }, { type: "resolver.buscando", service: "evil" },
  { type: "resolver.miss", reason: "match de comunidad sin namespace verificado", rejected_impostor: true, ranked: [] },
  { type: "cerrado", path: "miss", ok: false, rejected_impostor: true, premium_available: false, cause: "no_confiable" },
]);

let EQUIP_BODY = EQUIP_OK;     // el test lo cambia por caso
let dispatchHits = 0;          // el carril libre NUNCA debe pegar acá

async function wire(page) {
  const json = (route, v) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(v) });
  // Playwright: la ÚLTIMA ruta registrada que matchea gana → el catch-all va PRIMERO, las
  // específicas DESPUÉS (si no, "**/v1/**" interceptaría /v1/catalog/equip y comería el SSE).
  await page.route("**/v1/**", (route) => json(route, {}));
  await page.route("**/v1/inspect/dispatch", (route) => { dispatchHits++; route.fulfill({ status: 200, contentType: "text/event-stream", body: sse([{ type: "cerrado", path: "x", ok: false }]) }); });
  await page.route("**/v1/catalog/equip", (route) => route.fulfill({ status: 200, contentType: "text/event-stream", body: EQUIP_BODY }));
  await page.route("**/v1/catalog/validate**", (route) => json(route, { service: "stripe", verdict: "confiable", registry_status: "ok", server_name: "com.stripe/mcp", picked_is_trusted: true, message: "confiable" }));
  await page.route("**/v1/catalog/search**", (route) => json(route, {
    items: [{ id: "com.stripe/mcp", name: "Stripe", description: "Pagos y cobros de tu cuenta.", source: "registry", server_name: "com.stripe/mcp", badge: { kind: "official", label: "✓ oficial (com.stripe)", verified: true } }],
    counts: { internal: 0, registry: 1, total: 1 }, registry_status: "ok",
  }));
  await page.route("**/v1/icons**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/v1/icons") return json(route, { known: ["stripe", "github"] });
    return route.fulfill({ status: 200, contentType: "image/png", body: PNG });
  });
  await page.route("**/v1/atoms/catalog**", (route) => json(route, { atoms: [{ id: "arxiv", label: "arXiv", sub: "papers", atom: "tool", zone: "fuentes", auth: "keyless", connector: null, server: "arxiv", tools: ["arxiv_search"], state: "ready" }], total: 1, by_zone: {} }));
  await page.route("**/v1/connectors", (route) => json(route, { connectors: [{ connector: "gmail", auth_method: "oauth", capability_line: "Correo." }], total: 1 }));
  await page.route(/\/v1\/connectors\/[^/]+$/, (route) => json(route, { connector: "gmail", auth_method: "oauth", capability_line: "Correo.", credential_fields: [], steps: [] }));
  await page.route("**/v1/belts/cards**", (route) => json(route, { cards: [], total: 0, servers_real: [], dropped: [] }));
  await page.route("**/v1/users/u1/puppets", (route) => json(route, { puppets: [{ id: "eq-agent", name: "Equip UI", config: { schema_version: "v1", meta: { name: "Equip UI", nicho: "qa" }, model: { primary: "opus", brain_provider: "included", max_turns: 8 }, belt: { belt_refs: [], tool_filters: {} }, framing: { inline: "b" }, rag: { enabled: false }, keys: {}, gates: { money_touch: "needs_ok", send: "needs_ok" }, canvas: { nucleos: [{ model: "included" }], blocks: [], links: [], layout: [] } } }] }));
  await page.route("**/v1/users/u1/keys", (route) => json(route, { keys: [] }));
  await page.route("**/v1/brains/status**", (route) => json(route, { service: { state: "ready" }, providers: {} }));
  await page.route("**/v1/auth/login", (route) => json(route, { id: "u1", session_token: "token-u1", email: "u@x" }));
}

async function newPage(browser, base) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  await ctx.addInitScript(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", email: "u@x", session_token: "token-u1" }));
    localStorage.setItem("puppet_user", JSON.stringify({ id: "u1", email: "u@x", session_token: "token-u1" }));
    localStorage.setItem("aleph-lang", "es"); localStorage.setItem("aleph-theme", "dark");
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/favicon|Failed to load resource|net::ERR/i.test(m.text())) errors.push(m.text()); });
  await wire(page);
  page.__errors = errors; page.__ctx = ctx;
  return page;
}

async function cuartoCase(browser, base, label, body, { expectTile }) {
  EQUIP_BODY = body; dispatchHits = 0;
  const page = await newPage(browser, base);
  try {
    await page.goto(`${base}/cuarto/cuarto.pixi.html?puppet=eq-agent`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__cuarto && window.__cuartoCatalog && window.__renderPieces, null, { timeout: 25000 });
    await page.waitForTimeout(1500);   // dejar que la hidratación de ?puppet= (wipe async) asiente antes de sembrar
    const before = await page.evaluate(() => window.__cuarto.placedTiles().length);
    await page.evaluate(() => window.__cuartoCatalog._doConnect("com.stripe/mcp", "stripe"));
    // esperar el desenlace: tile nuevo (ok) o HUD honesto (fallo)
    await page.waitForFunction((n) => {
      const s = document.getElementById("status");
      return window.__cuarto.placedTiles().length !== n || (s && s.textContent.length > 0);
    }, before, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(600);
    const st = await page.evaluate((n) => ({
      tiles: window.__cuarto.placedTiles().length,
      grew: window.__cuarto.placedTiles().length > n,
      hud: (document.getElementById("status") || {}).textContent || "",
      hasStripeTile: window.__cuarto.placedTiles().some((t) => /stripe/i.test(t.server || t.label || "")),
    }), before);
    if (expectTile) {
      ok(st.grew && st.hasStripeTile, `Cuarto ${label}: tile REAL colocado por el carril libre`, JSON.stringify(st));
      ok(/curando|del catálogo|equipé/i.test(st.hud), `Cuarto ${label}: curación/éxito mostrado en el HUD`, st.hud.slice(0, 80));
    } else {
      ok(!st.grew, `Cuarto ${label}: NO se colocó tile (fallo honesto)`, JSON.stringify(st));
      ok(st.hud.length > 0, `Cuarto ${label}: HUD muestra el fallo tipado`, st.hud.slice(0, 80));
    }
    ok(dispatchHits === 0, `Cuarto ${label}: el carril libre NO pegó a /v1/inspect/dispatch (desacoplado del Motor B)`, `hits=${dispatchHits}`);
    ok(page.__errors.length === 0, `Cuarto ${label}: consola limpia`, page.__errors.slice(0, 3).join(" | "));
  } finally { await page.__ctx.close(); }
}

// [Obra 4] ACÁ ESTABA `conectarCase`, que probaba la puerta vieja de Conectar.dc.html
// (#regGrid → "Curar y equipar"). Esa puerta se enterró: el catálogo público es una sección
// de Conectores. Su testigo —«card del registro con badge de confianza + acción», «curación
// → ✓ equipado»— vive ahora en `qa/verify_seccion.mjs`, marcado [heredado].
//
// Y ya estaba ROTO antes de esta obra: navegaba a `Conectar.dc.html` sin `?catalogo=publico`,
// y el shim del tope del archivo mandaba esa URL a Conectores. Medido sobre main.

const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
try {
  console.log("══ Cuarto: carril libre equipar-desde-registro ══");
  await cuartoCase(browser, base, "confiable", EQUIP_OK, { expectTile: true });
  await cuartoCase(browser, base, "registro-caído", EQUIP_DOWN, { expectTile: false });
  await cuartoCase(browser, base, "no-confiable", EQUIP_MISS, { expectTile: false });
} finally {
  await browser.close();
  await new Promise((r) => server.close(r));
}
console.log(failures.length ? `\n✗ ${failures.length} fallo(s) de UI` : "\n✓ verify_catalog_equip_ui: all green");
process.exit(failures.length ? 1 : 0);
