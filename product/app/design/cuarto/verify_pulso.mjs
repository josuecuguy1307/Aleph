/* verify_pulso.mjs — EL PULSO en RUN · A (ida) + B (match función-exacto) + C (ritmo wall_s).
 *
 * DOS capas de verificación:
 *   1) MECÁNICA (headless, SIN backend, puerto ≠ :8091): maneja el api del Cuarto y el camino REAL
 *      de consumeLive con un stream SSE CONTROLADO (page.route fulfilea text/event-stream con eventos
 *      de forma exacta del contrato Motor B). NO fabrica ecos en el producto: alimenta EVENTOS al
 *      consumidor y verifica que el render responde 1:1 (que es justo lo que un test debe hacer).
 *   2) REAL (aparte, scripts/run_pulso_real.mjs): la corrida con Opus vía shim :8923, tool_calls>0
 *      reales. Esa es la prueba anti-grift final; este archivo prueba la MECÁNICA determinística.
 *
 * A · tool_call_started → destello Núcleo→tool (ecoFireSpark) · tool_call_finished → destello
 *     tool→Núcleo (ecoReturn) · tile FRENADO (gate) NO dispara ida.
 * B · varias tools del mismo server → cada destello cae en el cable EXACTO de su función (no en otra
 *     del mismo server) · conteo 100% honesto (N destellos = N tool_calls).
 * C · la duración del eco refleja wall_s (clamp 200ms–2s): una tool lenta da un destello más largo.
 *
 * Run:  node verify_pulso.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8108;                                // ≠ :8091 y ≠ otros verify
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

// dos tools del MISMO server (para B) + una tercera de otro server
const TOOLS = [
  { id: "t_search", key: "t_search", label: "Buscar película", category: "read", atom: "tool", server: "tmdb", tools: ["search_movie"] },
  { id: "t_detail", key: "t_detail", label: "Detalle película", category: "read", atom: "tool", server: "tmdb", tools: ["get_movie_details"] },
  { id: "t_weather", key: "t_weather", label: "Clima", category: "read", atom: "tool", server: "open-meteo", tools: ["get_weather"] },
];

// ── stream SSE controlado: arma el body text/event-stream EXACTO del contrato (id/event/data) ──
function sseBody(frames) {
  let id = 0, out = "";
  for (const f of frames) { id++; out += `id: ${id}\nevent: ${f.type}\ndata: ${JSON.stringify(f)}\n\n`; }
  return out;
}

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
const shot = async (name) => { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); };

// default: catálogo vacío para todo /v1/** (las rutas específicas del run se sobre-escriben por test)
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  // siembro las 3 tools y reencuadro
  const placed = await page.evaluate((TOOLS) => {
    const c = window.__cuarto;
    TOOLS.forEach((t) => c.placeTile(t));   // sin coords → balancedFreeCell
    return c.placedTiles().map((t) => ({ id: t.id, server: t.server, tools: t.tools }));
  }, TOOLS);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(250);
  ok(placed.length === 3, "3 tools sembradas (2 del MISMO server tmdb + 1 open-meteo)", `placed=${placed.length}`);

  // ╔══ A · DESTELLO DE IDA + ECO (api directo, geometría desde el log) ══════════════════════════╗
  const A = await page.evaluate(async () => {
    const c = window.__cuarto;
    c.setRunning(true);                 // limpia gateState + _ecoLog
    await c.ecoFireSpark("t_search");   // IDA: Núcleo → tool
    await c.ecoReturn("t_search");      // ECO: tool → Núcleo
    return c.ecoLog();
  });
  ok(A.length === 2 && A[0].dir === "ida" && A[1].dir === "eco",
     "A · started→ida, finished→eco (en orden)", `log=${A.map((e) => e.dir).join(",")}`);
  const ida = A.find((e) => e.dir === "ida"), eco = A.find((e) => e.dir === "eco");
  ok(ida && eco && dist(ida.from, eco.to) < 2 && dist(ida.to, eco.from) < 2,
     "A · la IDA viaja Núcleo→tool y el ECO viaja tool→Núcleo (extremos espejados)",
     ida && eco ? `idaΔ(from,ecoTo)=${dist(ida.from, eco.to).toFixed(1)} idaΔ(to,ecoFrom)=${dist(ida.to, eco.from).toFixed(1)}` : "");
  ok(ida && dist(ida.from, ida.to) > 30, "A · el destello de ida RECORRE el cable (no es de largo cero)",
     ida ? `len=${dist(ida.from, ida.to).toFixed(0)}px` : "");

  // captura del destello de ida en vuelo (violeta sobre el cable)
  await page.evaluate(() => { window.__cuarto.setRunning(true); window.__cuarto.ecoFireSpark("t_detail"); });
  await page.waitForTimeout(110);
  await shot("pulso-A-ida-en-vuelo.png");

  // A · tile FRENADO no dispara ida
  const held = await page.evaluate(async () => {
    const c = window.__cuarto;
    c.setRunning(true);
    c.gateHold("t_search");             // frená la tool (gateState=held)
    const before = c.ecoLog().length;
    await c.ecoFireSpark("t_search");   // NO debe salir ida
    const after = c.ecoLog().length;
    c.gateRelease("t_search"); c.gateClearAll();
    return { before, after };
  });
  ok(held.after === held.before, "A · una tool FRENADA (gate held) NO dispara destello de ida", `log ${held.before}→${held.after}`);

  await page.evaluate(() => window.__cuarto.setRunning(false));   // soltá el running de los tests A (si no, ▶ RUN early-returns)

  // ╔══ B · MATCH FUNCIÓN-EXACTO + concurrencia (camino REAL: consumeLive ← SSE controlado) ═══════╗
  // Dos tools del MISMO server (tmdb): get_movie_details→t_detail, search_movie→t_search. Eventos
  // INTERCALADOS (start c1, start c2, finish c1, finish c2) → el eco de c1 DEBE volver a t_detail
  // (su par por call_id), NO al último started (t_search). Posicional caería en el tile equivocado.
  const RUN_ID = "r_pulsoB";
  const frames = [
    { type: "tool_call_started",  call_id: "c1", tool: "get_movie_details" },
    { type: "tool_call_started",  call_id: "c2", tool: "search_movie" },
    { type: "tool_call_finished", call_id: "c1", tool: "get_movie_details", wall_s: 0.3 },
    { type: "tool_call_finished", call_id: "c2", tool: "search_movie", wall_s: 0.3 },
    { type: "closed", ok: true, run_id: RUN_ID, model_final: "stub-verify" },
  ];
  // rutas específicas DESPUÉS del default → ganan (Playwright matchea en orden inverso de registro)
  await page.route("**/v1/runs/enqueue", (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ job_id: "j_pulsoB", run_id: RUN_ID }) }));
  await page.route("**/v1/spaces/*/stream*", (route) => route.fulfill({ status: 200, contentType: "text/event-stream", headers: { "cache-control": "no-cache" }, body: sseBody(frames) }));

  await page.evaluate(() => { window.__ecoTools = undefined; });
  // [Cuarto entrega, no corre] el Cuarto ya no tiene botón de Ejecutar: correr es de La Sala.
  // El PIPELINE quedó intacto y sigue siendo lo que esta vara prueba — se dispara por código.
  await page.evaluate((p) => window.__ejecutarTurno(p), 'corre una tarea de ejemplo');
  await page.waitForFunction(() => window.__ecoTools !== undefined, null, { timeout: 15000 }).catch(() => {});
  const B = await page.evaluate(() => ({ tools: window.__ecoTools, log: window.__cuarto.ecoLog() }));
  await shot("pulso-B-run-stub.png");

  ok(B.tools === 2, "B · conteo HONESTO: N destellos = N tool_calls reales (2)", `__ecoTools=${B.tools}`);
  const ev = B.log || [];
  const idaSeq = ev.filter((e) => e.dir === "ida").map((e) => e.tileId);
  const ecoSeq = ev.filter((e) => e.dir === "eco").map((e) => e.tileId);
  // función-exacto: la 1ª ida (get_movie_details) cae en t_detail. Posicional daría t_search (1º de la cola).
  ok(idaSeq[0] === "t_detail", "B · función-exacto: get_movie_details→t_detail (NO el 1º de la cola del server)", `ida=[${idaSeq.join(",")}]`);
  ok(idaSeq[1] === "t_search", "B · función-exacto: search_movie→t_search", `ida=[${idaSeq.join(",")}]`);
  // call_id: el eco de c1 (get_movie_details) vuelve a t_detail aunque el ÚLTIMO started fue t_search
  ok(ecoSeq[0] === "t_detail" && ecoSeq[1] === "t_search",
     "B · call_id: con starts intercalados cada ECO vuelve a SU tile (no al último)", `eco=[${ecoSeq.join(",")}]`);
  ok(idaSeq.length === 2 && ecoSeq.length === 2, "B · ningún destello fabricado de más (2 ida + 2 eco exactos)", `ida=${idaSeq.length} eco=${ecoSeq.length}`);
  await page.unroute("**/v1/runs/enqueue");
  await page.unroute("**/v1/spaces/*/stream*");

  // ╔══ C · RITMO REAL desde wall_s (la duración del eco refleja la latencia real, clamp 200ms–2s) ══╗
  const C = await page.evaluate(() => {
    const c = window.__cuarto;
    const dur = (wall_s) => { c.setRunning(true); c.ecoReturn("t_weather", wall_s); return c.ecoLog().find((e) => e.dir === "eco").dur; };
    return { fast: dur(0.1), slow: dur(5), mid: dur(0.8), none: dur(undefined) };
  });
  ok(C.slow > C.fast, "C · una tool LENTA da un destello MÁS LARGO que una rápida", `lenta=${C.slow}ms rápida=${C.fast}ms`);
  ok(C.fast === 200 && C.slow === 2000, "C · clamp sano: 0.1s→200ms (min), 5s→2000ms (max) — ni invisible ni eterno", `min=${C.fast} max=${C.slow}`);
  ok(C.mid === 800, "C · proporcional dentro del rango: 0.8s→800ms", `mid=${C.mid}ms`);
  ok(C.none === 520, "C · sin wall_s (cosmético/playEco) → duración fija de antes (520ms)", `default=${C.none}ms`);

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — PULSO A+B+C verificados (ida·eco · tile frenado sin ida · función-exacto + call_id · conteo honesto · ritmo wall_s clampado)"));
process.exit(fails.length ? 1 : 0);
