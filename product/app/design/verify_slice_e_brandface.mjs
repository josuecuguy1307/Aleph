/* Slice E browser regression: shared Brandface identity across Cuarto, Sala and Conectar.
 *
 * Dos carriles:
 *  - STUB (default): matriz determinista con el catálogo de capacidades stubbeado en la
 *    FUENTE NUEVA del grid (/v1/atoms/catalog + /v1/connectors vía cuarto.catalog.js,
 *    post 6d805c4). Contrato: logo real curado, fallback iniciales, estado Conectado/Parcial
 *    sobrevive, modal comparte la cara.
 *  - REAL (ALEPH_SIDECAR_BIN=<binario> o ALEPH_BASE=<url>): sirve el design/ del ÁRBOL y
 *    proxya /v1 al sidecar real (client role, datadir aislado). Exige caras de marca VIVAS
 *    en el grid completo — el carril que caza el bug "73 cards / 0 caras" de la .app.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "../../../qa/lib/frozen_guard.mjs";
import http from "node:http";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const DESIGN = new URL(".", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8//8/AwAI/AL+X7nBTAAAAABJRU5ErkJggg==", "base64");
const KNOWN = ["arxiv", "github", "github-ro", "gmail", "xero", "zotero"];
// La fuente PRIMARIA del grid: /v1/atoms/catalog (cuarto.catalog.js los normaliza).
const ATOMS = [
  { id: "github", label: "GitHub", sub: "Repos, issues y PRs de tu cuenta.", atom: "tool", zone: "fuentes",
    auth: "personal_token", connector: "github", server: "github", tools: ["gh_issues", "gh_prs"], state: "connectable", armario: "apps" },
  { id: "arxiv", label: "arXiv", sub: "Papers académicos al alcance.", atom: "tool", zone: "fuentes",
    auth: "keyless", connector: null, server: "arxiv", tools: ["arxiv_search"], state: "ready", armario: "mundo" },
];
// /v1/connectors complementa con conectores SIN pieza de catálogo (github queda absorbido por su átomo).
const CONNECTORS = [
  { connector: "github", auth_method: "personal_token", tier: "good", capability_line: "Repositorios y commits." },
  { connector: "gmail", auth_method: "oauth", tier: "good", capability_line: "Borradores y lectura de correo." },
  { connector: "xero", auth_method: "oauth", tier: "good", capability_line: "Registros financieros." },
  { connector: "custom_local", auth_method: "keyless", tier: "internal", capability_line: "Conector local de prueba." },
];
const BELT_CARDS = [
  { id: "legacy-github-card", label: "GitHub", sub: "repos", tools: ["issues"], state: "ready", connector: "github" },
  { id: "custom-card", label: "Custom Local", sub: "sin logo curado", tools: ["run"], state: "ready", connector: "custom_local" },
];
const RECIPE = {
  schema_version: "v1",
  meta: { name: "Brandface Slice E", nicho: "qa" },
  model: { primary: "opus", brain_provider: "included", max_turns: 8 },
  belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json", tool_filters: {} },
  framing: { inline: "Responde breve." },
  rag: { enabled: false },
  keys: {},
  gates: { money_touch: "needs_ok", send: "needs_ok" },
  canvas: { nucleos: [{ model: "included" }], blocks: [], links: [], layout: [] },
};

const failures = [];
const ok = (value, label, detail = "") => {
  console.log(`${value ? "  ✓" : "  ✗"} ${label}${!value && detail ? " -> " + detail : ""}`);
  if (!value) failures.push(label);
};

/** Un wait que tira NO mata la corrida (fallo visible, resumen siempre). Reintenta el leg
 *  entero una vez — flake de Pixi/WebGL bajo la matriz larga; un rojo determinista sigue
 *  rojo. Los ✗ parciales del intento crashado se descartan (el retry los re-mide todos). */
async function attempt(label, fn, tries = 2) {
  for (let i = 1; i <= tries; i++) {
    const mark = failures.length;
    try { return await fn(); }
    catch (e) {
      failures.length = mark;
      console.log(`  ↻ ${label}: intento ${i} crashed (${String(e).split("\n")[0].slice(0, 110)})${i < tries ? " — reintento" : ""}`);
      if (i === tries) failures.push(`${label}: crashed tras ${tries} intentos`);
    }
  }
}

