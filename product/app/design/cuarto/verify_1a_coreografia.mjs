/* _verify_1a.mjs — verificación e2e de la rama 1a-coreografia (Motor B + coreografía del contrato).
 * Front del worktree (serve.py :8096 → backend :8077, GROQ + seed-probes ON). NO toca :8091.
 * UNA sola forja REAL (con seeds → valida brain + descarta 404s) para no chocar el TPM de Groq;
 * assert (a) se prueba con el request INTERCEPTADO (sin gastar forja). Render 1:1 con eventos reales.
 */
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const BASE = process.env.ALEPH_BASE || "http://127.0.0.1:8096";
const PAGE = BASE + "/cuarto/cuarto.pixi.html";
const SHOTDIR = process.env.SHOTDIR;
const TMDB = readFileSync(process.env.TMDB_KEY_FILE).toString().trim();
const URL_TARGET = "https://api.themoviedb.org/3";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const eqMultiset = (a, b) => { const A = [...a].sort(), B = [...b].sort(); return A.length === B.length && A.every((x, i) => x === B[i]); };

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1366, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push("[console] " + m.text()); });
page.on("pageerror", (e) => errors.push("[pageerror] " + String(e)));
const shot = (n) => page.screenshot({ path: join(SHOTDIR, n) });

const R = {};
try {
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__cuarto.forge && window.__startForgeInspection, null, { timeout: 12000 });
  await sleep(600);
  await shot("1a-00-idle.png");

  const snap = () => page.evaluate(() => ({
    model: JSON.stringify(window.__cuarto.relationModel()),
    pieces: JSON.stringify(window.__cuarto.pieces()),
    relations: JSON.stringify(window.__cuarto.relations()),
    placed: JSON.stringify(window.__cuarto.placedTiles()),
  }));
  const before = await snap();

  // ════ ASSERT (a) · el clic REAL del botón LLEVA a la pantalla de Inspección, con el handoff.
  //
  // ⚠️ REALINEADO AL CONTRATO NUEVO [Integración #5 · cierre (f)]. Antes este assert probaba que
  // el clic disparaba POST /v1/inspect/forge, o sea la coreografía ENCIMA del diorama. Eso dejó
  // de ser el contrato: el trabajo pesado vive en `inspeccion/inspeccion.html` (igual que
  // "＋ Tu MCP"), y desde el Cuarto sólo se equipa. Lo que hay que probar ahora es el CABLEADO
  // del botón a su destino y que lo tipeado VIAJE — no que el diorama forje.
  //
  // El motor NO cambió y este archivo lo sigue probando entero: la fase de abajo corre la forja
  // REAL por `window.__startForgeInspection`, el mismo camino que usa la pantalla nueva
  // (importa `inspectAndEquip` de `cuarto/cuarto.inspect.js` y pega a los mismos endpoints).
  //
  // Se intercepta la navegación y se ABORTA: así leemos la URL destino sin perder el documento
  // (el resto del verify sigue usando `window.__cuarto` de ESTA página).
  let navUrl = null;
  await page.route("**/inspeccion/inspeccion.html*", async (route) => {
    navUrl = route.request().url();
    await route.abort();
  });
  await page.fill("#intent", URL_TARGET);
  await page.fill("#inspecttoken", TMDB);
  await page.click("#inspect");
  await sleep(900);
  await page.unroute("**/inspeccion/inspeccion.html*");
  const navQS = navUrl ? new URLSearchParams(navUrl.split("?")[1] || "") : null;
  R.assert_a = !!navUrl && /\/inspeccion\/inspeccion\.html/.test(navUrl) &&
    navQS.get("forma") === "token" && navQS.get("url") === URL_TARGET;
  R.handoffShape = { destino: navUrl && navUrl.split("?")[0], forma: navQS && navQS.get("forma"),
    url_viaja: !!(navQS && navQS.get("url") === URL_TARGET) };
  // el diorama NO se tocó: el clic ya no forja acá.
  R.assert_a_sin_coreografia = await page.evaluate(() => !window.__cuarto.forge.on);

  // ════ FORJA REAL (única) · vía el MISMO runForge del botón + seeds (404 reales → descartadas).
  // Instrumentamos api.forge para registrar cada COMANDO de render y comparar 1:1 con los eventos.
  await sleep(300);
  await page.evaluate(() => {
    const f = window.__cuarto.forge;
    window.__render = { propose: [], validating: [], validated: [], discarded: [] };
    for (const m of ["propose", "validating", "validated", "discarded"]) {
      const orig = f[m].bind(f);
      f[m] = (...a) => { const name = (m === "propose") ? (a[0] && (a[0].name || a[0].nombre)) : a[0];
        window.__render[m].push(name); return orig(...a); };
    }
    window.__ev = []; window.__done = false; window.__res = null;
    window.__peak = { ghosts: 0, validating: 0, validated: 0, discarded: 0, connected: 0 };
  });
  const seeds = [
    { name: "get_movie_box_office", endpoint: "/movie/{movie_id}/box_office", path_params: { movie_id: 550 } },
    { name: "get_movie_awards", endpoint: "/movie/{movie_id}/awards", path_params: { movie_id: 550 } },
    { name: "get_person_awards", endpoint: "/person/{person_id}/awards", path_params: { person_id: 287 } },
  ];
  await page.evaluate(({ url, cred, seeds }) => {
    window.__startForgeInspection({ url, cred, seedProbes: seeds, onEvent: (e) => window.__ev.push(e) })
      .then((r) => { window.__res = r; window.__done = true; });
  }, { url: URL_TARGET, cred: TMDB, seeds });

  // poll: captura cada fase la PRIMERA vez que aparece + acumula peaks
  const seen = {};
  const t0 = Date.now();
  while (Date.now() - t0 < 180000) {
    const s = await page.evaluate(() => {
      const st = window.__cuarto.forge.stats(); const p = window.__peak;
      p.ghosts = Math.max(p.ghosts, st.ghosts || 0); p.validating = Math.max(p.validating, st.validating || 0);
      p.validated = Math.max(p.validated, st.validated || 0); p.discarded = Math.max(p.discarded, st.discarded || 0);
      p.connected = Math.max(p.connected, st.connected ? 1 : 0); return st;
    });
    if (s.connected && !seen.c) { seen.c = 1; await shot("1a-01-target-conectada.png"); }
    if (s.ghosts > 0 && !seen.g) { seen.g = 1; await shot("1a-02-fantasmas-abanico.png"); }
    if (s.validating > 0 && !seen.vg) { seen.vg = 1; await shot("1a-03-validando-pulsa.png"); }
    if (s.validated > 0 && !seen.vd) { seen.vd = 1; await shot("1a-04-validada-solida.png"); }
    if (s.discarded > 0 && !seen.dz) { seen.dz = 1; await shot("1a-05-descartada-desvanece.png"); }
    if (await page.evaluate(() => window.__done)) { if (!seen.f && s.ghosts) { await sleep(400); await shot("1a-06-forjado-listas-sellar.png"); seen.f = 1; } break; }
    await sleep(60);
  }
  await sleep(300);
  if (!seen.f) { await shot("1a-06-forjado-listas-sellar.png"); }

  const res = await page.evaluate(() => window.__res);
  const render = await page.evaluate(() => window.__render);
  const ev = await page.evaluate(() => window.__ev);
  const peak = await page.evaluate(() => window.__peak);
  const after = await snap();

  const evNames = (t) => ev.filter((e) => e.type === t).map((e) => e.nombre);
  const evPropuesta = evNames("tool.propuesta"), evValidando = evNames("tool.validando");
  const evValidada = evNames("tool.validada"), evDescartada = evNames("tool.descartada");
  const evTypes = [...new Set(ev.map((e) => e.type))];
  const seedNames = seeds.map((s) => s.name);

  R.run_ok = !!(res && res.ok);
  R.degraded = ev.some((e) => e.type === "error" && e.degraded);
  R.eventTypes = evTypes;
  R.eventCounts = { propuesta: evPropuesta.length, validando: evValidando.length, validada: evValidada.length, descartada: evDescartada.length };
  R.renderCounts = { propose: render.propose.length, validating: render.validating.length, validated: render.validated.length, discarded: render.discarded.length };
  R.peak = peak;

  // (b) las N fantasmas aparecen en síntesis (propuestas reales del cerebro) + target conectada
  R.assert_b = peak.ghosts > 0 && peak.connected === 1 && render.propose.length > 0 && eqMultiset(render.propose, evPropuesta);
  // (c) cada una pulsa→sólida (validada) o se desvanece (descartada), 1:1 con los eventos reales
  R.oneToOne = {
    propuesta: eqMultiset(render.propose, evPropuesta),
    validando: eqMultiset(render.validating, evValidando),
    validada: eqMultiset(render.validated, evValidada),
    descartada: eqMultiset(render.discarded, evDescartada),
  };
  R.assert_c_validated = evValidada.length > 0 && R.oneToOne.validada && peak.validated > 0 && seen.vg === 1 && seen.vd === 1;
  R.assert_c_discarded = evDescartada.length > 0 && R.oneToOne.descartada && seen.dz === 1 &&
    seedNames.every((n) => evDescartada.includes(n));
  R.discardedNames = evDescartada;
  R.validatedNames = evValidada;
  // (d) modelo del Cuarto byte-idéntico antes/después de la coreografía
  R.assert_d_modelIntact = before.model === after.model && before.pieces === after.pieces &&
    before.relations === after.relations && before.placed === after.placed;

  // ════ ASSERT (e) · drag (F3) + gate (F5) intactos ════
  await page.evaluate(() => window.__cuarto.forge.clear());
  const dg = await page.evaluate(() => {
    const c = window.__cuarto;
    const cell = c.freeCell("fuentes");
    const placed = c.placeTile({ id: "vt1", key: "vt", label: "VTest", category: "read", atom: "tool", role: "fuentes" }, cell.gx, cell.gy);
    const hasIda = c.relations().some((x) => x.kind === "ida" && x.to === "vt1");
    const hasEco = c.relations().some((x) => x.kind === "eco" && x.from === "vt1");
    const dest = c.freeCell("fuentes") || cell;
    const moved = c.moveTile("vt1", dest.gx, dest.gy);                         // F3 (mismo camino que el drag)
    const idaAfterMove = c.relations().some((x) => x.kind === "ida" && x.to === "vt1");
    c.setGated("vt1", true);
    const hasGate = c.relations().some((x) => x.kind === "gate" && x.on === "vt1");  // F5 · candado sobre la línea
    const held = c.gateHold("vt1"); const isHeld = c.isGateHeld("vt1"); c.gateRelease("vt1");
    return { placed: !!placed, hasIda, hasEco, moved, idaAfterMove, hasGate, gateHeldApi: !!held, isHeld };
  });
  // F3 · drag REAL con el mouse (pointer path; caza errores de consola)
  const tile = await page.evaluate(() => {
    const c = window.__cuarto; const t = c.placedTiles()[0]; if (!t) return null;
    const p = c.viewPoint(t.gridX, t.gridY); const cv = c.app.canvas; const r = cv.getBoundingClientRect();
    const k = r.width / cv.width; return { x: r.left + p.x * k, y: r.top + (p.y - 30) * k };
  });
  if (tile) {
    await page.mouse.move(tile.x, tile.y); await page.mouse.down();
    await page.mouse.move(tile.x + 40, tile.y + 26, { steps: 8 });
    await page.mouse.move(tile.x + 72, tile.y + 44, { steps: 8 }); await page.mouse.up(); await sleep(200);
  }
  await shot("1a-07-drag-gate-intactos.png");
  R.dragGate = dg;
  R.assert_e = dg.placed && dg.hasIda && dg.hasEco && dg.moved && dg.idaAfterMove && dg.hasGate && dg.isHeld;

  R.errors = errors; R.console_clean = errors.length === 0;
  R.PASS = R.assert_a && R.assert_b && R.assert_c_validated && R.assert_c_discarded &&
    R.assert_d_modelIntact && R.assert_e && R.console_clean && R.run_ok && !R.degraded;
} catch (e) {
  R.fatal = String(e && e.stack || e); R.errors = errors;
}
console.log("RESULT_JSON_START");
console.log(JSON.stringify(R, null, 2));
console.log("RESULT_JSON_END");
await browser.close();
