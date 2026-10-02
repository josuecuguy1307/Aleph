/* verify_slots.mjs — SLOTS (§8 del Cuarto) · A+B+C (D suma su check de nacimiento al final).
 * Headless, SIN backend (puerto ≠ :8091). Carga fixture_slots y prueba las 4 mecánicas:
 *   A · 0 adders en escena (ningún nodo kind:"adder");
 *   D-mecanismo · placeTile SIN coords cae en balancedFreeCell (la pieza nace en celda balanceada);
 *   B · el ghost INTERPOLA hacia la celda destino (no salta) + el foco per-celda lo sigue/enciende;
 *   C · el floor-tint SUBE en modo-colocar (dark: pico de breath > reposo · light: alpha del piso sube).
 *   + capturas (piso en reposo · grid respirando dark · grid respirando light) + 0 errores.
 * Run:  node verify_slots.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { SLOTS_FIXTURE, buildSlots } from "./fixture_slots.mjs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = Number(process.env.SLOTS_PORT || 8102); // parametrizable para integraciones
if (PORT === 25374) { console.error("✗ :25374 es la .app instalada — jamás."); process.exit(2); }
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const TOOL = { id: "slots_drag", key: "slots_drag", label: "arrastre", category: "read", atom: "tool" };

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
const shot = async (name) => { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); };

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  const n = await page.evaluate(buildSlots, SLOTS_FIXTURE);
  await page.waitForTimeout(150);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(250);
  ok(n === 4, "fixture de slots cargado (4 tools sembradas)", `placedTiles=${n}`);

  // ╔══ A · PISO LIMPIO: 0 adders en escena ═════════════════════════════════════════════════════╗
  const adders = await page.evaluate(() => window.__cuarto.adderCount());
  ok(adders === 0, "A · 0 adders en escena (ningún nodo kind:'adder')", `adderCount=${adders}`);
  await shot("slots-A-piso-limpio.png");

  // ╔══ D-mecanismo · placeTile SIN coords cae en balancedFreeCell ═══════════════════════════════╗
  const bal = await page.evaluate(() => {
    const c = window.__cuarto;
    const expected = c.layout.balancedCell();                       // hueco balanceado ANTES de colocar
    const res = c.placeTile({ id: "slots_bal", key: "slots_bal", label: "nace", category: "process", atom: "tool" }); // SIN coords
    const match = res && expected && res.gridX === expected.gx && res.gridY === expected.gy;
    c.removeTile("slots_bal");                                       // limpieza
    return { expected, res, match };
  });
  ok(bal.match, "D-mecanismo · placeTile sin coords → cae EXACTO en balancedFreeCell (nace, no aparece)",
     `balanced=(${bal.expected && bal.expected.gx},${bal.expected && bal.expected.gy}) place=(${bal.res && bal.res.gridX},${bal.res && bal.res.gridY})`);

  // ── puntos de piso para arrastrar (2 celdas lejanas) ──
  const pts = await page.evaluate(() => {
    const c = window.__cuarto, r = c.app.canvas.getBoundingClientRect(), a = [];
    for (let fy = 0.3; fy <= 0.72; fy += 0.06) for (let fx = 0.2; fx <= 0.82; fx += 0.04) {
      const x = r.left + r.width * fx, y = r.top + r.height * fy; if (c.screenToCell(x, y)) a.push({ x, y });
    }
    let best = null, bd = -1;
    for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) { const d = Math.hypot(a[i].x - a[j].x, a[i].y - a[j].y); if (d > bd) { bd = d; best = [a[i], a[j], d]; } }
    return best;
  });
  ok(pts && pts[2] > 120, "2 puntos de piso lejanos para arrastrar", pts ? `dist=${Math.round(pts[2])}px` : "");
  const [A, B] = pts;

  // ╔══ B · el GHOST INTERPOLA hacia la celda destino (no salta) + foco per-celda ════════════════╗
  await page.evaluate(({ A, TOOL }) => { const c = window.__cuarto; c.beginDrag(TOOL); c.updateDrag(A.x, A.y); }, { A, TOOL });
  await page.waitForTimeout(280);
  const s1 = await page.evaluate(() => window.__cuarto.ghostState());
  ok(s1.visible && Math.hypot(s1.x - s1.tx, s1.y - s1.ty) < 2, "B · ghost asentado en A (render ≈ destino)", `Δ=${Math.hypot(s1.x - s1.tx, s1.y - s1.ty).toFixed(2)}`);
  const jmp = await page.evaluate(({ B }) => { const c = window.__cuarto; const before = c.ghostState(); c.updateDrag(B.x, B.y); const after = c.ghostState(); return { before, after }; }, { B });
  const movedRender = Math.hypot(jmp.after.x - jmp.before.x, jmp.after.y - jmp.before.y);
  const toTarget = Math.hypot(jmp.after.tx - jmp.after.x, jmp.after.ty - jmp.after.y);
  ok(movedRender < 1.0, "B · tras updateDrag(B): el render NO saltó (interpola, no set seco)", `Δrender=${movedRender.toFixed(2)}px`);
  ok(toTarget > 60, "B · el DESTINO se movió a B (el ghost tiene a dónde fluir)", `Δ(pos→target)=${toTarget.toFixed(1)}px`);
  ok(jmp.after.glowOn === true && jmp.after.glowVisible === true, "B · el foco per-celda está ENCENDIDO y visible durante el arrastre");
  await page.waitForTimeout(60);
  const mid = await page.evaluate(() => window.__cuarto.ghostState());
  ok(Math.hypot(mid.x - mid.tx, mid.y - mid.ty) > 2, "B · mid-flight: el ghost va EN CAMINO hacia B (interpolando)", `Δ=${Math.hypot(mid.x - mid.tx, mid.y - mid.ty).toFixed(1)}px`);
  // converge: poll por estado real (headless throttlea el rAF a ~16fps → sleeps fijos sub-asientan)
  await page.waitForFunction(() => { const g = window.__cuarto.ghostState(); return Math.hypot(g.x - g.tx, g.y - g.ty) < 1.2; }, null, { timeout: 6000 }).catch(() => {});
  const s3 = await page.evaluate(() => window.__cuarto.ghostState());
  ok(Math.hypot(s3.x - s3.tx, s3.y - s3.ty) < 2.5, "B · el lerp CONVERGE a B (render alcanza el destino)", `Δ=${Math.hypot(s3.x - s3.tx, s3.y - s3.ty).toFixed(2)}`);

  // ╔══ C · el FLOOR-TINT sube en modo-colocar (dark, per-celda por proximidad) ══════════════════╗
  const breathPlacing = await page.evaluate(() => window.__cuarto.floorBreath());
  ok(!breathPlacing.light && breathPlacing.placing && breathPlacing.max > 0.3,
     "C · dark · en modo-colocar el piso RESPIRA (pico de breath cerca de la celda activa)", `max=${breathPlacing.max.toFixed(2)}`);
  await shot("slots-C-grid-respira-dark.png");                       // grid respirando + ghost + foco
  // soltar → vuelve al reposo (casi invisible) — poll por la decaída real
  await page.evaluate(() => window.__cuarto.cancelDrag());
  await page.waitForFunction(() => window.__cuarto.floorBreath().max < 0.04, null, { timeout: 7000 }).catch(() => {});
  const breathRest = await page.evaluate(() => window.__cuarto.floorBreath());
  ok(!breathRest.placing && breathRest.max < 0.06, "C · en reposo el piso queda casi invisible (breath → 0)", `max=${breathRest.max.toFixed(3)}`);
  await shot("slots-C-piso-reposo-dark.png");

  // ╔══ C-light · el alpha del piso CLARO sube en modo-colocar ═══════════════════════════════════╗
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light"); window.__cuarto.setTheme("light"); window.__cuarto.cam.fit(); });
  await page.waitForFunction(() => window.__cuarto.floorBreath().lightAlpha < 0.825, null, { timeout: 6000 }).catch(() => {}); // reposo: ease a LO=0.8
  const lightRest = await page.evaluate(() => window.__cuarto.floorBreath());
  await page.evaluate(({ A, TOOL }) => { const c = window.__cuarto; c.beginDrag(TOOL); c.updateDrag(A.x, A.y); }, { A, TOOL });
  await page.waitForFunction(() => window.__cuarto.floorBreath().lightAlpha > 0.96, null, { timeout: 6000 }).catch(() => {}); // colocando: ease a HI=1.0
  const lightPlacing = await page.evaluate(() => window.__cuarto.floorBreath());
  ok(lightRest.light && lightRest.lightAlpha < 0.86 && lightPlacing.lightAlpha > lightRest.lightAlpha + 0.06,
     "C · light · el alpha del piso SUBE al colocar (reposo sutil → activo)", `reposo=${lightRest.lightAlpha.toFixed(2)} colocando=${lightPlacing.lightAlpha.toFixed(2)}`);
  await shot("slots-C-grid-respira-light.png");
  await page.evaluate(() => window.__cuarto.cancelDrag());

  // ╔══ D · CLICK en la paleta → emerge en celda BALANCEADA + nacimiento 0.9→1.0 (sin overshoot) ══╗
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "dark"); window.__cuarto.setTheme("dark"); window.__cuarto.cam.fit(); });
  await page.waitForTimeout(200);
  // (1) maneja el HANDLER REAL de la paleta: inyecto un átomo + un chip y disparo pointerdown/up SIN mover.
  //     clientY off-canvas (arriba) → la celda del pointerdown es null → fuerza el camino CLICK (no drag).
  const clickRes = await page.evaluate(() => {
    const c = window.__cuarto;
    window.__atoms.byKey["__slotstest"] = { id: "__slotstest", key: "__slotstest", label: "Prueba slots", category: "process", atom: "tool" };
    const before = c.placedTiles().length;
    const expected = c.layout.balancedCell();
    const host = document.getElementById("paletteList");
    const chip = document.createElement("div"); chip.className = "chip"; chip.dataset.key = "__slotstest"; host.appendChild(chip);
    const rect = c.app.canvas.getBoundingClientRect();
    const cx = rect.left + rect.width / 2, cy = rect.top - 30;
    chip.dispatchEvent(new PointerEvent("pointerdown", { clientX: cx, clientY: cy, bubbles: true }));
    window.dispatchEvent(new PointerEvent("pointerup", { clientX: cx, clientY: cy, bubbles: true }));
    chip.remove();
    const tiles = c.placedTiles();
    const last = tiles.find((t) => t.label === "Prueba slots") || tiles[tiles.length - 1];
    return { before, after: tiles.length, expected, last: last ? { gx: last.gridX, gy: last.gridY, label: last.label } : null };
  });
  ok(clickRes.after === clickRes.before + 1, "D · click en la paleta (sin arrastrar) → colocó 1 pieza por el handler real", `${clickRes.before}→${clickRes.after}`);
  ok(clickRes.last && clickRes.expected && clickRes.last.gx === clickRes.expected.gx && clickRes.last.gy === clickRes.expected.gy,
     "D · la pieza del click EMERGE en la celda BALANCEADA (no en zona fija)", `balanced=(${clickRes.expected && clickRes.expected.gx},${clickRes.expected && clickRes.expected.gy}) pieza=(${clickRes.last && clickRes.last.gx},${clickRes.last && clickRes.last.gy})`);

  // (2) nacimiento 0.9→1.0: muestreo la escala de una pieza recién nacida por rAF (sin overshoot, sin partir de 0)
  const birth = await page.evaluate(async () => {
    const c = window.__cuarto;
    c.placeTile({ id: "__slotsbirth", key: "__slotsbirth", label: "nace", category: "read", atom: "tool" });
    const samples = [];
    for (let i = 0; i < 30; i++) { const s = c.tileScale("__slotsbirth"); if (s) samples.push(s.scale); await new Promise((r) => requestAnimationFrame(r)); }
    return samples;
  });
  const postTick = birth.slice(1);                                  // [0] = escala default pre-tick (1.0) → la descarto
  const sMin = Math.min(...postTick), sMax = Math.max(...birth);
  ok(sMin >= 0.85 && sMin <= 0.99, "D · el nacimiento ARRANCA cerca de 0.9 (no desde 0 ni overshoot)", `min=${sMin.toFixed(3)}`);
  ok(sMax <= 1.03, "D · nacimiento SIN overshoot (la escala nunca pasa de ~1.0; easeOutBack pasaría ~1.06)", `max=${sMax.toFixed(3)}`);
  ok(birth[birth.length - 1] >= 0.97, "D · la escala CONVERGE a 1.0 (asentada)", `fin=${birth[birth.length - 1].toFixed(3)}`);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(200);
  await shot("slots-D-emerge.png");

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — SLOTS A+B+C+D verificados (0 adders · ghost interpola · piso respira · click→balanced + nacimiento 0.9→1.0)"));
process.exit(fails.length ? 1 : 0);
