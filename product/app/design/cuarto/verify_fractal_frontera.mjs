/* verify_fractal_frontera.mjs — D4 (muro-frontera VIVO + anti-grift) · headless, SIN backend (puerto 8105).
 *
 * Sirve product/app/design ESTÁTICO en :8105, stubea /v1/**. NO fabrica eventos in-page: REPLAYEA los
 * eventos ESTRUCTURALES REALES capturados por verify_frontera_d4.py (FakeBrain-sobre-motor-real →
 * frontera_d4_events.json) por el MISMO api de frontera viva que usa consumeLive (window.__cuartoReplayEvent).
 *
 * Prueba D4:
 *   · ANTES de replay el recinto NO está encendido (la luz viene de EVENTOS, no de animación in-page · §7e).
 *   · sub_agent_started(slug) REAL → el recinto de ESE slug enciende (running=true); portal/halo event-driven.
 *   · sub_agent_finished status=ok held=0 → se apaga (running=false) y marca CRUZÓ (bridge result · §1).
 *   · sub_agent_finished status=gate held>0 → "espera tu OK" (held=true).
 *   · ANTI-GRIFT keyeado en `degraded`: stream CLEAN → isDegraded=false (aunque sea fake-brain, no opus);
 *     stream DEGRADED → isDegraded=true (banner "no es el cerebro") → el flag FLIPEA.
 *   · §1 pertenencia: el bus B2 CRUZA el muro si es miembro (busCrosses); el CAJÓN nunca enciende;
 *     el _draw NO fabrica una memoria A3/RAG privada dentro del hijo (grift inverso · riesgo c).
 *   · 0 errores JS de página.
 * Run:  node verify_fractal_frontera.mjs   (requiere frontera_d4_events.json — corré antes verify_frontera_d4.py)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync, existsSync } from "node:fs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");             // product/app/design (para que ../theme.js resuelva)
const PORT = 8105;                                // libre (≠ 8080/8090/8091 de otras sesiones)
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const EVENTS_FILE = join(HERE, "frontera_d4_events.json");

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

if (!existsSync(EVENTS_FILE)) {
  console.error(`FALTA ${EVENTS_FILE} — corré primero:  python3 platform/assembler/deleg_fixtures/verify_frontera_d4.py`);
  process.exit(1);
}
const EVENTS = JSON.parse(readFileSync(EVENTS_FILE, "utf-8"));
const CLEAN = EVENTS.clean, HELD = EVENTS.held, DEG = EVENTS.degraded;
const only = (arr, type) => arr.filter((e) => e.type === type);

// ── static server (stdlib python) ────────────────────────────────────────────
const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

const drawOf = (id) => page.evaluate((i) => window.__cuarto.recintoDraw().find((r) => r.id === i) || null, id);
// drawRecintos vuelca _draw en el ticker (rAF, throttleado en headless) → POLL hasta que el frame PINTE
// el valor esperado. Prueba a la vez que drawRecintos CONSUMIÓ el estado vivo (el contrato medible), sin
// carrera de timing. Timeout → devuelve el último draw (la aserción falla limpia, no throw).
const waitDraw = async (id, key, val) => {
  try { await page.waitForFunction(({ i, k, v }) => { const r = window.__cuarto.recintoDraw().find((x) => x.id === i); return !!r && r[k] === v; }, { i: id, k: key, v: val }, { polling: 50, timeout: 4000 }); } catch {}
  return drawOf(id);
};
const feed = (evs) => page.evaluate((es) => es.map((e) => window.__cuartoReplayEvent(e)), evs);
const clearLive = () => page.evaluate(() => window.__cuarto.recintoLiveClear());

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection && window.__cuartoReplayEvent && window.__cuartoApplyFrontierEvent, null, { timeout: 10000 });

  // ── SEED · dos recintos-AGENTE (los slugs de los eventos capturados) + un CAJÓN de control ──────
  await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    // slug = basename(agent_ref) sin .json → matchea e.slug de los eventos REALES capturados.
    c.placeRecinto({ id: "agtClean", nucleo: true, agent_ref: "platform/assembler/deleg_fixtures/child_readonly_d4.json", gridX: 2, gridY: 2, w: 2, h: 2 },
      [{ id: "ac1", key: "ac1", label: "rd", category: "read" }]);
    c.placeRecinto({ id: "agtHeld", nucleo: true, agent_ref: "platform/assembler/deleg_fixtures/child_research.json", gridX: 6, gridY: 2, w: 2, h: 2 },
      [{ id: "ah1", key: "ah1", label: "wn", category: "write" }]);
    c.placeRecinto({ id: "cajX", gridX: 4, gridY: 6, w: 2, h: 2 },
      [{ id: "k1", key: "k1", label: "K1", category: "process" }]);
  });
  // esperá a que drawRecintos llene _draw REAL (hasNucleo poblado) — poll, no waitForTimeout ciego
  await page.waitForFunction(() => {
    const d = window.__cuarto.recintoDraw();
    return d.some((r) => r.id === "agtClean" && r.hasNucleo === true) && d.some((r) => r.id === "cajX");
  }, null, { polling: 60, timeout: 6000 });

  // ── FIX D (§9·D · anti-grift) · MAPEO ÚNICO evento→api: el SSE real de producción (consumeLive) y el
  // replay del harness llaman la MISMA función (__cuartoApplyFrontierEvent). Antes eran DOS copias y NINGÚN
  // test D4 ejercitaba consumeLive → un typo en el acople de campos shipeaba verde. Ahora TODO lo que este
  // harness afirma vía __cuartoReplayEvent corre el MISMO código que consumeLive. Acá probamos que el mapeo
  // compartido existe y que el acople status/held/result del sub_agent_finished vive en ESA función.
  const sharedMap = await page.evaluate(() => {
    if (typeof window.__cuartoApplyFrontierEvent !== "function") return { fn: false };
    const c = window.__cuarto; c.recintoLiveClear();
    c.recintoRun("agtClean", true);
    // driva la función COMPARTIDA directo (exactamente como consumeLive.onSubFinish) con un resolver fijo
    window.__cuartoApplyFrontierEvent("sub_agent_finished", { status: "gate", held: 1, result: "" }, () => "agtClean");
    const lv = c.recintoLiveState("agtClean");
    return { fn: true, held: !!(lv && lv.held), running: !!(lv && lv.running) };
  });
  await clearLive();
  ok(sharedMap.fn === true, "FIX D · existe el MAPEO ÚNICO window.__cuartoApplyFrontierEvent (consumeLive y replay lo comparten)");
  ok(sharedMap.held === true && sharedMap.running === false,
    "FIX D · el acople status:gate/held:1→held + apagar running vive en la función COMPARTIDA (un typo rompería consumeLive Y el replay)",
    JSON.stringify(sharedMap));

  // ── (0) ANTES de replay: NADA encendido (la luz viene de EVENTOS reales, no de animación in-page) ──
  const before = await drawOf("agtClean");
  ok(before && before.running === false && before.held === false && before.crossed === false,
    "PRE · antes de cualquier evento el recinto NO está encendido (la luz NO se fabrica in-page · §7e)",
    JSON.stringify({ running: before && before.running, held: before && before.held }));
  ok(before && before.portal === true && before.hasNucleo === true,
    "PRE · el recinto-agente tiene portal (pieza-mundo) y su muro está listo para encender");

  // ── (1) CLEAN · sub_agent_started REAL → enciende; finished ok/held0 → apaga + CRUZÓ ────────────
  await clearLive();
  await feed(only(CLEAN, "sub_agent_started"));
  const litRun = await waitDraw("agtClean", "running", true);
  ok(litRun && litRun.running === true,
    "CLEAN · sub_agent_started(child_readonly_d4) REAL → el MURO del recinto enciende (running=true)",
    JSON.stringify({ running: litRun && litRun.running }));
  // el CAJÓN nunca se enciende (un cajón no es un agente que corra)
  const cajLit = await drawOf("cajX");
  ok(cajLit && !cajLit.running && !cajLit.hasNucleo,
    "CLEAN · el CAJÓN NO enciende (running=false, no es agente) — la luz cae SÓLO en el recinto correcto");

  await feed(only(CLEAN, "sub_agent_finished"));
  const done = await waitDraw("agtClean", "running", false);
  ok(done && done.running === false && done.held === false && done.errored === false && done.crossed === true,
    "CLEAN · sub_agent_finished(status=ok,held=0) → se apaga (running=false) y marca CRUZÓ (bridge result · §1)",
    JSON.stringify({ running: done && done.running, held: done && done.held, crossed: done && done.crossed }));
  await feed([...only(CLEAN, "cost"), ...only(CLEAN, "final")]);
  const agClean = await page.evaluate(() => window.__cuarto.antiGrift());
  ok(agClean.isDegraded === false,
    "CLEAN · anti-grift isDegraded=false (degraded=null) — cerebro NO degradado…",
    JSON.stringify(agClean));
  ok(agClean.realBrain === false && /fake/i.test(String(agClean.modelFinal)),
    "CLEAN · …pero HONESTO: model_final='fake-brain' → realBrain=false (no se afirma opus)",
    JSON.stringify({ modelFinal: agClean.modelFinal, realBrain: agClean.realBrain }));
  const bannerClean = await page.evaluate(() => window.__antiGriftBanner.style.display);
  ok(bannerClean === "none", "CLEAN · el banner anti-grift está OCULTO (no hay degradación)");

  // ── (2) HELD · sub_agent_finished status=gate held>0 → "espera tu OK" ───────────────────────────
  await clearLive();
  await feed(only(HELD, "sub_agent_started"));
  const heldRun = await waitDraw("agtHeld", "running", true);
  ok(heldRun && heldRun.running === true, "HELD · sub_agent_started(child_research) REAL → enciende el recinto correcto");
  await feed(only(HELD, "sub_agent_finished"));
  const held = await waitDraw("agtHeld", "held", true);
  ok(held && held.held === true && held.running === false,
    "HELD · sub_agent_finished(status=gate,held=1) → el recinto queda en 'espera tu OK' (held=true)",
    JSON.stringify({ held: held && held.held, running: held && held.running }));
  // el recinto CLEAN no se contaminó (la luz cae por slug, no global)
  const cleanUntouched = await drawOf("agtClean");
  ok(cleanUntouched && cleanUntouched.held === false && cleanUntouched.running === false,
    "HELD · el OTRO recinto (agtClean) NO se contaminó (el estado cae por SLUG, no global)");

  // ── (3) DEGRADED · anti-grift FLIPEA (keyeado en el campo `degraded`, no en 'un modelo respondió') ─
  await clearLive();
  await feed(DEG);   // stream completo: notice(degraded) + cost(degraded) + sub_agent_* + final(degraded poblado)
  const agDeg = await page.evaluate(() => window.__cuarto.antiGrift());
  ok(agDeg.isDegraded === true,
    "DEGRADED · anti-grift isDegraded=true (degraded POBLADO) — el flag FLIPEA vs CLEAN (discriminación real)",
    JSON.stringify({ isDegraded: agDeg.isDegraded, modelFinal: agDeg.modelFinal }));
  ok("opus" !== String(agDeg.modelFinal).toLowerCase() && /qwen|oss/i.test(String(agDeg.modelFinal)),
    "DEGRADED · model_final HONESTO = OSS de fallback (NO opus)", JSON.stringify({ modelFinal: agDeg.modelFinal }));
  const bannerDeg = await page.evaluate(() => window.__antiGriftBanner.style.display);
  ok(bannerDeg === "block", "DEGRADED · el banner 'NO es el cerebro real' se MUESTRA");
  // el recinto degradado igual corrió y CRUZÓ (degradado ≠ roto): el árbol es estructural
  const degRec = await waitDraw("agtClean", "crossed", true);
  ok(degRec && degRec.crossed === true && degRec.runDegraded === true,
    "DEGRADED · el recinto igual CRUZÓ su resultado, y refleja runDegraded (run-level, cerebro del padre)",
    JSON.stringify({ crossed: degRec && degRec.crossed, runDegraded: degRec && degRec.runDegraded }));

  // ── (4) DISCRIMINACIÓN directa · re-alimentar CLEAN limpia el banner (el flag es reversible por run) ─
  await clearLive();
  await page.evaluate(() => window.__refreshAntiGrift());
  await feed([...only(CLEAN, "cost"), ...only(CLEAN, "final")]);
  await page.evaluate(() => window.__refreshAntiGrift());
  const agBack = await page.evaluate(() => window.__cuarto.antiGrift());
  ok(agBack.isDegraded === false,
    "DISCRIMINACIÓN · tras recintoLiveClear + re-feed CLEAN, isDegraded vuelve a false (keyeado en `degraded`)",
    JSON.stringify(agBack));

  // ── (5) §1 PERTENENCIA · bus B2 cruza si es miembro; sin fabricar aislamiento que el runtime no da ──
  // FIX C (§9·C · grift-inverso) · busCrosses ahora DERIVA del modelo (relación `comparte`), no de un
  // default. SIN pieza-memoria NO hay bus → busCrosses=false (antes era true FANTASMA en TODO recinto-
  // agente, contradiciendo el cable teal y el runtime que sólo emite recipe.memory con bloque memoria).
  const noMemDraw = await waitDraw("agtClean", "busCrosses", false);
  ok(noMemDraw && noMemDraw.busCrosses === false,
    "§1/FIX C · SIN pieza-memoria el bus B2 NO cruza (busCrosses=false) — el default fantasma corregido (no tautológico)",
    JSON.stringify({ busCrosses: noMemDraw && noMemDraw.busCrosses }));
  // colocar una pieza-MEMORIA de nivel superior → rebuildModel emite `comparte` a cada recinto-agente
  // miembro → AHORA el bus SÍ cruza (el cable teal y el campo medible concuerdan, ya no pueden discrepar).
  await page.evaluate(() => window.__cuarto.placeTile({ id: "mem1", key: "mem1", label: "Memoria", atom: "memoria" }, 4, 4));
  const memberDraw = await waitDraw("agtClean", "busCrosses", true);         // con memoria + miembro → cruza
  await page.evaluate(() => window.__cuarto.setSharesMemory("agtClean", false));
  const nonMemberDraw = await waitDraw("agtClean", "busCrosses", false);      // baja del bus → deja de cruzar
  await page.evaluate(() => window.__cuarto.setSharesMemory("agtClean", true));
  await waitDraw("agtClean", "busCrosses", true);                             // restaura
  const caj = await drawOf("cajX");
  const fabricatedInterior = await page.evaluate(() => {
    const r = window.__cuarto.recintoDraw().find((x) => x.id === "agtClean");
    return Object.keys(r).some((k) => /a3|rag|privateMem|corpus/i.test(k));   // grift inverso (riesgo c)
  });
  ok(memberDraw && memberDraw.busCrosses === true && nonMemberDraw && nonMemberDraw.busCrosses === false,
    "§1 · CON pieza-memoria el bus B2 CRUZA el muro SÓLO si el agente es miembro (busCrosses sigue la membresía teal)",
    JSON.stringify({ member: memberDraw && memberDraw.busCrosses, nonMember: nonMemberDraw && nonMemberDraw.busCrosses }));
  ok(caj && caj.busCrosses === false,
    "§1 · el CAJÓN no cruza bus (no es agente) — nada de compartir lo que no es suyo");
  ok(fabricatedInterior === false,
    "§1 · grift inverso EVITADO: el _draw NO fabrica memoria A3/RAG privada dentro del hijo (el runtime no la da)");

  // ── (6) mapeo de ERROR (unidad del front · vocabulario REAL 'error', sin run de error capturado) ──
  await page.evaluate(() => {
    const c = window.__cuarto; c.recintoLiveClear();
    c.recintoRun("agtClean", true);
    c.recintoFinish("agtClean", { status: "error", held: 0, result: "" });
  });
  const errMap = await waitDraw("agtClean", "errored", true);
  ok(errMap && errMap.errored === true && errMap.running === false && errMap.crossed === false,
    "MAPEO · sub_agent_finished(status=error) → errored=true (tinte rojo), sin cruce (unidad del front)",
    JSON.stringify({ errored: errMap && errMap.errored, crossed: errMap && errMap.crossed }));

  // ── 0 errores JS/render de página ──
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e);
  fails.push("harness: " + e.message);
} finally {
  await browser.close();
  server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — D4 (muro-frontera vivo con eventos REALES + anti-grift) verificada"));
process.exit(fails.length ? 1 : 0);
