/* verify_circulo.mjs — done-bar sub-rama 2b (circulo-agente): el recinto-AGENTE tiene cara de CÍRCULO.
 *   (a) agente → _draw.ring:true + ringRadius>0 + halo LATE sobre el anillo · cajón → sin ring
 *   (b) chip de nombre SIEMPRE visible ("<label> · agente", re-traducible)
 *   (c) modelo: rel {kind:"agente", recinto→nucleo} SOLO para agentes; escena sin recintos = sin esa rel
 *   (d) FLUJO por el cable-agente: ida Núcleo→sub-agente y eco sub-agente→Núcleo (ecoLog real)
 *   (e) keepOut: una pieza suelta NO nace pegada al anillo (Chebyshev>1 del footprint)
 *   (f) dark+light · (g) 0 errores JS
 * Puerto :8152. Sin backend (stub /v1/**).   Run: node verify_circulo.mjs */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = 8152;
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 860 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__cuarto.atomState, null, { timeout: 12000 });

  // ── (c-base) escena SIN recintos: cero rels "agente" (paridad con el modelo previo) ──
  const base = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeTile({ id: "vc-t1", label: "t", category: "read", atom: "tool", server: "exa" });
    return c.relations().filter((r) => r.kind === "agente").length;
  });
  ok(base === 0, "(c1) escena sin recintos → 0 relaciones 'agente'", `n=${base}`);

  // ── escena: agente + cajón (colocar → esperar UN frame del ticker → leer _draw) ──
  await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeRecinto({ id: "vc-agente", label: "Research", hasNucleo: true, w: 2, h: 2, agent_ref: "catalog/agents/research-sub.config.json" },
      [{ id: "vc-r1", label: "a", category: "read", atom: "tool", server: "arxiv" }]);
    c.placeRecinto({ id: "vc-cajon", label: "Cajón", hasNucleo: false, w: 2, h: 1 }, []);
  });
  await sleep(150);   // drawRecintos corre en el ticker → _draw existe recién al frame siguiente
  const st = await page.evaluate(() => {
    const c = window.__cuarto;
    return { rels: c.relations().filter((r) => r.kind === "agente"),
             recs: c.atomState().recintos,
             draw: Object.fromEntries(c.recintoDraw().map((r) => [r.id, r])) };
  });
  const agt = st.draw["vc-agente"], caj = st.draw["vc-cajon"];
  ok(agt && agt.ring === true && agt.ringRadius > 20 && agt.haloActive === true,
     "(a1) AGENTE → círculo (ring:true, radio real) + halo activo", `ring=${agt && agt.ring} r=${agt && agt.ringRadius}`);
  ok(caj && caj.ring === false && caj.haloActive === false, "(a2) CAJÓN → sin círculo", `ring=${caj && caj.ring}`);
  // poll-until: el pulso (sin(t·3), amplitud 0.32) DEBE mover el alpha >0.05 en ≤4s reales;
  // muestreo fijo era flaky si el headless congela un par de frames entre lecturas.
  const hs = [agt.haloAlpha]; let hDelta = 0; const hT0 = Date.now();
  while (hDelta <= 0.05 && Date.now() - hT0 < 4000) {
    await sleep(200);
    hs.push(await page.evaluate(() => window.__cuarto.recintoDraw().find((r) => r.id === "vc-agente").haloAlpha));
    hDelta = Math.max(...hs) - Math.min(...hs);
  }
  ok(hDelta > 0.05, "(a3) el halo del anillo LATE (alpha cambia entre frames)", `Δ=${hDelta.toFixed(3)} en ${hs.length} muestras`);
  ok(st.recs["vc-agente"] && /Research · agent/.test(st.recs["vc-agente"].chip || ""),
     "(b) chip visible '<label> · agente' (EN fallback del TR según lang)", `chip=${st.recs["vc-agente"] && st.recs["vc-agente"].chip}`);
  ok(st.rels.length === 1 && st.rels[0].from === "vc-agente" && st.rels[0].to === "nucleo",
     "(c2) rel 'agente' EXACTA: recinto→nucleo, solo el agente", JSON.stringify(st.rels));

  // ── (d) flujo por el cable-agente: ida + eco con el id del RECINTO ──
  const log = await page.evaluate(async () => {
    const c = window.__cuarto;
    c.ecoFire("vc-agente");
    await c.ecoFireSpark("vc-agente");
    await c.ecoReturn("vc-agente", 1.2);
    return c.ecoLog().filter((e) => e.tileId === "vc-agente");
  });
  const ida = log.find((e) => e.dir === "ida"), eco = log.find((e) => e.dir === "eco");
  ok(!!ida && !!eco, "(d1) ida + eco viajaron con el id del sub-agente", `n=${log.length}`);
  ok(ida && eco && Math.abs(ida.from.x - eco.to.x) < 2 && Math.abs(ida.from.y - eco.to.y) < 2,
     "(d2) round-trip cerrado: la ida sale de donde el eco vuelve (Núcleo)", "");
  ok(eco && eco.dur === 1200, "(d3) duración del eco = wall_s real (1.2s→1200ms)", `dur=${eco && eco.dur}`);

  // ── (e) keepOut: 3 piezas sueltas nuevas NO nacen pegadas al agente ──
  const kd = await page.evaluate(() => {
    const c = window.__cuarto;
    const before = c.placedTiles().map((t) => t.id);
    ["k1", "k2", "k3"].forEach((id) => c.placeTile({ id: "vc-" + id, label: id, category: "read", atom: "tool", server: "exa" }));
    const ag = c.pieceData("vc-agente");
    const news = c.placedTiles().filter((t) => !before.includes(t.id));
    return { ag: { gx: ag.gridX, gy: ag.gridY }, news: news.map((t) => ({ id: t.id, gx: t.gridX, gy: t.gridY })) };
  });
  const tooClose = kd.news.filter((p) =>
    p.gx >= kd.ag.gx - 1 && p.gx <= kd.ag.gx + 2 && p.gy >= kd.ag.gy - 1 && p.gy <= kd.ag.gy + 2);
  ok(kd.news.length === 3 && tooClose.length === 0, "(e) keepOut: nada nace pegado al círculo (margen 1 celda)",
     `news=${JSON.stringify(kd.news)} vs agente@${JSON.stringify(kd.ag)}`);

  // ── (f) capturas ──
  await page.evaluate(() => window.__cuarto.cam.fit(1.3)); await sleep(400);
  await page.screenshot({ path: join(HERE, "screenshots", "circulo-dark.png") });
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light"); window.__cuarto.setTheme("light"); });
  await sleep(400);
  await page.screenshot({ path: join(HERE, "screenshots", "circulo-light.png") });
  ok(true, "(f) capturas dark+light", "screenshots/circulo-{dark,light}.png");

  ok(errors.length === 0, "(g) 0 errores JS/render", errors.slice(0, 2).join(" ; "));
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  await browser.close(); server.kill();
}
console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — círculo-agente (anillo+halo · chip · rel agente · flujo por el cable · keepOut)"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