/** Static server del design/. Con proxyTarget, /v1 y /health se proxyan al sidecar REAL. */
function serve(proxyTarget = "") {
  const server = http.createServer((req, response) => {
    const url = new URL(req.url, "http://local");
    if (proxyTarget && (url.pathname.startsWith("/v1") || url.pathname === "/health")) {
      const target = new URL(url.pathname + url.search, proxyTarget);
      const up = http.request(target, { method: req.method, headers: { ...req.headers, host: target.host } }, (r2) => {
        response.writeHead(r2.statusCode || 502, r2.headers);
        r2.pipe(response);
      });
      up.on("error", () => { response.writeHead(502); response.end("proxy"); });
      req.pipe(up);
      return;
    }
    if (/favicon|apple-touch-icon/i.test(url.pathname)) { response.writeHead(204); response.end(); return; }
    const file = path.join(DESIGN, decodeURIComponent(url.pathname));
    if (!file.startsWith(DESIGN) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      response.writeHead(404); response.end("nf"); return;
    }
    response.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(response);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

async function wire(page) {
  const json = (route, value) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
  await page.route("**/v1/**", (route) => json(route, {}));
  await page.route("**/v1/icons**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/v1/icons") return json(route, { known: KNOWN });
    const slug = decodeURIComponent(url.pathname.replace(/^\/v1\/icons\//, ""));
    if (slug === "xero") return route.fulfill({ status: 404, body: "" });
    if (KNOWN.includes(slug)) return route.fulfill({ status: 200, contentType: "image/png", body: PNG });
    return route.fulfill({ status: 404, body: "" });
  });
  await page.route("**/v1/atoms/catalog**", (route) => json(route, { atoms: ATOMS, total: ATOMS.length, by_zone: {} }));
  await page.route("**/v1/connectors", (route) => json(route, { connectors: CONNECTORS, total: CONNECTORS.length }));
  await page.route(/\/v1\/connectors\/[^/]+$/, (route) => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split("/").pop() || "");
    const c = CONNECTORS.find((item) => item.connector === name) || { connector: name, auth_method: "keyless", capability_line: name };
    json(route, { ...c, credential_fields: [{ id: "token", label: "Token", secret: true, shape: "tok_..." }], steps: [{ txt: "Crea tu llave" }] });
  });
  await page.route("**/v1/users/u1/keys", (route) => json(route, {
    keys: [{ provider: "xero", last4: "xero" }, { provider: "gmail__oauth_partial" }],
  }));
  await page.route("**/v1/brains/status**", (route) => json(route, {
    service: { state: "ready", mode: "managed", managed: true },
    providers: {
      included: { provider: "included", state: "ready", detail: "ok" },
      claude_cli: { provider: "claude_cli", state: "ready", detail: "ok" },
      codex_cli: { provider: "codex_cli", state: "ready", detail: "ok" },
    },
  }));
  await page.route("**/v1/belts/cards**", (route) => json(route, { cards: BELT_CARDS, total: BELT_CARDS.length, servers_real: [], dropped: [] }));
  await page.route("**/v1/users/u1/puppets", (route) => json(route, { puppets: [{ id: "brandface-agent", name: "Brandface Slice E", config: RECIPE }] }));
  await page.route("**/v1/auth/login", (route) => json(route, { id: "u1", session_token: "token-u1", email: "u@x" }));
  await page.route("**/v1/users/u1/rag/**", (route) => json(route, { docs: [] }));
  await page.route("**/v1/sessions/**", (route) => json(route, { artifacts: [] }));
  await page.route("**/v1/chats**", (route) => json(route, { chats: [], total: 0, messages: [] }));
  await page.route("**/v1/payments/status", (route) => json(route, { ok: true }));
}

async function newPage(browser, base, width, theme, { stub = true } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 840 }, reducedMotion: "reduce" });
  if (stub) {
    await context.addInitScript(({ theme }) => {
      sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", email: "u@x", session_token: "token-u1" }));
      localStorage.setItem("aleph-lang", "es");
      localStorage.setItem("aleph-theme", theme);
    }, { theme });
  }
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error" && !/favicon|Failed to load resource|net::ERR/i.test(message.text())) errors.push(message.text());
  });
  if (stub) await wire(page);
  page.__errors = errors;
  page.__context = context;
  page.__base = base;
  return page;
}

