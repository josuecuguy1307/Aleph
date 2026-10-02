/* verify_icons_live.mjs — ÍCONOS DE DOMINIO en vivo (headless Playwright, SIN backend, puerto ≠ :8091).
 * Prueba que el glifo de dominio (3er hijo de la tool) se MONTA, se RESUELVE bien y se comporta:
 *   (a) glifos correctos sobre tools de servers distintos (yfinance/kicad/dicom/gmail/freecad);
 *   (b) universalidad: un forjado cae por heurística (forged-tmdb→film) y un sin-match → puzzle;
 *   (c) lente F4: el glifo es MONOCROMO (glyphInk) en reposo y toma el color de ROL sólo con F4 ON;
 *       la llave sigue tiñéndose por rol (tickTool intacto). Capturas F4 OFF/ON;
 *   (d) 0 errores de consola (atrapa fallos de PIXI Graphics.svg()).
 * Run:  node verify_icons_live.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveIcon } from "./cuarto.icons.js";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8101;                                 // ≠ :8091
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

// colores de rol (ZONE_DEF de render.js) — para la aserción del tint con F4 ON.
const ROLE_COLOR = { read: 0x35d18f, process: 0x9a7cff, write: 0xf2b13c, send: 0xf2b13c };

// tools sembradas: server/connector reales + forjado + sin-match. category fija el rol (color).
const SEED = [
  { id: "yf",   label: "precio_histórico", category: "read",    server: "yfinance",          gx: 1, gy: 1, expect: "chart-candlestick" },
  { id: "kc",   label: "schematic",        category: "process", server: "kicad",             gx: 3, gy: 1, expect: "circuit-board" },
  { id: "dc",   label: "query_patients",   category: "read",    server: "dicom",             gx: 5, gy: 1, expect: "scan" },
  { id: "gm",   label: "armar_borrador",   category: "write",   connector: "gmail",          gx: 1, gy: 3, expect: "mail" },
  { id: "fc",   label: "create_object",    category: "process", server: "freecad",           gx: 3, gy: 3, expect: "box" },
  { id: "tmdb", label: "buscar_película",  category: "read",    server: "forged-tmdb",       tools: ["get_movie_details"], gx: 5, gy: 3, expect: "film" },
  { id: "raro", label: "frobnicate",       category: "process", server: "totalmente-raro-x", tools: ["frobnicate"],         gx: 2, gy: 5, expect: "puzzle" },
];

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const hex = (n) => (n == null ? "null" : "0x" + Number(n).toString(16).padStart(6, "0"));

// sanity en Node: el contrato resuelve lo que el live espera (mismo módulo que usa render.js)
for (const s of SEED) ok(resolveIcon(s) === s.expect, `[node] resolveIcon(${s.id}) = ${s.expect}`, hex);

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
const shot = async (name) => { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); };

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  // siembra las tools
  const placed = await page.evaluate((seed) => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    for (const s of seed) c.placeTile(s, s.gx, s.gy);
    return c.placedTiles().length;
  }, SEED);
  await page.waitForTimeout(200);
  ok(placed === SEED.length, `sembradas ${SEED.length} tools`, `placed=${placed}`);

  // ── (a)+(b) cada glifo resuelto en VIVO (vía api.glyph) coincide con lo esperado ──
  const live = await page.evaluate((ids) => Object.fromEntries(ids.map((id) => [id, window.__cuarto.glyph(id)])), SEED.map((s) => s.id));
  for (const s of SEED) {
    const g = live[s.id];
    ok(g && g.icon === s.expect, `(a/b) ${s.id} (${s.server || s.connector}) → glifo "${s.expect}"`, g ? `got "${g.icon}"` : "null");
  }
  ok(live.tmdb.icon === "film", "(b) UNIVERSAL · forged-tmdb cae por heurística → film");
  ok(live.raro.icon === "puzzle", "(b) UNIVERSAL · server sin-match + tool sin-keyword → puzzle (default)");

  // ── (c) en REPOSO (view off) el glifo es MONOCROMO: tint === glyphInk ──
  const rest = await page.evaluate((ids) => { const c = window.__cuarto; c.view.set("off");
    return Object.fromEntries(ids.map((id) => [id, c.glyph(id)])); }, SEED.map((s) => s.id));
  for (const s of SEED) ok(rest[s.id].tint === rest[s.id].ink,
    `(c) reposo · ${s.id} glifo monocromo (tint==glyphInk)`, `tint=${hex(rest[s.id].tint)} ink=${hex(rest[s.id].ink)}`);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(250);
  await shot("icons-tools-dark.png");
  await shot("icons-f4-off.png");

  // ── (c) con F4 ON (vista funcion) el glifo toma el COLOR DE ROL (≠ ink) ──
  await page.evaluate(() => window.__cuarto.lens.set(true)); await page.waitForTimeout(250);
  await shot("icons-f4-on.png");
  const on = await page.evaluate((ids) => Object.fromEntries(ids.map((id) => [id, window.__cuarto.glyph(id)])), SEED.map((s) => s.id));
  for (const s of SEED) {
    const want = ROLE_COLOR[s.category];
    ok(on[s.id].tint === want && on[s.id].tint !== on[s.id].ink,
      `(c) F4 ON · ${s.id} glifo toma color de rol (${s.category})`, `tint=${hex(on[s.id].tint)} want=${hex(want)}`);
  }

  // ── (c) F4 OFF de nuevo → vuelve a monocromo ──
  await page.evaluate(() => window.__cuarto.lens.set(false)); await page.waitForTimeout(200);
  const off2 = await page.evaluate((ids) => Object.fromEntries(ids.map((id) => [id, window.__cuarto.glyph(id)])), SEED.map((s) => s.id));
  ok(SEED.every((s) => off2[s.id].tint === off2[s.id].ink), "(c) F4 OFF · todos los glifos vuelven a monocromo");

  // ── (d) 0 errores de consola (incl. cualquier fallo de Graphics.svg) ──
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "(d) 0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — íconos de dominio en vivo (a/b/c/d)"));
process.exit(fails.length ? 1 : 0);
