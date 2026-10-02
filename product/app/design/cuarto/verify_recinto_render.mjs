/* verify_recinto_render.mjs — sub-rama 2 (recinto-render) · headless, SIN backend (puerto ≠ :8091).
 *
 * El recinto por fin SE DIBUJA. Prueba: (A) agente→muro+halo, cajón→muro sin halo (distinguibles);
 * (B) el halo LATE (pulsa); (C) cable de hijo OCULTO converge a la caja; (D) el muro rota con la sala;
 * (E) REGRESIÓN: escena sin recintos → recintoDraw() vacío + modelo idéntico. Capturas agente/cajón/
 * rotado/light/dark. Falla si hay error JS. Run:  node verify_recinto_render.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8098;                                // ≠ :8091
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const NUCLEO_VIOLET = 0xb389ff, CAJON_NEUTRAL = 0x8893a7;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

const reset = () => page.evaluate(() => window.__cuarto.placedTiles().forEach((t) => window.__cuarto.removeTile(t.id)));
const shotCanvas = async (name) => { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); };

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  // ╔══ E · REGRESIÓN (escena SIN recintos = idéntica + recintoDraw vacío) ════════════════════════╗
  const E = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeTile({ id: "t1", key: "t1", label: "T1", category: "process" }, 4, 3);
    c.placeTile({ id: "ctx1", key: "ctx1", label: "Ctx", atom: "contexto" }, 5, 3);
    const m = c.relationModel();
    return { pieces: m.pieces, rels: m.relationships, recintoDraw: c.recintoDraw(), anyParentId: m.pieces.some((p) => "parentId" in p) };
  });
  ok(eq(E.pieces, [{ id: "nucleo", type: "nucleo", role: null }, { id: "t1", type: "tool", role: "mesa" }, { id: "ctx1", type: "contexto", role: null }])
    && !E.anyParentId, "E · escena sin recinto: pieces/relationships IDÉNTICAS, sin parentId");
  ok(eq(E.rels, [{ kind: "ida", from: "nucleo", to: "t1" }, { kind: "eco", from: "t1", to: "nucleo" }, { kind: "permanent", from: "ctx1", to: "nucleo" }]),
    "E · relationships de capa 2 intactas (ida+eco+permanent)");
  ok(eq(E.recintoDraw, []), "E · sin recintos → recintoDraw() vacío (drawRecintos no dibuja nada)");

  // ╔══ A · agente (muro+halo) vs cajón (muro sin halo) — distinguibles de un vistazo ═════════════╗
  await reset();
  await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeRecinto({ id: "agt", nucleo: true, agent_ref: "a/x", gridX: 2, gridY: 2, w: 2, h: 2 },
      [{ id: "a1", key: "a1", label: "A1", category: "read" }]);
    c.placeRecinto({ id: "caj", gridX: 6, gridY: 5, w: 2, h: 2 },
      [{ id: "k1", key: "k1", label: "K1", category: "process" }, { id: "k2", key: "k2", label: "K2", category: "write" }]);
  });
  await page.waitForTimeout(150);                                  // deja correr un tick → drawRecintos llena _draw (params REALES)
  const A = await page.evaluate(() => { const d = window.__cuarto.recintoDraw();
    return { agt: d.find((x) => x.id === "agt"), caj: d.find((x) => x.id === "caj") }; });
  ok(A.agt && A.agt.hasNucleo === true && A.agt.haloActive === true && A.agt.wallColor === NUCLEO_VIOLET,
    "A · AGENTE → muro violeta + halo activo", JSON.stringify(A.agt));
  ok(A.caj && A.caj.hasNucleo === false && A.caj.haloActive === false && A.caj.wallColor === CAJON_NEUTRAL,
    "A · CAJÓN → muro neutro, SIN halo", JSON.stringify(A.caj));
  ok(A.agt.wallColor !== A.caj.wallColor && A.agt.haloActive !== A.caj.haloActive,
    "A · agente y cajón se distinguen (color de muro + presencia de halo)");

  // ╔══ B · el HALO LATE (pulsa con el tiempo); el cajón nunca ═══════════════════════════════════╗
  const sample = () => page.evaluate(() => { const d = window.__cuarto.recintoDraw();
    return { agt: d.find((x) => x.id === "agt").haloAlpha, caj: d.find((x) => x.id === "caj").haloAlpha }; });
  const s0 = await sample(); await page.waitForTimeout(280); const s1 = await sample(); await page.waitForTimeout(280); const s2 = await sample();
  const spread = Math.max(s0.agt, s1.agt, s2.agt) - Math.min(s0.agt, s1.agt, s2.agt);
  ok(spread > 0.02, `B · el halo del agente LATE (haloAlpha varía ${s0.agt.toFixed(2)}→${s1.agt.toFixed(2)}→${s2.agt.toFixed(2)})`);
  ok(s0.caj === 0 && s1.caj === 0 && s2.caj === 0, "B · el cajón NUNCA late (haloAlpha=0 siempre)");
  await page.evaluate(() => window.__cuarto.cam.fit());
  await page.waitForTimeout(200); await shotCanvas("recinto-2-agente-vs-cajon.png");

  // ╔══ C · cable de hijo OCULTO converge a la CAJA (no cuelga al fantasma) ══════════════════════╗
  const C = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "agtC", nucleo: true, agent_ref: "a/c", gridX: 3, gridY: 3, w: 2, h: 2 },
      [{ id: "c1", key: "c1", label: "C1", category: "read" }, { id: "c2", key: "c2", label: "C2", category: "process" }]);
    const dist = (a, b) => (a && b ? Math.hypot(a.x - b.x, a.y - b.y) : Infinity);
    const beforeD = dist(c.screenPointOf("c1"), c.screenPointOf("agtC")); // visible: lejos de la caja
    c.setRecintoCollapsed("agtC", true);                                  // colapsar → hijos ocultos (sub-rama 3: footprint → 1×1)
    // NOTA: la sub-rama 3 encoge el footprint a 1×1 al colapsar, así que el centro de la caja se mueve.
    // El cable converge al centro VIVO de la caja → re-leemos screenPointOf("agtC") DESPUÉS de colapsar.
    const afterD = dist(c.screenPointOf("c1"), c.screenPointOf("agtC"));
    return { beforeD, afterD };
  });
  ok(C.beforeD > 5, `C · hijo VISIBLE: su extremo está en su celda, lejos de la caja (${C.beforeD.toFixed(1)}px)`);
  ok(C.afterD < 1, `C · hijo OCULTO (colapsado): su cable CONVERGE a la caja (${C.afterD.toFixed(2)}px, no cuelga)`);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(150); await shotCanvas("recinto-2-colapsado-stack.png");

  // ╔══ D · el muro ROTA con la sala (cámara-aware) + light/dark ═════════════════════════════════╗
  await reset();
  const Dmove = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeRecinto({ id: "agtR", nucleo: true, agent_ref: "a/r", gridX: 3, gridY: 3, w: 2, h: 2 }, [{ id: "r1", key: "r1", label: "R1", category: "read" }]);
    const before = c.screenPointOf("agtR");
    c.cam.rotateBy(1);                                                    // rotar el plano iso
    const after = c.screenPointOf("agtR");
    return { moved: Math.hypot(after.x - before.x, after.y - before.y) };
  });
  await page.waitForTimeout(150);
  const Ddrawn = await page.evaluate(() => window.__cuarto.recintoDraw().some((x) => x.id === "agtR" && x.haloActive));
  ok(Dmove.moved > 2 && Ddrawn, `D · el muro rota con la sala (la caja se reproyectó ${Dmove.moved.toFixed(0)}px, sigue dibujándose)`);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(150);
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "dark"); window.__cuarto.setTheme("dark"); });
  await page.waitForTimeout(200); await shotCanvas("recinto-2-rotado-dark.png");
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light"); window.__cuarto.setTheme("light"); });
  await page.waitForTimeout(200); await shotCanvas("recinto-2-rotado-light.png");

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — sub-rama 2 (recinto-render) verificada"));
process.exit(fails.length ? 1 : 0);
