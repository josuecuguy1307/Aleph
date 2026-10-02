/* reel_capture.mjs — PASO 3: re-captura del Cuarto para el reel (rama cuarto-reform-reel).
 * Honest-spectacular: maneja el Cuarto REAL (pixi.html) y captura el crecimiento como time-lapse.
 *   · EN gate: window.t('cuarto.zone.lee.label')==='Reads' · AlephI18n.lang()==='en' · html lang=en (0 español).
 *   · Solo el diorama en cámara: el chrome (.float de #stage + #aleph-tg) se OCULTA; queda el canvas.
 *   · Crecimiento por ESCALONES (simple → equipa → expande → "este mundo es tuyo"): N capturas por
 *     escalón + un CLIP (recordVideo) de toda la secuencia, en DARK y en LIGHT.
 *   · Glifo de dominio MONO protagonista; color del piso ÚNICO original (sin hue por categoría).
 *   · CLÍMAX = 21 chips UNO POR CATEGORÍA (íconos distintos, cero repetidos), con AIRE (densidad ~0.24:
 *     piso + cables visibles entre piezas) + push-in de cámara (chips más grandes).
 *   · Puerto aislado (≠ :8091/:8096) · 0 errores de consola.
 * Salida: ~/Desktop/aleph-cuarto-reel/{shots,clip}/{dark,light}/   Run:  node reel_capture.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { homedir } from "node:os";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolveIcon } from "./cuarto.icons.js";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const OUT = join(homedir(), "Desktop", "aleph-cuarto-reel");
const PORT = 8146;                                  // aislado (≠ :8091/:8096 y ≠ otros verify)
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const FIT_PAD = 1.22;                               // margen del fit (>1 = más holgura alrededor del diorama)

const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hex = (n) => "#" + (n >>> 0).toString(16).padStart(6, "0").slice(-6);

// 21 servers — UNO POR CATEGORÍA madre (íconos distintos, cero repetidos). Cumulativo por escalón.
const CATS = [
  { server: "yfinance",        category: "read"    }, // financiero  → chart-candlestick
  { server: "exa",             category: "read"    }, // busqueda    → search
  { server: "openfoam",        category: "process" }, // simulacion  → wind
  { server: "gmail",           category: "send"    }, // email       → mail
  { server: "arxiv",           category: "read"    }, // academico   → graduation-cap
  { server: "freecad",         category: "process" }, // cad         → box
  { server: "kicad",           category: "process" }, // electronica → circuit-board
  { server: "github",          category: "write"   }, // codigo      → git-branch
  { server: "huggingface",     category: "process" }, // ml_ia       → brain
  { server: "slack",           category: "send"    }, // mensajeria  → message-square
  { server: "dicom",           category: "read"    }, // medico      → scan
  { server: "forged-tmdb",     category: "read"    }, // media       → film
  { server: "resolved-mapbox", category: "read"    }, // mapas       → map
  { server: "stata",           category: "process" }, // datos       → chart-column
  { server: "pandoc",          category: "process" }, // documentos  → file-text
  { server: "google_calendar", category: "read"    }, // calendario  → calendar
  { server: "forged-notion",   category: "write"   }, // escritura   → pen-line
  { server: "resolved-stripe", category: "send"    }, // pagos       → credit-card
  { server: "forged-zapier",   category: "process" }, // automatizacion → workflow
  { server: "forged-rss",      category: "read"    }, // comunicacion → radio
  { server: "zzz-unknown-xyz", category: "process" }, // custom      → puzzle
];
const distinctIcons = new Set(CATS.map((c) => resolveIcon({ server: c.server }))).size;
const tool = (spec, i) => { const id = `reel-${spec.server}-${i}`; return { id, key: id, label: spec.server, category: spec.category, atom: "tool", server: spec.server }; };

async function captureRun(browser, theme) {
  const SHOTS = join(OUT, "shots", theme), CLIP = join(OUT, "clip", theme);
  mkdirSync(SHOTS, { recursive: true }); mkdirSync(CLIP, { recursive: true });
  const bg = theme === "light" ? "#f3ecdf" : "#10131a";
  const context = await browser.newContext({
    viewport: { width: 1600, height: 900 }, deviceScaleFactor: 2,
    recordVideo: { dir: CLIP, size: { width: 1600, height: 900 } },
  });
  await context.addInitScript((t) => {
    try { localStorage.setItem("aleph-lang", "en"); localStorage.setItem("aleph-theme", t); } catch (e) {}
  }, theme);
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

  let shotN = 0;
  const shot = async (name) => { shotN++; await page.screenshot({ path: join(SHOTS, `${String(shotN).padStart(2, "0")}-${name}.png`) }); };
  // coloca una pieza y RE-ENCUADRA al toque (fit al bounding-box del contenido) → la cámara siempre
  // contiene TODO; cuando la grilla crece (7→11) hace zoom-out suave, nunca recorta a mitad del time-lapse.
  const placeMany = async (specs, base, { dwell = 150 } = {}) => {
    for (let i = 0; i < specs.length; i++) {
      await page.evaluate((t) => window.__cuarto.placeTile(t), tool(specs[i], base + i));
      await page.evaluate((p) => window.__cuarto.cam.fit(p), FIT_PAD);   // fit continuo (recalcula bounds al tamaño actual)
      await sleep(dwell);
    }
  };
  // fit al contenido COMPLETO con margen (sin zoom fijo): Cuarto entero en frame, holgado. Nada cortado.
  const frame = async () => { await page.evaluate((p) => window.__cuarto.cam.fit(p), FIT_PAD); await sleep(350); };

  try {
    await page.goto(PAGE_URL, { waitUntil: "load" });
    await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 12000 });

    // EN + tema + ocultar chrome (solo diorama)
    const g = await page.evaluate(({ t, bg }) => {
      document.documentElement.lang = "en";
      document.documentElement.setAttribute("data-theme", t);
      try { window.AlephI18n && window.AlephI18n.apply && window.AlephI18n.apply(); } catch (e) {}
      try { window.__cuarto.setTheme(t); } catch (e) {}
      const st = document.createElement("style");
      st.textContent = `#stage > *:not(#cuarto){display:none!important} body > *:not(#stage){display:none!important} #aleph-tg{display:none!important} html,body{background:${bg}!important}`;
      document.head.appendChild(st);
      return { lee: window.t("cuarto.zone.lee.label"), lang: window.AlephI18n.lang(), htmlLang: document.documentElement.lang };
    }, { t: theme, bg });
    ok(g.lee === "Reads", `[${theme}] EN gate · 'cuarto.zone.lee.label'==='Reads'`, `lee=${g.lee}`);
    ok(g.lang === "en", `[${theme}] EN gate · AlephI18n.lang()==='en'`, `lang=${g.lang}`);
    ok(g.htmlLang === "en", `[${theme}] EN gate · html lang=en`);
    await page.evaluate(() => { window.__cuarto.relabel(); window.__cuarto.placedTiles().forEach((t) => window.__cuarto.removeTile(t.id)); });
    await frame(); await shot("escalon0-vacio");

    // ESCALÓN 1 · SIMPLE (4 categorías)
    await placeMany(CATS.slice(0, 4), 0); await frame(); await shot("escalon1-simple-a"); await shot("escalon1-simple-b");
    // ESCALÓN 2 · SE EQUIPA (→10) + constelación limpia
    await placeMany(CATS.slice(4, 10), 4); await frame(); await shot("escalon2-equipa-a"); await shot("escalon2-equipa-b");
    await page.evaluate(() => { window.__cuarto.view.set("servicio"); window.__cuarto.cam.fit(1.55); }); await sleep(500); await shot("escalon2-constelacion");
    await page.evaluate(() => window.__cuarto.view.set("off")); await sleep(250);
    // ESCALÓN 3 · SE EXPANDE (→16)
    const n0 = await page.evaluate(() => window.__cuarto.gridSize().N);
    await placeMany(CATS.slice(10, 16), 10); await frame();
    const n1 = await page.evaluate(() => window.__cuarto.gridSize().N);
    ok(n1 > n0, `[${theme}] grilla SE EXPANDIÓ en escalón 3 (N creció)`, `N: ${n0} → ${n1}`);
    await shot("escalon3-expande-a"); await shot("escalon3-expande-b");
    // ESCALÓN 4 · "ESTE MUNDO ES TUYO" (→21, uno por categoría, todos distintos)
    await placeMany(CATS.slice(16, 21), 16); await frame();
    const d = await page.evaluate(() => window.__cuarto.density());
    const placed = await page.evaluate(() => window.__cuarto.placedTiles().length);
    ok(d.value >= 0.18 && d.value <= 0.28, `[${theme}] clímax con AIRE (densidad ~0.20-0.25)`, `n=${d.n} N=${d.N} dens=${d.value.toFixed(3)}`);
    ok(placed === 21 && distinctIcons === 21, `[${theme}] clímax = 21 chips, UNO por categoría (glifos distintos, 0 repetidos)`, `piezas=${placed} glifos_distintos=${distinctIcons}`);
    await shot("escalon4-mundo-tuyo-a"); await shot("escalon4-mundo-tuyo-b");
    // constelación al clímax
    await page.evaluate(() => { window.__cuarto.view.set("servicio"); window.__cuarto.cam.fit(1.55); }); await sleep(500); await shot("escalon4-constelacion");
    await page.evaluate(() => window.__cuarto.view.set("off")); await sleep(250);

    // CAPABILITY · recinto en escena LIMPIA (el halo del sub-agente se LEE)
    await page.evaluate(() => window.__cuarto.placedTiles().forEach((t) => window.__cuarto.removeTile(t.id)));
    await page.evaluate(() => {
      const c = window.__cuarto;
      c.placeRecinto({ label: "Research sub-agent", hasNucleo: true, w: 2, h: 2 },
        [{ id: "cap-r1", label: "a", category: "read", atom: "tool", server: "arxiv" },
         { id: "cap-r2", label: "b", category: "read", atom: "tool", server: "exa" },
         { id: "cap-r3", label: "c", category: "process", atom: "tool", server: "pandoc" }]);
      ["yfinance", "gmail", "github"].forEach((s, i) => c.placeTile({ id: "cap-l" + i, label: s, category: ["read", "send", "write"][i], atom: "tool", server: s }));
    });
    await frame(); await shot("capability-recinto-clean");

    const real = errors.filter((e) => !/Failed to load resource|favicon|net::ERR/i.test(e));
    ok(real.length === 0, `[${theme}] 0 errores JS/render`, real.length ? "\n  " + real.join("\n  ") : "");
  } catch (e) {
    console.error(`HARNESS ERROR [${theme}]:`, e); fails.push(`harness[${theme}]: ${e && e.message ? e.message : String(e)}`);
  } finally {
    await page.close(); await context.close();
  }
  console.log(`  → ${theme}: ${shotN} capturas en ${SHOTS} · clip en ${CLIP}`);
}

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  for (const theme of ["dark", "light"]) await captureRun(browser, theme);
} finally {
  await browser.close(); server.kill();
}

console.log("");
if (fails.length === 0) console.log("RESULTADO: VERDE — reel re-capturado en DARK y LIGHT (EN · chrome oculto · 21 distintos · aire · push-in · recinto + constelación)");
else { console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); }
process.exit(fails.length === 0 ? 0 : 1);
