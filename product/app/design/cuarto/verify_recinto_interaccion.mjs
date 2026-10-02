/* verify_recinto_interaccion.mjs — sub-rama 3 (recinto-interaccion) · headless, SIN backend (≠ :8091).
 *
 * El recinto se vuelve INTERACTIVO. Prueba: (A) toggle colapsar↔expandir (1:1, footprint 1×1↔w×h);
 * (B) drag del bloque (recinto+hijos juntos, posición relativa, rebote si choca); (C) drop-into-como-hijo
 * y emancipación; (D) "ordenar" NO dispersa los hijos; (E) ⚠️ AUTO-EXPAND ante gate_waiting real en
 * recinto colapsado [RIESGO #1]; (F) REGRESIÓN sin recintos idéntica. Capturas de los estados.
 * Run:  node verify_recinto_interaccion.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8099;
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

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
const clientOf = (gx, gy) => page.evaluate(({ gx, gy }) => {
  const c = window.__cuarto, p = c.viewPoint(gx, gy), r = c.app.canvas.getBoundingClientRect();
  return { x: r.left + p.x * (r.width / c.app.screen.width), y: r.top + p.y * (r.height / c.app.screen.height) };
}, { gx, gy });

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  // ╔══ F · REGRESIÓN (sin recintos = idéntica) ══════════════════════════════════════════════════╗
  const F = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeTile({ id: "t1", key: "t1", label: "T1", category: "process" }, 4, 4);
    c.placeTile({ id: "t2", key: "t2", label: "T2", category: "read" }, 5, 4);
    const before = c.relationModel();
    c.dropTileAt("t1", 6, 5);                        // sin recintos: dropTileAt = camino normal (mover)
    c.order();                                       // ordenar sin recintos
    const after = c.relationModel();
    return { before, after, anyParentId: after.pieces.some((p) => "parentId" in p) };
  });
  ok(eq(F.before.relationships, F.after.relationships) && !F.anyParentId,
    "F · sin recintos: relationships intactas tras dropTileAt+order, ninguna pieza con parentId");

  // ╔══ A · TOGGLE colapsar↔expandir (1:1, footprint 1×1↔w×h, hijos ocultos↔visibles) ════════════╗
  await reset();
  await page.evaluate(() => window.__cuarto.placeRecinto(
    { id: "R", nucleo: true, agent_ref: "a/R", gridX: 2, gridY: 3, w: 2, h: 2 },
    [{ id: "a1", key: "a1", label: "A1", category: "read" }, { id: "a2", key: "a2", label: "A2", category: "process" }]));
  const s0 = await page.evaluate(() => window.__cuarto.recintoState("R"));
  await page.evaluate(() => window.__cuarto.toggleRecinto("R"));   // → colapsado
  const s1 = await page.evaluate(() => window.__cuarto.recintoState("R"));
  await page.evaluate(() => window.__cuarto.toggleRecinto("R"));   // → expandido
  const s2 = await page.evaluate(() => window.__cuarto.recintoState("R"));
  ok(!s0.collapsed && eq(s0.eff, { w: 2, h: 2 }) && s0.children.every((c) => !c.hidden), "A · expandido inicial: eff 2×2, hijos visibles");
  ok(s1.collapsed && eq(s1.eff, { w: 1, h: 1 }) && s1.children.every((c) => c.hidden), "A · colapsado: eff 1×1, hijos OCULTOS");
  ok(!s2.collapsed && eq(s2.eff, { w: 2, h: 2 }) && s2.children.every((c) => !c.hidden), "A · re-expandido: eff 2×2, hijos visibles (alterna 1:1)");
  // CLIC REAL en el muro del recinto (celda vacía del footprint) → toggle (prueba el wire del hit-area)
  await page.evaluate(() => window.__cuarto.setRecintoCollapsed("R", false));
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(150);
  const wall = await clientOf(2, 4);                               // celda del footprint sin hijo (a1@2,3 · a2@3,3)
  await page.mouse.move(wall.x, wall.y); await page.mouse.down(); await page.mouse.up(); await page.waitForTimeout(150);
  const s3 = await page.evaluate(() => window.__cuarto.recintoState("R"));
  ok(s3.collapsed === true, "A · CLIC real en el muro → colapsa (hit-area + tileDragUp recinto wired)");
  await page.evaluate(() => window.__cuarto.setRecintoCollapsed("R", false));

  // ╔══ B · DRAG del BLOQUE (recinto+hijos juntos, posición relativa; rebote si choca) — grilla 7×7 ═╗
  const B = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "R2", nucleo: true, agent_ref: "a/R2", gridX: 1, gridY: 3, w: 2, h: 2 },
      [{ id: "b1", key: "b1", label: "B1", category: "read" }, { id: "b2", key: "b2", label: "B2", category: "process" }]);
    c.placeTile({ id: "obs", key: "obs", label: "OBS", category: "process" }, 4, 3);   // obstáculo (dentro de la grilla 7×7)
    const rel = (st) => st.children.map((ch) => `${ch.gx - st.gx},${ch.gy - st.gy}`).sort();
    const relBefore = rel(c.recintoState("R2"));
    const movedOk = c.moveRecinto("R2", 4, 4);                     // footprint (4,4)-(5,5) libre → mueve el bloque
    const sMoved = c.recintoState("R2");
    const bounce = c.moveRecinto("R2", 3, 3);                      // footprint (3,3)-(4,4) pisa OBS@(4,3) → rebota
    const sBounce = c.recintoState("R2");
    return { movedOk, relBefore, movedRel: rel(sMoved), movedXY: [sMoved.gx, sMoved.gy], bounce, bounceXY: [sBounce.gx, sBounce.gy] };
  });
  ok(B.movedOk && eq(B.movedXY, [4, 4]) && eq(B.relBefore, B.movedRel), "B · drag del bloque: recinto+hijos se mueven juntos, posición relativa intacta");
  ok(B.bounce === false && eq(B.bounceXY, [4, 4]), "B · REBOTE: mover sobre celda ocupada → no mueve (se queda)");

  // ╔══ C · DROP-INTO-como-hijo + EMANCIPACIÓN ═══════════════════════════════════════════════════╗
  const C = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "R3", nucleo: true, agent_ref: "a/R3", gridX: 1, gridY: 3, w: 2, h: 2 }, []);
    c.placeTile({ id: "loose", key: "loose", label: "L", category: "read" }, 5, 5);     // pieza suelta (global)
    const beforeParent = c.parentOf("loose");
    c.dropTileAt("loose", 1, 3);                                   // soltar DENTRO del recinto → adopta
    const afterAdopt = c.parentOf("loose");
    const inLocal = c.recintoState("R3").children.some((ch) => ch.id === "loose");
    c.dropTileAt("loose", 5, 6);                                   // arrastrar AFUERA → emancipa
    const afterEmanc = c.parentOf("loose");
    const stillChild = c.recintoState("R3").children.some((ch) => ch.id === "loose");
    return { beforeParent, afterAdopt, inLocal, afterEmanc, stillChild };
  });
  ok(C.beforeParent === null && C.afterAdopt === "R3" && C.inLocal, "C · soltar pieza DENTRO del recinto → adoptada como hijo (parentId + occ local)");
  ok(C.afterEmanc === null && !C.stillChild, "C · arrastrar hijo AFUERA → emancipado (pierde parentId, vuelve al global)");

  // ╔══ D · "ORDENAR" no dispersa los hijos ══════════════════════════════════════════════════════╗
  const D = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "R4", nucleo: true, agent_ref: "a/R4", gridX: 1, gridY: 3, w: 2, h: 2 },
      [{ id: "d1", key: "d1", label: "D1", category: "read" }, { id: "d2", key: "d2", label: "D2", category: "process" }]);
    c.placeTile({ id: "x1", key: "x1", label: "X1", category: "read" }, 5, 4);
    c.placeTile({ id: "x2", key: "x2", label: "X2", category: "process" }, 5, 5);
    const before = c.recintoState("R4");
    c.order();
    const after = c.recintoState("R4");
    const childrenStillIn = after.children.every((ch) => c.parentOf(ch.id) === "R4" &&
      ch.gx >= after.gx && ch.gx < after.gx + after.footprint.w && ch.gy >= after.gy && ch.gy < after.gy + after.footprint.h);
    return { recintoStill: before.gx === after.gx && before.gy === after.gy, childrenStillIn };
  });
  ok(D.recintoStill && D.childrenStillIn, "D · 'ordenar' NO dispersa: recinto fijo, hijos siguen dentro con parentId (riesgo #2)");

  // ╔══ E · ⚠️ AUTO-EXPAND ante gate_waiting REAL en recinto colapsado [RIESGO #1] ════════════════╗
  await reset();
  await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeRecinto({ id: "RG", nucleo: true, agent_ref: "a/RG", gridX: 3, gridY: 3, w: 2, h: 2 },
      [{ id: "g1", key: "g1", label: "Pagar", category: "write", gated: true }]);
    c.setRecintoCollapsed("RG", true);                            // caja CERRADA con un gate adentro
  });
  const eBefore = await page.evaluate(() => ({ collapsed: window.__cuarto.recintoState("RG").collapsed }));
  await page.evaluate(() => window.__cuarto.gateHold("g1"));      // ⚠️ freno REAL de F5 dentro de la caja cerrada
  await page.waitForTimeout(150);
  const eAfter = await page.evaluate(() => ({ collapsed: window.__cuarto.recintoState("RG").collapsed, held: window.__cuarto.isGateHeld("g1") }));
  ok(eBefore.collapsed === true && eAfter.collapsed === false && eAfter.held === true,
    "E · ⚠️ gate_waiting en recinto COLAPSADO → AUTO-EXPANDE y el freno se ve (invariante F5 intacto)");
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(200);
  await shotCanvas("recinto-3-autoexpand-gate.png");

  // capturas de los estados base (expandido / colapsado)
  await page.evaluate(() => { const c = window.__cuarto; c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "SX", nucleo: true, agent_ref: "a/SX", gridX: 3, gridY: 3, w: 2, h: 2 },
      [{ id: "p1", key: "p1", label: "Lee", category: "read" }, { id: "p2", key: "p2", label: "Actúa", category: "write" }]); c.cam.fit(); });
  await page.waitForTimeout(200); await shotCanvas("recinto-3-expandido.png");
  await page.evaluate(() => { window.__cuarto.setRecintoCollapsed("SX", true); window.__cuarto.cam.fit(); });
  await page.waitForTimeout(200); await shotCanvas("recinto-3-colapsado.png");

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — sub-rama 3 (recinto-interaccion) verificada — RECINTO COMPLETO"));
process.exit(fails.length ? 1 : 0);
