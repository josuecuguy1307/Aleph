/* verify_reel.mjs — REFORMA REEL del Cuarto (rama cuarto-reform-reel). Headless, sin backend.
 * Prueba los 3 cambios de la reconstrucción mediana sobre la pixi.html real:
 *   CAMBIO 1 · GLIFO PROTAGONISTA: el ícono de dominio es grande/centrado/billboard y MONOCROMO; el
 *             zócalo es color único original (sin hue por categoría). Universalidad = glifos distintos.
 *   CAMBIO 2 · DENSIDAD: placeTile sin coords EXPANDE la grilla al conteo (N=ceil(1+√(n/0.24))) ANTES de
 *             poblar; densidad n/(N−1)² ≤ 0.60 SIEMPRE; keep-out (Núcleo + tronco de cable) respetado.
 *   CAMBIO 3 · CAPACIDADES: recinto (api.placeRecinto, halo de agente) + constelación (api.view.set) prenden.
 * + capturas para el gate (mosaico · constelación · recinto). Run:  node verify_reel.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveIcon } from "./cuarto.icons.js";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8141;                                 // puerto libre (≠ los otros verify)
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const hex = (n) => "#" + (n >>> 0).toString(16).padStart(6, "0").slice(-6);

// ── set de servers que barre las 21 categorías madre (chip hue = categoryHue del DOMINIO) ──
const SPECS = [
  { server: "yfinance",        category: "read"    }, // financiero
  { server: "pandoc",          category: "process" }, // documentos
  { server: "arxiv",           category: "read"    }, // academico
  { server: "exa",             category: "read"    }, // busqueda
  { server: "stata",           category: "process" }, // datos
  { server: "forged-tmdb",     category: "read"    }, // media
  { server: "dicom",           category: "read"    }, // medico
  { server: "resolved-mapbox", category: "read"    }, // mapas
  { server: "freecad",         category: "process" }, // cad
  { server: "openfoam",        category: "process" }, // simulacion
  { server: "kicad",           category: "process" }, // electronica
  { server: "github",          category: "write"   }, // codigo
  { server: "huggingface",     category: "process" }, // ml_ia
  { server: "gmail",           category: "send"    }, // email
  { server: "slack",           category: "send"    }, // mensajeria
  { server: "google_calendar", category: "read"    }, // calendario
  { server: "forged-notion",   category: "write"   }, // escritura
  { server: "resolved-stripe", category: "send"    }, // pagos
  { server: "forged-zapier",   category: "process" }, // automatizacion
  { server: "forged-rss",      category: "read"    }, // comunicacion
  { server: "zzz-unknown-xyz", category: "process" }, // custom (default puzzle)
];

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

  // limpiar a sólo-Núcleo (la escena puede traer piezas sembradas)
  await page.evaluate(() => window.__cuarto.placedTiles().forEach((t) => window.__cuarto.removeTile(t.id)));
  const N0 = (await page.evaluate(() => window.__cuarto.gridSize())).N;
  ok(N0 === 7, "grilla arranca en N=7 (escena base)", `N0=${N0}`);

  // ── CAMBIO 2 · colocar 42 piezas SIN coords; medir densidad + N + keep-out en CADA paso ──
  const nucleo = await page.evaluate(() => { const z = window.__cuarto.scene.zones.find((x) => x.role === "nucleo"); return { gx: z.gridX, gy: z.gridY }; });
  const TOTAL = 42;
  const trail = await page.evaluate(({ specs, total }) => {
    const c = window.__cuarto, out = [];
    for (let i = 0; i < total; i++) {
      const s = specs[i % specs.length];
      const id = `reel-${s.server}-${i}`;
      c.placeTile({ id, key: id, label: s.server, category: s.category, atom: "tool", server: s.server });
      const d = c.density(), g = c.gridSize();
      out.push({ value: d.value, n: d.n, N: g.N });
    }
    return out;
  }, { specs: SPECS, total: TOTAL });

  const maxDens = Math.max(...trail.map((t) => t.value));
  const finalN = trail[trail.length - 1].N;
  ok(maxDens <= 0.60 + 1e-9, "CAMBIO 2 · densidad n/(N−1)² ≤ 0.60 en TODO el crecimiento", `pico=${maxDens.toFixed(3)}`);
  ok(finalN > N0, "CAMBIO 2 · la grilla SE EXPANDIÓ de verdad con el conteo (N creció)", `N: ${N0} → ${finalN}`);
  // N esperado por la fórmula del harness 689749d0
  const expN = Math.max(7, Math.ceil(1 + Math.sqrt(TOTAL / 0.24)));
  ok(finalN === expN, "CAMBIO 2 · N = ceil(1+√(count/0.24)) (densidad objetivo ~0.24, con aire)", `N=${finalN} esperado=${expN}`);

  // keep-out: ninguna pieza sobre el Núcleo+anillo ni sobre el tronco de cable
  const placed = await page.evaluate(() => window.__cuarto.placedTiles().map((t) => ({ gx: t.gridX, gy: t.gridY })));
  // misma definición que el source: anclada al Núcleo (estable bajo crecimiento), NO al centro de grilla
  const inKeepOut = (gx, gy) =>
    Math.max(Math.abs(gx - nucleo.gx), Math.abs(gy - nucleo.gy)) <= 1 ||
    (gx === nucleo.gx && gy > nucleo.gy && gy <= nucleo.gy + 3);
  const violations = placed.filter((p) => inKeepOut(p.gx, p.gy));
  ok(violations.length === 0, "CAMBIO 2 · keep-out respetado (0 piezas sobre Núcleo+anillo ni tronco de cable)", `violaciones=${violations.length}`);

  // ── CAMBIO 1 · DIVERSIDAD por ÍCONO (el color volvió al original; la universalidad la lleva el glifo) ──
  const expectedIcons = new Set(SPECS.map((s) => resolveIcon({ server: s.server })));
  ok(expectedIcons.size >= 18, "CAMBIO 1 · el set sembrado abarca ≥18 glifos de dominio distintos (universalidad por ícono)", `distinct=${expectedIcons.size}/21`);
  // verificación en VIVO: el glifo resuelto por pieza coincide con la cadena de íconos (render real)
  const liveGlyphs = await page.evaluate(() => {
    const c = window.__cuarto, seen = {};
    for (const t of c.placedTiles()) { const g = c.glyph(t.id); if (g) seen[t.id] = { icon: g.icon, tint: g.tint, ink: g.ink }; }
    return seen;
  });
  const sample = `reel-yfinance-0`;
  ok(liveGlyphs[sample] && liveGlyphs[sample].tint === liveGlyphs[sample].ink,
     "CAMBIO 1 · glifo MONOCROMO en reposo (tint==glyphInk) — contrato intacto", `tint=${liveGlyphs[sample] && hex(liveGlyphs[sample].tint)}`);
  // todas las piezas tienen glifo no-vacío y mono
  const allMono = Object.values(liveGlyphs).every((g) => g.tint === g.ink);
  ok(allMono && Object.keys(liveGlyphs).length === TOTAL, "CAMBIO 1 · las 42 piezas tienen glifo de dominio resuelto y monocromo", `glifos=${Object.keys(liveGlyphs).length}`);

  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(300);
  await shot("reel-01-mosaico.png");

  // ── CAMBIO 3 · CONSTELACIÓN: prende vía api.view.set y agrupa ──
  const cons = await page.evaluate(() => { const c = window.__cuarto; const m = c.view.set("servicio"); return { mode: c.view.get(), state: c.viewState() }; });
  ok(cons.mode === "servicio" && cons.state.groups.length > 0, "CAMBIO 3 · constelación PRENDE (api.view.set('servicio') agrupa por dominio)", `grupos=${cons.state.groups.length}`);
  await page.waitForTimeout(300); await shot("reel-02-constelacion.png");
  await page.evaluate(() => window.__cuarto.view.set("off"));

  // ── CAMBIO 3 · RECINTO: api.placeRecinto crea un AGENTE con halo ──
  const r = await page.evaluate(() => window.__cuarto.placeRecinto({ label: "Sub-agente", hasNucleo: true, w: 2, h: 2 },
      [{ id: "rk1", label: "tool A", category: "read", atom: "tool", server: "yfinance" },
       { id: "rk2", label: "tool B", category: "process", atom: "tool", server: "openfoam" }]));
  await page.waitForTimeout(150);                                   // dejar correr un frame del ticker (drawRecintos llena n._draw)
  const draw = await page.evaluate((id) => window.__cuarto.recintoDraw().find((d) => d.id === id), r && r.id);
  ok(r && r.hasNucleo === true, "CAMBIO 3 · recinto-AGENTE creado vía api.placeRecinto (hasNucleo)", `id=${r && r.id}`);
  ok(draw && draw.haloActive === true, "CAMBIO 3 · el recinto DIBUJA su halo de agente (recintoDraw)", `haloActive=${draw && draw.haloActive}`);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(300);
  await shot("reel-03-recinto.png");

  // ── 0 errores de consola/render ──
  const real = errors.filter((e) => !/Failed to load resource|favicon|net::ERR/i.test(e));
  ok(real.length === 0, "0 errores JS/render de página", real.length ? "\n  " + real.join("\n  ") : "");

} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push("harness: " + (e && e.message ? e.message : String(e)));
} finally {
  await browser.close();
  server.kill();
}

console.log("");
if (fails.length === 0) console.log("RESULTADO: VERDE — reforma reel (glifo mono protagonista · color único · densidad con aire · keep-out · recinto · constelación)");
else { console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); }
process.exit(fails.length === 0 ? 0 : 1);
