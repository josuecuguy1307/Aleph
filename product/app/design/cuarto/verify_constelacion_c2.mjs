/* verify_constelacion_c2.mjs — CONSTELACIÓN (capa 3) · C2 = BRILLO POR RELEVANCIA (doc §12).
 * Headless, SIN backend (puerto ≠ :8091). El grado crudo es PLANO para tools (modelo estrella) → la
 * relevancia se DERIVA de las señales ricas: nº de hijos del recinto + fan-out de la conexión. Prueba:
 *   (A) relevancia ORDENADA: recinto con 3 hijos > recinto con 1 hijo; conexión que habilita 3 > 1; tool suelta = 0;
 *   (B) el HALO del agente FOLDA la relevancia (más hijos → halo más intenso; supera el techo sin-relevancia 0.50);
 *   (C) el Núcleo NO recibe relevancia (sigue mandando como hub, intacto);
 *   (D) el HOVER-GLOW sigue vivo e INDEPENDIENTE de la relevancia (pulse sube n.glow; relevancia no usa ese canal);
 *   (E) REGRESIÓN: escena de tools planas → toda relevancia = 0 (sin recintos ni fan-out, idéntico a hoy);
 *   (F) theme claro/oscuro OK + captura. Falla si hay error JS.
 * Run:  node verify_constelacion_c2.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8100;                                // ≠ :8091
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
const shotCanvas = async (name) => { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); };

// siembra la escena de RELEVANCIA (in-page): recinto grande(3) vs chico(1), conexión fan-out 3 vs 1, tool suelta(0).
function buildRelevanceScene() {
  const c = window.__cuarto;
  c.placedTiles().forEach((t) => c.removeTile(t.id));
  c.placeRecinto({ id: "big", label: "Agente Grande", nucleo: true, agent_ref: "a/big", gridX: 0, gridY: 4, w: 2, h: 2 },
    [{ id: "b1", key: "b1", label: "b1", category: "read" }, { id: "b2", key: "b2", label: "b2", category: "process" }, { id: "b3", key: "b3", label: "b3", category: "write" }]);
  c.placeRecinto({ id: "small", label: "Agente Chico", nucleo: true, agent_ref: "a/small", gridX: 5, gridY: 4, w: 2, h: 2 },
    [{ id: "s1", key: "s1", label: "s1", category: "read" }]);
  c.placeTile({ id: "cxBig", key: "cxBig", label: "Conexión Grande", atom: "conexion", server: "svc1" }, 2, 1);
  c.placeTile({ id: "e1", key: "e1", label: "e1", category: "read", server: "svc1" }, 3, 2);
  c.placeTile({ id: "e2", key: "e2", label: "e2", category: "process", server: "svc1" }, 4, 2);
  c.placeTile({ id: "e3", key: "e3", label: "e3", category: "write", server: "svc1" }, 4, 3);
  c.placeTile({ id: "cxSmall", key: "cxSmall", label: "Conexión Chica", atom: "conexion", server: "svc2" }, 6, 1);
  c.placeTile({ id: "f1", key: "f1", label: "f1", category: "read", server: "svc2" }, 6, 2);
  c.placeTile({ id: "lone", key: "lone", label: "lone", category: "process", server: "svc3" }, 2, 3);
  return c.relevance();
}

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  const REL = await page.evaluate(buildRelevanceScene);
  await page.waitForTimeout(150);

  // ╔══ A · relevancia ORDENADA por señales ricas (no grado crudo, que es plano) ═════════════════╗
  ok(REL.big === 0.6 && REL.small === 0.2 && REL.big > REL.small,
    "A · recinto con 3 hijos (0.6) brilla MÁS que con 1 hijo (0.2)", `big=${REL.big} small=${REL.small}`);
  ok(REL.cxBig === 0.6 && REL.cxSmall === 0.2 && REL.cxBig > REL.cxSmall,
    "A · conexión que habilita 3 tools (0.6) > la que habilita 1 (0.2) — fan-out", `cxBig=${REL.cxBig} cxSmall=${REL.cxSmall}`);
  ok(REL.lone === 0 && REL.e1 === 0 && REL.b1 === 0,
    "A · tool suelta y tools habilitadas = 0 (grado plano en la estrella; honesto, sin brillo inventado)");

  // ╔══ C · el Núcleo NO recibe relevancia (sigue siendo el hub, intacto) ════════════════════════╗
  ok(!("nucleo" in REL), "C · el Núcleo NO está en el mapa de relevancia (su brillo de hub queda intacto)");

  // ╔══ B · el HALO del agente FOLDA la relevancia (más hijos → más intenso; supera 0.50 sin-relevancia) ══╗
  const N = 16; const bigA = [], smallA = [];
  for (let i = 0; i < N; i++) {
    const s = await page.evaluate(() => { const d = window.__cuarto.recintoDraw();
      const b = d.find((x) => x.id === "big"), s = d.find((x) => x.id === "small"); return { b: b.haloAlpha, s: s.haloAlpha, br: b.relevance, sr: s.relevance }; });
    bigA.push(s.b); smallA.push(s.s); await page.waitForTimeout(180);
  }
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length, maxA = (a) => Math.max(...a);
  ok(mean(bigA) > mean(smallA), `B · halo PROMEDIO del agente grande > chico (${mean(bigA).toFixed(3)} > ${mean(smallA).toFixed(3)})`);
  ok(maxA(bigA) > 0.55, `B · el halo del grande SUPERA el techo sin-relevancia (max ${maxA(bigA).toFixed(3)} > 0.55; pulse solo tope 0.50 → la relevancia está foldeada)`);
  const haloVaries = maxA(bigA) - Math.min(...bigA) > 0.02;
  ok(haloVaries, "B · el halo SIGUE LATIENDO (no se congela): la relevancia es ADITIVA al pulso del Núcleo");

  // ╔══ D · el HOVER-GLOW sigue vivo e INDEPENDIENTE de la relevancia ════════════════════════════╗
  const D = await page.evaluate(() => {
    const c = window.__cuarto;
    const before = c.nodeGlow("lone");           // suelta, relevancia 0 → glow base ~0
    c.pulse("lone");                             // simula hover/selección
    const after = c.nodeGlow("lone");            // mismo evaluate: el ticker no decae entre pulse y lectura
    const relevantGlow = c.nodeGlow("cxBig");    // relevante pero NO pulsada → su glow (canal hover) sigue ~0
    return { before, after, relevantGlow };
  });
  ok(D.after > 1 && D.after > D.before, `D · pulse() SUBE el hover-glow de una pieza sin relevancia (${D.before.toFixed(2)}→${D.after.toFixed(2)}) — el hover sigue vivo`);
  ok(D.relevantGlow < 0.3, `D · una pieza RELEVANTE no pulsada tiene glow~0 (${D.relevantGlow.toFixed(2)}): relevancia y hover son canales SEPARADOS`);

  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(300); await shotCanvas("constelacion-c2-relevancia-dark.png");

  // ╔══ E · REGRESIÓN: tools planas (sin recinto ni fan-out) → toda relevancia = 0 ═══════════════╗
  const FLAT = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeTile({ id: "p1", key: "p1", label: "P1", category: "read" }, 4, 3);
    c.placeTile({ id: "p2", key: "p2", label: "P2", category: "process" }, 5, 3);
    return { rel: c.relevance(), recintoDraw: c.recintoDraw() };
  });
  ok(Object.values(FLAT.rel).every((v) => v === 0) && FLAT.recintoDraw.length === 0,
    "E · escena de tools planas → relevancia 0 en TODO + sin recintos (tickTile/drawRecintos byte-idéntico a hoy)", JSON.stringify(FLAT.rel));

  // ╔══ F · theme claro/oscuro OK ════════════════════════════════════════════════════════════════╗
  await page.evaluate(buildRelevanceScene); await page.waitForTimeout(150);
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light"); window.__cuarto.setTheme("light"); window.__cuarto.cam.fit(); });
  await page.waitForTimeout(300); await shotCanvas("constelacion-c2-relevancia-light.png");
  const lightRel = await page.evaluate(() => window.__cuarto.relevance().big);
  ok(lightRel === 0.6, "F · en theme CLARO la relevancia se computa igual (big=0.6) sin error");

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — C2 (brillo por relevancia) verificada"));
process.exit(fails.length ? 1 : 0);