async function assertNoOverflow(page, label) {
  const layout = await page.evaluate(() => ({
    horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
    bodyOverflow: document.body.scrollWidth > innerWidth + 1,
  }));
  ok(!layout.horizontalOverflow && !layout.bodyOverflow, `${label}: no horizontal overflow`, JSON.stringify(layout));
}

async function checkConectar(browser, base, width, theme) {
  const page = await newPage(browser, base, width, theme);
  try {
    await page.goto(`${base}/Conectar.dc.html`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#grid .card", { timeout: 15000 });
    await page.waitForFunction(() => window.AlephBrand && window.AlephBrand._known() !== null, null, { timeout: 15000 });
    await page.waitForFunction(() => {
      const cards = [...document.querySelectorAll("#grid .card")];
      const github = cards.find((card) => /github/i.test(card.textContent || ""));
      const xero = cards.find((card) => /xero/i.test(card.textContent || ""));
      return github && github.querySelector(".bface img") && xero && xero.querySelector(".bface.binit");
    }, null, { timeout: 10000 });
    const cards = await page.evaluate(() => {
      const out = {};
      for (const card of document.querySelectorAll("#grid .card")) {
        const name = (card.querySelector(".nm")?.textContent?.trim() || "").toLowerCase().replace(/\s+/g, "_");
        out[name] = {
          img: !!card.querySelector(".top .bface img"),
          init: !!card.querySelector(".top .bface.binit"),
          text: card.textContent.replace(/\s+/g, " ").trim(),
          broken: [...card.querySelectorAll("img")].some((img) => img.complete && img.naturalWidth === 0),
        };
      }
      return out;
    });
    ok(cards.github?.img && !cards.github?.broken, `Conectar ${theme} ${width}: GitHub uses shared logo face`, JSON.stringify(cards.github));
    ok(cards.arxiv?.img, `Conectar ${theme} ${width}: public MCP atom gets logo via server slug`, JSON.stringify(cards.arxiv));
    ok(cards.xero?.init && /Conectado/.test(cards.xero.text), `Conectar ${theme} ${width}: failed Xero icon falls back and keeps state`, JSON.stringify(cards.xero));
    ok(cards.gmail?.img && /Parcial/.test(cards.gmail.text), `Conectar ${theme} ${width}: partial state survives Brandface`, JSON.stringify(cards.gmail));
    ok(cards.custom_local?.init, `Conectar ${theme} ${width}: unknown connector uses deterministic initials`, JSON.stringify(cards.custom_local));
    await page.click("#grid .card:has-text('github') button");
    await page.waitForSelector("#modal .mhead .bface img", { timeout: 10000 });
    await assertNoOverflow(page, `Conectar ${theme} ${width}`);
    await page.screenshot({ path: `/tmp/aleph-slice-e-conectar-${theme}-${width}.png`, fullPage: true });
    ok(page.__errors.length === 0, `Conectar ${theme} ${width}: console clean`, page.__errors.slice(0, 3).join(" | "));
  } finally {
    await page.__context.close();
  }
}

async function checkSala(browser, base, width, theme) {
  const page = await newPage(browser, base, width, theme);
  try {
    await page.goto(`${base}/sala/sala.html?puppet=brandface-agent`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.AlephBrand && window.AlephBrand._known() !== null, null, { timeout: 15000 });
    const contract = await page.evaluate(() => ({
      sameUrl: window.AlephBrand.url({ server: "legacy-github-card", connector: "github", label: "GitHub" }),
      known: window.AlephBrand.has({ server: "legacy-github-card", connector: "github" }),
      html: window.AlephBrand.faceHTML({ server: "legacy-github-card", connector: "github", label: "GitHub" }),
      fallback: window.AlephBrand.faceHTML({ connector: "custom_local", label: "Custom Local" }),
    }));
    ok(contract.known && contract.sameUrl === "/v1/icons/github" && /\/v1\/icons\/github/.test(contract.html),
      `Sala ${theme} ${width}: connector identity wins over legacy server id`, JSON.stringify(contract));
    ok(/binit/.test(contract.fallback), `Sala ${theme} ${width}: fallback initials available`);
    await assertNoOverflow(page, `Sala ${theme} ${width}`);
    await page.screenshot({ path: `/tmp/aleph-slice-e-sala-${theme}-${width}.png`, fullPage: true });
    ok(page.__errors.length === 0, `Sala ${theme} ${width}: console clean`, page.__errors.slice(0, 3).join(" | "));
  } finally {
    await page.__context.close();
  }
}

async function checkCuarto(browser, base, width, theme) {
  const page = await newPage(browser, base, width, theme);
  try {
    await page.goto(`${base}/cuarto/cuarto.pixi.html?puppet=brandface-agent`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.AlephBrand && window.AlephBrand._known() !== null, null, { timeout: 20000 });
    // ?puppet= dispara loadPuppet FIRE-AND-FORGET y su rehidratación LIMPIA la escena: un seed
    // temprano muere con el wipe tardío (flake histórico de este leg). __loadedPuppet marca el
    // FIN de esa hidratación — recién ahí la escena es estable y se puede sembrar.
    await page.waitForFunction(() => window.__loadedPuppet, null, { timeout: 20000 });
    await page.evaluate(async () => { await window.AlephBrand.image({ connector: "github" }); });
    await page.evaluate(() => {
      const c = window.__cuarto;
      c.placedTiles().forEach((tile) => c.removeTile(tile.id));
      c.placeTile({ id: "gh", label: "GitHub Issues", category: "read", server: "legacy-github-card", connector: "github", tools: ["issues"] }, 1, 1);
      c.placeTile({ id: "xe", label: "Xero", category: "read", server: "xero", connector: "xero", tools: ["accounts"] }, 3, 1);
      c.placeTile({ id: "cu", label: "Custom Local", category: "process", connector: "custom_local", tools: ["run"] }, 5, 1);
      window.__renderPieces();
    });
    await page.waitForFunction(() => {
      const brand = window.__cuarto.brand("gh");
      return !!(brand && brand.shown);
    }, null, { timeout: 20000 });
    const seeded = await page.evaluate(() => ({
      github: window.__cuarto.brand("gh"),
      xero: window.__cuarto.brand("xe"),
      custom: window.__cuarto.brand("cu"),
      // [FIX-P3 · §7] the rows died — "the piece IS the logo". The brand now lives on the
      // diorama piece itself, so that is what gets measured: `brand()` is the render's own
      // read-only view of the mounted face. Stricter: a row could carry an <img> while the
      // piece on the floor showed none; this cannot.
      githubRowImg: !!(window.__cuarto.brand("gh") || {}).shown,
      customRowFallback: window.__cuarto.brand("cu") === null,
    }));
    ok(seeded.github?.slug === "github" && seeded.github?.shown && seeded.githubRowImg,
      `Cuarto ${theme} ${width}: seeded GitHub piece uses same Brandface slug`, JSON.stringify(seeded.github));
    ok(seeded.xero === null, `Cuarto ${theme} ${width}: failed icon fetch keeps generic glyph`, JSON.stringify(seeded.xero));
    ok(seeded.custom === null && seeded.customRowFallback, `Cuarto ${theme} ${width}: missing icon falls back cleanly`, JSON.stringify(seeded.custom));
    await assertNoOverflow(page, `Cuarto ${theme} ${width}`);
    await page.screenshot({ path: `/tmp/aleph-slice-e-cuarto-${theme}-${width}.png`, fullPage: true });
    ok(page.__errors.length === 0, `Cuarto ${theme} ${width}: console clean`, page.__errors.slice(0, 3).join(" | "));
  } finally {
    await page.__context.close();
  }
}

// ── carril REAL: frontend del árbol × sidecar de verdad (el que caza "73 cards / 0 caras") ──

function freePort() {
  return new Promise((res) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); });
  });
}

