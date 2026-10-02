/* verify_pulso_real.mjs — LA CORRIDA REAL del pulso: Opus vía shim :8923, tool_calls>0 REALES.
 *
 * NO fabrica eventos. Sirve el front de ESTE worktree (con el pulso A+B+C) en un puerto propio,
 * proxyando /v1 al backend REAL :8080 (su worker drena la cola, su events_dir alimenta el stream).
 * Equipa pysandbox (run_python, keyless, belt-inline-rich) y toca ▶ RUN con el cerebro DEFAULT
 * (opus → shim :8923, claude-code-opus-4.8). El agente llama run_python de verdad → el Motor B
 * emite tool_call_started/finished reales → consumeLive dispara el PULSO (ida+eco) en el cable.
 *
 * Prueba: window.__ecoTools === N (N = tool_calls reales del closed), model_final = opus, ida+eco
 * en el ecoLog, y captura del destello sobre el cable. SIN tool_calls reales → ROJO honesto (no
 * fabrica). Requiere el stack vivo (backend :8080 + shim :8923). Si no está, lo dice y sale 3.
 *
 * Run:  node verify_pulso_real.mjs        (BACKEND=http://127.0.0.1:8080 por defecto)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const WORKTREE = join(HERE, "..", "..", "..", "..");   // cuarto → design → app → product → repo
const SHOTS = join(HERE, "screenshots");
const BACKEND = process.env.BACKEND || "http://127.0.0.1:8080";
const FRONT_PORT = Number(process.env.FRONT_PORT || 8099);
const PAGE_URL = `http://127.0.0.1:${FRONT_PORT}/cuarto/cuarto.pixi.html`;

const log = (...a) => console.log(...a);
const fails = [];
const ok = (cond, label, extra) => { log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

// ── 0) pre-flight: backend + shim vivos ──
async function up(url) { try { const r = await fetch(url, { signal: AbortSignal.timeout(3000) }); return r.ok; } catch { return false; } }
if (!(await up(`${BACKEND}/health`))) { console.error(`FALTA: backend en ${BACKEND}/health no responde. Levantá el stack.`); process.exit(3); }
if (!(await up("http://127.0.0.1:8923/v1/models"))) { console.error("FALTA: shim Opus :8923 no responde. Arrancá el shim (PUPPET_BRAIN_SHIM=1, SHIM_CALL_TIMEOUT=360)."); process.exit(3); }
log(`· backend ${BACKEND} ✓ · shim :8923 ✓`);

// ── 1) front de ESTE worktree (con el pulso) → proxy /v1 a :8080 ──
const front = spawn("python3", ["product/app/serve.py"], {
  cwd: WORKTREE, stdio: "ignore",
  env: { ...process.env, ALEPH_FRONT_PORT: String(FRONT_PORT), ALEPH_BACKEND: BACKEND },
});
await new Promise((r) => setTimeout(r, 900));
// confirmá que sirve EL CÓDIGO DEL PULSO (no otro worktree)
const hasPulso = await (async () => { try { const r = await fetch(`${PAGE_URL.replace("cuarto.pixi.html", "cuarto.render.js")}`); const t = await r.text(); return /ecoFireSpark/.test(t); } catch { return false; } })();
ok(hasPulso, "el front sirve el código del PULSO de este worktree (ecoFireSpark presente)");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1320, height: 880 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
const shot = async (name) => { try { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); } catch {} };

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 15000 });

  // ── 2) equipá pysandbox (run_python, keyless) — átomo REAL del catálogo del backend ──
  const placed = await page.evaluate(async () => {
    const cat = await (await fetch("/v1/atoms/catalog")).json();
    const atoms = cat.atoms || cat;
    const py = atoms.find((a) => a.id === "pysandbox" || a.server === "pysandbox");
    if (!py) return { ok: false };
    window.__cuarto.placeTile({ ...py, key: py.id });   // arrastra belt_ref/server/tools del catálogo real
    const t = window.__cuarto.placedTiles().find((x) => x.server === "pysandbox");
    return { ok: !!t, tile: t };
  });
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(250);
  ok(placed.ok, "pysandbox equipado (run_python, keyless, belt-inline-rich)", placed.tile ? `belt_ref=${placed.tile.belt_ref}` : "");
  await shot("pulso-real-0-equipado.png");

  // ── 3) prompt que FUERZA un run_python real + cerebro DEFAULT (opus → shim :8923) ──
  await page.evaluate(() => {
    const r = document.getElementById("runprompt");
    if (r) r.value = "Usá tu herramienta de Python (run_python) AHORA para calcular la suma de los enteros del 1 al 100. Ejecutá el código de verdad; no lo expliques. Decime sólo el número resultante.";
  });
  const model = await page.evaluate(() => { const c = window.__cuarto; const d = c.nucleoData(); return { model: d.model, recipe: (window.__lastRecipe && window.__lastRecipe.model) || null }; });
  log(`· cerebro del núcleo: ${model.model} (default → shim Opus). Tocando ▶ RUN…`);

  // ── 4) ▶ RUN (camino real: enqueue → worker :8080 → shim Opus → run_python → eventos reales) ──
  await page.evaluate(() => { window.__ecoTools = undefined; });
  // [Cuarto entrega, no corre] el Cuarto ya no tiene botón de Ejecutar: correr es de La Sala.
  // El PIPELINE quedó intacto y sigue siendo lo que esta vara prueba — se dispara por código.
  await page.evaluate(() => window.__ejecutarTurno());

  // catch del destello en vuelo: apenas el ecoLog crezca (1er evento real), screenshot
  let captured = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 240000) {
    const st = await page.evaluate(() => ({ done: window.__ecoTools !== undefined, n: (window.__cuarto.ecoLog() || []).length }));
    if (!captured && st.n > 0) { await shot("pulso-real-1-destello-en-vuelo.png"); captured = true; }
    if (st.done) break;
    await page.waitForTimeout(350);
  }

  const R = await page.evaluate(() => ({
    tools: window.__ecoTools, verdict: window.__lastRun, enqueue: window.__enqueue,
    log: window.__cuarto.ecoLog(),
  }));
  await page.waitForTimeout(200); await shot("pulso-real-2-final.png");

  log("\n  ── enqueue ──\n    " + JSON.stringify(R.enqueue).slice(0, 240));
  log("  ── verdict (closed) ──\n    " + JSON.stringify(R.verdict).slice(0, 360));
  log("  ── ecoLog (destellos disparados) ──\n    " + JSON.stringify(R.log).slice(0, 400));

  const mf = String((R.verdict && R.verdict.model_final) || "");
  const idas = (R.log || []).filter((e) => e.dir === "ida");
  const ecos = (R.log || []).filter((e) => e.dir === "eco");
  ok(typeof R.tools === "number" && R.tools >= 1, "REAL · tool_calls>0 (no fabricados) — window.__ecoTools", `__ecoTools=${R.tools}`);
  ok(/opus/i.test(mf), "REAL · el cerebro fue Opus vía shim (model_final)", `model_final=${mf}`);
  ok(idas.length >= 1 && ecos.length >= 1, "REAL · el PULSO disparó ida (Núcleo→tool) Y eco (tool→Núcleo) sobre el cable", `ida=${idas.length} eco=${ecos.length}`);
  ok(captured, "REAL · capturé el destello en vuelo (pulso-real-1-destello-en-vuelo.png)");
  ok(R.verdict && R.verdict.ok === true, "REAL · el run cerró OK (closed.ok)", R.verdict ? `ok=${R.verdict.ok} error=${R.verdict.error || "—"}` : "sin veredicto");

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon|net::ERR/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); front.kill("SIGKILL");
}

log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — PULSO REAL (Opus vía shim, tool_calls>0 reales, ida+eco sobre el cable, captura)"));
process.exit(fails.length ? 1 : 0);
