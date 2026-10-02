/* verify_catalog_visibility.mjs -- focused regression for shared catalog visibility.
 *
 * Run:
 *   node product/app/design/verify_catalog_visibility.mjs
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { accessSync, constants } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.FRONT_PORT || 8307);
if (PORT === 25374) throw new Error(":25374 es la .app instalada — jamás");
const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

const atomsFixture = {
  atoms: [
    {
      id: "excel",
      label: "Excel local",
      sub: "crea y edita .xlsx reales",
      atom: "tool",
      zone: "mesa",
      server: "excel",
      tools: ["create_workbook", "edit_sheet"],
      belt_ref: "catalog/templates/finanzas/belt-finanzas.mcp.json",
      auth: "keyless",
      armario: "archivos",
      state: "ready",
      badge: "Ya funciona - sin llave",
      requirements: {
        connection: { needed: false, auth: "keyless", connector: null, connectable: false, state: "ready" },
        params: [],
        gate: { gated: false, level: null },
      },
    },
    {
      id: "stripe-payments",
      label: "Stripe pagos",
      sub: "cobros y clientes via MCP",
      atom: "conexion",
      zone: "entrega",
      server: "stripe",
      tools: ["list_customers", "create_invoice"],
      belt_ref: "catalog/templates/cowork/belt-stripe.mcp.json",
      auth: "personal_token",
      connector: "stripe",
      armario: "apps",
      state: "connectable",
      badge: "Conectar",
      connectable: true,
      requirements: {
        connection: { needed: true, auth: "personal_token", connector: "stripe", connectable: true, state: "connectable" },
        params: [],
        gate: { gated: true, level: "money" },
      },
    },
  ],
  total: 2,
  by_zone: { fuentes: 0, mesa: 1, entrega: 1 },
};

const connectorsFixture = {
  connectors: [
    {
      connector: "stripe",
      auth_method: "personal_token",
      tier: "good",
      capability_line: "Listo - puedo operar Stripe con tu key.",
    },
    {
      connector: "asana",
      auth_method: "personal_token",
      tier: "average",
      capability_line: "Listo - puedo ver tus tareas de Asana.",
    },
  ],
  total: 2,
};

const fails = [];
const ok = (cond, label, extra = "") => {
  console.log(`${cond ? "OK" : "FAIL"} ${label}${extra ? "  " + extra : ""}`);
  if (!cond) fails.push(label + (extra ? " " + extra : ""));
};

function localChromePath() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  const candidates = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  ];
  for (const p of candidates) {
    try { accessSync(p, constants.X_OK); return p; } catch {}
  }
  return null;
}

async function startServer() {
  const server = createServer(async (req, res) => {
    try {
      const pathname = decodeURIComponent((req.url || "/").split("?")[0]);
      const rel = pathname === "/" ? "/Home.dc.html" : pathname;
      const file = resolve(join(ROOT, rel));
      if (!file.startsWith(ROOT)) throw new Error("outside root");
      const buf = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
      res.end(buf);
    } catch {
      res.writeHead(404);
      res.end("not found");
    }
  });
  await new Promise((r) => server.listen(PORT, "127.0.0.1", r));
  return server;
}

async function routeCatalog(page) {
  await page.route("**/v1/**", async (route) => {
    const url = new URL(route.request().url());
    let body = {};
    if (url.pathname === "/v1/atoms/catalog") body = atomsFixture;
    else if (url.pathname === "/v1/connectors") body = connectorsFixture;
    else if (url.pathname === "/v1/motor/estado") {
      const ref = url.searchParams.get("ref") || "";
      const byRef = {
        excel: { estado: "detectado", causa: null },
        stripe: { estado: "roto", causa: "falta_key" },
        asana: { estado: "no_configurado", causa: null },
      };
      const s = byRef[ref] || { estado: "detectado", causa: null };
      body = { tipo: url.searchParams.get("tipo"), ref, ...s,
        evidencia: { fixture: "verify_catalog_visibility" }, ts: 1785192000 };
    }
    else if (url.pathname.startsWith("/v1/connectors/")) {
      const connector = decodeURIComponent(url.pathname.split("/").pop() || "");
      body = {
        connector,
        auth_method: "personal_token",
        capability_line: `Listo - puedo conectar ${connector}.`,
        credential_fields: [{ id: "token", label: "Token", secret: true, shape: "tok_..." }],
        steps: [],
        trust_line: "Se guarda cifrado.",
        errors: {},
      };
    } else if (url.pathname === "/v1/recipes/validate") {
      body = { valid: true, effective_gates: {}, warnings: [], errors: [] };
    } else if (url.pathname === "/v1/models") {
      body = { models: [], source: "stub" };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function visibleText(page, selector) {
  return await page.locator(selector).evaluate((el) => el.innerText || el.textContent || "");
}

async function visibleTextLower(page, selector) {
  return (await visibleText(page, selector)).toLowerCase();
}

const server = await startServer();
const port = server.address().port;
const chromePath = localChromePath();
const launchOpts = chromePath ? { executablePath: chromePath } : {};
let browser;

try {
  browser = await chromium.launch({ headless: true, ...launchOpts });

  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 1, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await routeCatalog(page);
  // La ruta vieja sigue viva sólo como red de seguridad y desemboca en la sección única.
  await page.goto(`http://127.0.0.1:${port}/Conectar.dc.html`, { waitUntil: "load" });
  ok(new URL(page.url()).pathname.endsWith("/Conectores.dc.html"), "Conectar legacy redirects to Conectores");
  await page.waitForFunction(() => {
    const local = (document.querySelector("#localRows")?.innerText || "").toLowerCase();
    const registry = (document.querySelector("#registryRows")?.innerText || "").toLowerCase();
    return ["excel local", "stripe pagos", "asana"].every((s) => local.includes(s))
      && ["github", "postgresql"].every((s) => registry.includes(s));
  });

  let gridText = await visibleTextLower(page, "#localRows");
  const registryText = await visibleTextLower(page, "#registryRows");
  ok(gridText.includes("excel local"), "Conectores LOCAL browses public MCP entries");
  ok(gridText.includes("stripe pagos"), "Conectores LOCAL browses account-backed MCP entries");
  ok(gridText.includes("asana"), "Conectores LOCAL browses connector-only account entries");
  ok(!gridText.includes("memoria compartida"), "Conectores LOCAL excludes structural built-ins");
  ok(registryText.includes("github") && registryText.includes("postgresql"),
     "Conectores REGISTRO loads beside LOCAL");

  const anatomy = await page.evaluate(() => ({
    local: [...document.querySelectorAll("#localRows .local-row")].every((r) =>
      !!r.dataset.estado && !!r.querySelector(".cx-local-state")),
    registry: [...document.querySelectorAll("#registryRows .registry-row")].every((r) =>
      !r.hasAttribute("data-estado") && !r.querySelector(".cx-local-state, .cx-light, [data-count-state]") &&
      !!r.querySelector(".cx-trust") && !!r.querySelector("[data-bring]")),
    selects: document.querySelectorAll("select,[data-puppet],[name*=puppet]").length,
  }));
  ok(anatomy.local, "LOCAL rows read persisted state");
  ok(anatomy.registry, "REGISTRY rows use trust/checklist/[Traer] and never a semaphore");
  ok(anatomy.selects === 0, "Conectores has no agent destination selector");

  await page.fill("#cxSearch", "stripe");
  await page.waitForFunction(() => {
    const txt = (document.querySelector("#localRows")?.innerText || "").toLowerCase();
    return txt.includes("stripe pagos") && !txt.includes("excel local");
  });
  gridText = await visibleTextLower(page, "#localRows");
  ok(gridText.includes("stripe pagos") && !gridText.includes("excel local"), "Conectores search filters its populations");
  await page.fill("#cxSearch", "");

  const legacy = await ctx.newPage();
  await routeCatalog(legacy);
  await legacy.goto(`http://127.0.0.1:${port}/Conexiones.dc.html`, { waitUntil: "load" });
  ok(new URL(legacy.url()).pathname.endsWith("/Conectores.dc.html"), "Conexiones legacy redirects to Conectores");
  await legacy.close();

  const cuartoCtx = await browser.newContext({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 1, reducedMotion: "reduce" });
  const cuarto = await cuartoCtx.newPage();
  await routeCatalog(cuarto);
  /* PRE-EXISTING RED, fixed in passing (verified against the base tree with `git stash`):
   * this navigated to `?equip=excel%230`, a deep-link shape the product stopped emitting.
   * The assertion right above prints the link Conexiones actually builds today —
   * `?equip=mcp%3Aexcel` — so the vara was testing a URL nobody produces, timing out before
   * it reached a single Cuarto assertion. It now follows the link it just verified. */
  await cuarto.goto(`http://127.0.0.1:${port}/cuarto/cuarto.pixi.html?equip=mcp%3Aexcel`, { waitUntil: "load" });
  await cuarto.waitForFunction(() => window.__cuarto && window.__catalog && window.__catalog.entries.length >= 4, null, { timeout: 15000 });
  await cuarto.waitForFunction(() => window.__cuarto.placedTiles().some((t) => /Excel local/.test(t.label || "")), null, { timeout: 10000 });

  /* [FIX-P3 · §7] the piece list died: what an equipped piece looks like now lives on the
   * FLOOR, and its name is read from the foot of its arc. Stricter than the old check: the
   * previous one lowercased the whole panel and looked for the substring "excel" anywhere in
   * it — a log line mentioning excel would have satisfied it. This one finds THE PIECE on the
   * floor and asks ITS arc for its name. */
  const pieceText = await cuarto.evaluate(async () => {
    const c = window.__cuarto;
    const t = c.placedTiles().find((x) => /Excel local/i.test(x.label || ""));
    if (!t) return "";
    window.__openAbanico(c.pieceData(t.id));
    await new Promise((r) => setTimeout(r, 200));
    const n = ((document.getElementById("abName") || {}).textContent || "").toLowerCase();
    try { window.__closeAbanico(); } catch (e) {}
    return n;
  });
  ok(pieceText.includes("excel"), "El Cuarto reflects query-equipped catalog item on the floor", pieceText);

  // [＋ Equipar] vive adentro del ⋯ desde la BARRA DE 3: se entra por donde entra el humano.
  const paletteOpen = await cuarto.locator("#palette").evaluate((el) => el.classList.contains("open"));
  if (!paletteOpen) { await cuarto.click("#metaBtn"); await cuarto.waitForSelector("#equipBtn", { state: "visible" }); await cuarto.click("#equipBtn"); }
  await cuarto.waitForFunction(() => document.querySelector("#palette")?.classList.contains("open"));
  let palText = await visibleTextLower(cuarto, "#paletteList");
  // [CONECTORES RICA · paso 0] La taxonomía visible (LOCAL vs REGISTRO) tiene una dueña:
  // Conectores. El Cuarto conserva la búsqueda para equipar, no repite badges/filtros de
  // procedencia que podían contradecir a la sección.
  ok(!!(await cuarto.locator("#palSearch").count()) && !(await cuarto.locator("#fKind").count()),
     "Equipar palette keeps search and does not duplicate Conectores taxonomy");

  await cuarto.fill("#palSearch", "stripe");
  palText = await visibleTextLower(cuarto, "#paletteList");
  ok(palText.includes("stripe pagos") && !palText.includes("excel local"), "Equipar palette search filters catalog");

  await cuarto.fill("#palSearch", "");
  const dictate = await page.evaluate(() => ({
    localIds: [...document.querySelectorAll("#localRows .local-row")].map((r) => r.dataset.connectorId),
    registryIds: [...document.querySelectorAll("#registryRows .registry-row")].map((r) => r.dataset.registryId),
    fKind: document.querySelectorAll("#fKind").length,
  }));
  ok(await cuarto.locator("#fKind").count() === 0 && dictate.fKind === 0,
     "the abolished #fKind filter stays absent");
  ok(dictate.localIds.length > 0 && dictate.registryIds.length > 0,
     "the Conectores section itself dictates both visible populations");
  ok(new Set([...dictate.localIds, ...dictate.registryIds]).size ===
     dictate.localIds.length + dictate.registryIds.length,
     "each visible connector id belongs to exactly one population");

  await cuartoCtx.close();
  await ctx.close();
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push(e && e.message ? e.message : String(e));
} finally {
  if (browser) await browser.close();
  await new Promise((r) => server.close(r));
}

console.log("");
if (!fails.length) {
  console.log("RESULT: GREEN -- shared catalog visible in Conectores and El Cuarto");
  process.exit(0);
}
console.log(`RESULT: RED (${fails.length})`);
for (const f of fails) console.log(" - " + f);
process.exit(1);