async function spawnSidecar(bin) {
  const port = await freePort();
  // datadir SIEMPRE aislado salvo override explícito: jamás tocar la DB real del usuario.
  const dataDir = process.env.ALEPH_DATA_DIR || fs.mkdtempSync(path.join(os.tmpdir(), "aleph-slice-e-"));
  const child = spawnFrozen(bin, ["--port", String(port)], {
    stdio: "ignore",
    env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: dataDir },
  });
  const base = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 45000;
  let up = false;
  while (Date.now() < deadline && child.exitCode === null) {
    try { const r = await fetch(base + "/health"); if (r.ok) { up = true; break; } } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  if (!up) { matarFrozen(child); throw new Error("sidecar real no levantó en 45s"); }
  return { child, base };
}

async function checkConectarReal(browser, sidecarBase) {
  const statics = await serve(sidecarBase);
  const base = `http://127.0.0.1:${statics.address().port}`;
  const page = await newPage(browser, base, 1280, "dark", { stub: false });
  try {
    await page.goto(`${base}/Conectar.dc.html`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.querySelectorAll("#grid .card").length > 10, null, { timeout: 30000 });
    await page.waitForFunction(() => window.AlephBrand && window.AlephBrand._known() !== null, null, { timeout: 15000 });
    await page.waitForFunction(
      () => [...document.querySelectorAll("#grid .bface img")].filter((i) => i.complete && i.naturalWidth > 0).length >= 8,
      null, { timeout: 20000 },
    ).catch(() => {});
    const real = await page.evaluate(() => {
      const imgs = [...document.querySelectorAll("#grid .bface img")];
      return {
        cards: document.querySelectorAll("#grid .card").length,
        known: (window.AlephBrand._known() || []).length,
        faces: imgs.filter((i) => i.complete && i.naturalWidth > 0).length,
        monos: document.querySelectorAll("#grid .mono").length,
      };
    });
    ok(real.cards >= 40, `REAL: el catálogo completo renderiza (${real.cards} cards)`, JSON.stringify(real));
    ok(real.known >= 40, `REAL: manifest /v1/icons con slugs curados (${real.known} known)`, JSON.stringify(real));
    ok(real.faces >= 8, `REAL: caras de marca VIVAS en el grid (${real.faces} logos cargados)`, JSON.stringify(real));
    ok(real.monos === 0, `REAL: cero caras .mono genéricas (bug 0/73 muerto)`, JSON.stringify(real));
    await page.screenshot({ path: "/tmp/aleph-slice-e-conectar-real.png", fullPage: true });
    ok(page.__errors.length === 0, "REAL: console clean", page.__errors.slice(0, 3).join(" | "));
  } finally {
    await page.__context.close();
    await new Promise((resolve) => statics.close(resolve));
  }
}

