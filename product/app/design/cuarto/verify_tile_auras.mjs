/* verify_tile_auras.mjs — PULSO+TABLERO · AURA DE ESTADO sobre las piezas del Cuarto (§2 · mapa vivo).
 *
 * Headless, SIN backend (puerto 8107). Sirve product/app/design ESTÁTICO, stubea /v1/**. NO fabrica auras
 * in-page: DRIVEA los MISMOS eventos que el run real (tool_call_started/finished, gate_waiting) por el MAPEO
 * COMPARTIDO de producción (window.__cuartoApplyFrontierEvent, el mismo que consumeLive llama con el id ya
 * resuelto). Prueba el contrato de honestidad de §2/§3:
 *   1. tool_call_started → aura 'calling'; tool_call_finished(ok) → 'done'; gate_waiting → 'held'.
 *   2. HONESTO: tool_call_finished SIN status de falla NUNCA da 'error' (el backend emite status:"ok"
 *      siempre); 'error' sólo aparece si el evento REAL trae status:"error"/ok:false.
 *   3. El estado llega al DIBUJO real (el HIJO Graphics: tileAura().has && .visible) — diff evento↔dibujo = 0.
 *   4. setRunning(true) LIMPIA todas las auras (no persisten stale entre runs).
 *   5. NO doble-anillo: un id de recinto-AGENTE (que lleva su halo en drawRecintos) es RECHAZADO por tileState.
 *   6. Sin estado → sin aura (byte-idéntico); 0 errores JS de página (drawTileAuras no tira).
 *   7. El pulso existente sigue vivo: ecoFire crece el ecoLog (glow/eco intactos).
 *
 * Run:  node verify_tile_auras.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");                 // product/app/design (para que ../theme.js resuelva)
const PORT = 8107;                                    // libre (≠ 8080/8090/8091/8105 de otras sesiones)
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const SHOTS = join(HERE, "screenshots");

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 820 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

// drawTileAuras vuelca el HIJO Graphics en el ticker (rAF, throttleado en headless) → POLL hasta que el
// frame PINTE (aura visible) el estado esperado. Prueba a la vez que drawTileAuras CONSUMIÓ el estado vivo.
const auraOf = (id) => page.evaluate((i) => window.__cuarto.tileAura(i), id);
const stateOf = (id) => page.evaluate((i) => window.__cuarto.tileLiveState(i), id);
const waitAura = async (id, state) => {
  try { await page.waitForFunction(({ i, s }) => { const a = window.__cuarto.tileAura(i); return !!a && a.visible && a.state === s; }, { i: id, s: state }, { polling: 40, timeout: 4000 }); } catch {}
  return auraOf(id);
};
// DRIVE por el MAPEO COMPARTIDO de producción (mismo código que consumeLive), con el id resuelto explícito.
const drive = (type, e, id) => page.evaluate(({ ty, ev, i }) => window.__cuartoApplyFrontierEvent(ty, ev, () => i), { ty: type, ev: e, i: id });

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__cuartoApplyFrontierEvent && window.__cuarto.tileState && window.__cuarto.tileAura, null, { timeout: 10000 });

  // ── SEED · una PIEZA PLANA (tool, keyless) + un recinto-AGENTE de control ──────────────────────
  const seed = await page.evaluate(() => {
    const c = window.__cuarto;
    const t = c.placeTile({ id: "toolA", key: "toolA", label: "Herramienta", server: "demo", category: "mesa", tools: ["run_demo"] });
    const ag = c.placeRecinto({ id: "agtX", label: "Sub-agente", nucleo: true, agent_ref: "packs/x.config.json" }, []);
    return { tile: t && t.id, tileKind: c.pieceData("toolA") ? "tile" : null, agent: ag && ag.id, agentHasNucleo: ag && ag.hasNucleo };
  });
  await page.evaluate(() => window.__cuarto.cam.fit());
  ok(seed.tile === "toolA", "seed · pieza plana kind:'tile' colocada (toolA)", `tile=${seed.tile}`);
  ok(seed.agent === "agtX" && seed.agentHasNucleo === true, "seed · recinto-AGENTE de control colocado (agtX)", `agent=${seed.agent}`);

  // ── 0) SIN evento → SIN aura (byte-idéntico) ──────────────────────────────────────────────────
  const a0 = await auraOf("toolA");
  ok(a0 && a0.state === null && a0.has === false, "0 · sin evento → sin aura (state=null, has=false) — dibujo byte-idéntico", JSON.stringify(a0));

  // ── 1) tool_call_started → 'calling' (aura violeta, ida) ──────────────────────────────────────
  await drive("tool_call_started", { call_id: 1, tool: "demo", tool_raw: "run_demo" }, "toolA");
  const aCall = await waitAura("toolA", "calling");
  ok((await stateOf("toolA"))?.state === "calling", "1 · tool_call_started → tileLive 'calling'");
  ok(aCall && aCall.has && aCall.visible && aCall.state === "calling", "1 · el estado LLEGA al dibujo (hijo Graphics visible) — diff evento↔dibujo=0", `r=${aCall && aCall.r}`);
  await page.screenshot({ path: join(SHOTS, "tile-aura-calling.png") }).catch(() => {});

  // ── 2) tool_call_finished(status:ok) → 'done' (teal), NUNCA 'error' sin falla real ────────────
  await drive("tool_call_finished", { call_id: 1, tool: "demo", tool_raw: "run_demo", status: "ok", result: "42" }, "toolA");
  const aDone = await waitAura("toolA", "done");
  ok((await stateOf("toolA"))?.state === "done", "2 · tool_call_finished(status:ok) → 'done' (NO 'error')");
  ok(aDone && aDone.visible && aDone.state === "done", "2 · 'done' llega al dibujo");

  // resultado que "parece" error PERO status ok → SIGUE 'done' (no fabricamos error de un string)
  await drive("tool_call_finished", { call_id: 2, tool: "demo", tool_raw: "run_demo", status: "ok", result: "Error: algo salió mal en el texto" }, "toolA");
  await page.waitForTimeout(120);
  ok((await stateOf("toolA"))?.state === "done", "2b · result con la palabra 'Error' pero status:ok → SIGUE 'done' (honestidad: no se infiere error del texto)");

  // ── 3) 'error' SÓLO con status de falla REAL (hoy no lo emite el backend para piezas planas) ──
  await drive("tool_call_finished", { call_id: 3, tool: "demo", tool_raw: "run_demo", status: "error", error: "boom" }, "toolA");
  await page.waitForTimeout(120);
  ok((await stateOf("toolA"))?.state === "error", "3 · tool_call_finished(status:error) → 'error' (sólo con evento de falla REAL)");

  // ── 4) gate_waiting → 'held' (ámbar) ──────────────────────────────────────────────────────────
  await drive("gate_waiting", { call_id: 4, tool: "demo", tool_raw: "run_demo", gate_action: "needs_ok" }, "toolA");
  const aHeld = await waitAura("toolA", "held");
  ok((await stateOf("toolA"))?.state === "held", "4 · gate_waiting → 'held'");
  ok(aHeld && aHeld.visible && aHeld.state === "held", "4 · 'held' llega al dibujo");
  await page.screenshot({ path: join(SHOTS, "tile-aura-held.png") }).catch(() => {});

  // ── 5) NO doble-anillo: un id de recinto-AGENTE es RECHAZADO por tileState ─────────────────────
  const agentGuard = await page.evaluate(() => {
    const c = window.__cuarto;
    const applied = c.tileState("agtX", "calling");   // debe RECHAZAR (kind:'recinto', no 'tile')
    return { applied, live: c.tileLiveState("agtX") };
  });
  ok(agentGuard.applied === false && agentGuard.live === null, "5 · NO doble-anillo: tileState RECHAZA el recinto-agente (kind-guard) → sin aura sobre el halo", JSON.stringify(agentGuard));

  // ── 6) setRunning(true) LIMPIA las auras (no stale entre runs) ────────────────────────────────
  await page.evaluate(() => window.__cuarto.setRunning(true));
  const cleared = await page.evaluate(() => ({ tool: window.__cuarto.tileLiveState("toolA"), aura: window.__cuarto.tileAura("toolA") }));
  await page.evaluate(() => window.__cuarto.setRunning(false));
  ok(cleared.tool === null, "6 · setRunning(true) LIMPIA tileLive (aura no persiste stale entre runs)");
  await page.waitForTimeout(120);
  const aAfter = await auraOf("toolA");
  ok(aAfter && aAfter.visible === false, "6 · tras limpiar, el HIJO Graphics queda OCULTO (visible=false)");

  // ── 7) el PULSO existente sigue vivo (glow/eco intactos): ecoFire crece el ecoLog ─────────────
  const eco = await page.evaluate(() => {
    window.__cuarto.setRunning(true);
    const before = window.__cuarto.ecoLog().length;
    window.__cuarto.ecoFireSpark("toolA");
    return { before, after: window.__cuarto.ecoLog().length };
  });
  await page.evaluate(() => window.__cuarto.setRunning(false));
  ok(eco.after > eco.before, "7 · el pulso existente sigue vivo (ecoFireSpark crece el ecoLog — glow/eco no se rompieron)", `ecoLog ${eco.before}→${eco.after}`);

  // ── 8) 0 errores JS/render (drawTileAuras corrió sin tirar en cada frame con estado) ──────────
  const real = errors.filter((e) => !/Failed to load resource|favicon|net::ERR/i.test(e));
  ok(real.length === 0, "8 · 0 errores JS de página (drawTileAuras no tira)", real.length ? "\n  " + real.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — AURA DE ESTADO honesta (evento REAL → estado → dibujo; error sólo con falla real; limpia en setRunning; sin doble-anillo; pulso intacto)"));
process.exit(fails.length ? 1 : 0);