const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();

try {
  console.log("══ Slice E Brandface matrix (stub) ══");
  for (const width of [1280, 1024, 800, 600]) {
    for (const theme of ["dark", "light"]) {
      await attempt(`Conectar ${theme} ${width}`, () => checkConectar(browser, base, width, theme));
      await attempt(`Sala ${theme} ${width}`, () => checkSala(browser, base, width, theme));
      await attempt(`Cuarto ${theme} ${width}`, () => checkCuarto(browser, base, width, theme));
    }
  }
  const REAL_BIN = process.env.ALEPH_SIDECAR_BIN || "";
  const REAL_BASE = process.env.ALEPH_BASE || "";
  if (REAL_BIN || REAL_BASE) {
    console.log("══ Slice E vs SIDECAR REAL ══");
    let child = null;
    let sidecarBase = REAL_BASE;
    if (!sidecarBase) ({ child, base: sidecarBase } = await spawnSidecar(REAL_BIN));
    try {
      await attempt("Conectar REAL", () => checkConectarReal(browser, sidecarBase));
    } finally {
      if (child) {
        try { child.kill(); } catch {}
        const hard = setTimeout(() => matarFrozen(child), 3000);   // grupo entero, no sólo el bootloader
        hard.unref?.();
      }
    }
  } else {
    console.log("(carril real OMITIDO: exportá ALEPH_SIDECAR_BIN=<binario> o ALEPH_BASE=<url> — exigido para certificar Slice E contra la .app)");
  }
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}

console.log(failures.length ? `\n✗ ${failures.length} Slice E failure(s)` : "\n✓ verify_slice_e_brandface: all green");
process.exit(failures.length ? 1 : 0);
