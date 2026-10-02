/* verify_slots_modo.mjs — la vara del MODO AGREGAR CASILLAS [Integración #5 · punto 34].
 *
 * Lo que hay que probar es el CICLO, no que los ＋ existan: la función vuelve como MODO y el
 * pecado original (SLOTS·A) fue que los ＋ estaban visibles por DEFAULT. Entonces:
 *
 *   1 · modo OFF (default)  → 0 adders en escena  ← lo mismo que asserta verify_slots.mjs · A
 *   2 · modo ON             → adders presentes    ← la función existe de verdad
 *   3 · salir del modo      → 0 otra vez          ← salir es SALIR: el diorama vuelve limpio
 *
 * Y además, porque un modo que no se puede prender desde la UI no sirve:
 *   4 · el botón vive DENTRO del widget de controles (⊙), no suelto en el diorama (§8.5)
 *   5 · el clic REAL en el botón hace el ciclo, y el indicador dice la verdad (ON/OFF)
 *   6 · un ＋ clickeado EXTIENDE la zona (la casilla se agrega de verdad)
 *
 * Headless, SIN backend (puerto ≠ :8091). Mismo harness que verify_slots.mjs.
 * Run:  node verify_slots_modo.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { SLOTS_FIXTURE, buildSlots } from "./fixture_slots.mjs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8112;                                // ≠ :8091 y ≠ los otros verify
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push("[console] " + m.text()); });
page.on("pageerror", (e) => errors.push("[pageerror] " + String(e)));
// sin backend: el árbol de /v1 se responde vacío (mismo stub que verify_slots.mjs)
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 15000 });
  await page.evaluate(buildSlots, SLOTS_FIXTURE);
  await page.waitForTimeout(150);
  await page.evaluate(() => window.__cuarto.cam.fit());
  await page.waitForTimeout(400);

  const count = () => page.evaluate(() => window.__cuarto.adderCount());
  const modo = () => page.evaluate(() => window.__cuarto.adders.on);

  // ── 1 · OFF por default ───────────────────────────────────────────────────────────────
  const off0 = await count(), m0 = await modo();
  ok(m0 === false, "1 · el modo arranca APAGADO (default)", `adders.on=${m0}`);
  ok(off0 === 0, "1 · modo off → 0 adders en escena (el piso nace limpio)", `adderCount=${off0}`);

  // ── 2 · ON → los ＋ existen ───────────────────────────────────────────────────────────
  await page.evaluate(() => window.__cuarto.adders.set(true));
  await page.waitForTimeout(250);
  const on1 = await count();
  ok(await modo() === true, "2 · adders.set(true) prende el modo");
  ok(on1 > 0, "2 · modo on → adders PRESENTES (la función volvió)", `adderCount=${on1}`);
  await page.screenshot({ path: join(SHOTS, "slots-modo-on.png") });

  // ── 3 · salir → 0 otra vez ────────────────────────────────────────────────────────────
  await page.evaluate(() => window.__cuarto.adders.set(false));
  await page.waitForTimeout(250);
  const off1 = await count();
  ok(await modo() === false, "3 · adders.set(false) apaga el modo");
  ok(off1 === 0, "3 · al salir → 0 adders (el diorama vuelve LIMPIO)", `adderCount=${off1}`);
  ok(off1 === off0, "3 · salir deja la escena como estaba (mismo conteo que al inicio)", `${off0} → ${off1}`);

  // ── 4 · el botón vive DENTRO del widget ⊙, no suelto en el diorama ────────────────────
  const ubic = await page.evaluate(() => {
    const b = document.getElementById("slotsBtn");
    if (!b) return { existe: false };
    return {
      existe: true,
      dentroDelWidget: !!b.closest("#camBody"),          // anidado en los controles de vista
      ocultoEnReposo: !!(b.closest("#camBody") || {}).hidden,   // colapsado = no se ve
    };
  });
  ok(ubic.existe, "4 · existe el botón «＋ Casillas»");
  ok(ubic.dentroDelWidget, "4 · vive DENTRO del widget de controles (⊙), no suelto en el diorama");
  ok(ubic.ocultoEnReposo, "4 · con el widget colapsado el botón NO se ve (nada nuevo ensucia el reposo)");

  // ── 5 · el clic REAL hace el ciclo y el indicador no miente ──────────────────────────
  await page.click("#camToggle");                       // abrir el widget
  await page.waitForTimeout(200);
  await page.click("#slotsBtn");                        // prender
  await page.waitForTimeout(250);
  const uiOn = await page.evaluate(() => ({
    n: window.__cuarto.adderCount(),
    txt: document.getElementById("slotsState").textContent.trim(),
    clase: document.getElementById("slotsBtn").classList.contains("on"),
  }));
  ok(uiOn.n > 0, "5 · el CLIC del botón prende el modo (adders en escena)", `adderCount=${uiOn.n}`);
  ok(uiOn.txt === "ON" && uiOn.clase, "5 · el indicador dice ON y no miente", `estado="${uiOn.txt}"`);
  await page.screenshot({ path: join(SHOTS, "slots-modo-widget.png") });

  // ── 6 · un ＋ EXTIENDE la zona de verdad (la casilla se agrega) ───────────────────────
  const antes = await page.evaluate(() => JSON.stringify(window.__cuarto.spatialSnapshot().zones));
  const crecio = await page.evaluate(() => {
    // se toca el ＋ por su propio camino (growZone), que es lo que hace su pointertap.
    // OJO: `nucleo` NO crece por diseño (no es un rol de CATEGORÍA) y devuelve blocked —
    // se prueban las zonas hasta encontrar una que el ＋ pueda extender de verdad.
    const zonas = window.__cuarto.spatialSnapshot().zones;
    for (const z of zonas) {
      for (const dir of window.__cuarto.growDirs(z.role)) {
        const r = window.__cuarto.growZone(z.role, dir, 1);
        if (!r.blocked) return r;
      }
    }
    return { blocked: true, ninguna: true };
  });
  await page.waitForTimeout(250);
  const despues = await page.evaluate(() => JSON.stringify(window.__cuarto.spatialSnapshot().zones));
  ok(!crecio.blocked && antes !== despues, "6 · tocar un ＋ EXTIENDE la zona (la casilla se agrega)",
     `${crecio.role || ""} ${crecio.dir || ""}`);
  const trasCrecer = await count();
  ok(trasCrecer > 0, "6 · tras crecer, los ＋ siguen al borde nuevo (siguen vivos en el modo)", `adderCount=${trasCrecer}`);

  // ── 5b · apagar con el botón vuelve a dejar el piso limpio ────────────────────────────
  await page.click("#slotsBtn");
  await page.waitForTimeout(250);
  const uiOff = await page.evaluate(() => ({
    n: window.__cuarto.adderCount(),
    txt: document.getElementById("slotsState").textContent.trim(),
    clase: document.getElementById("slotsBtn").classList.contains("on"),
  }));
  ok(uiOff.n === 0, "5b · el segundo clic SALE del modo → 0 adders", `adderCount=${uiOff.n}`);
  ok(uiOff.txt === "OFF" && !uiOff.clase, "5b · el indicador vuelve a OFF", `estado="${uiOff.txt}"`);
  await page.screenshot({ path: join(SHOTS, "slots-modo-off.png") });

  ok(errors.length === 0, "0 errores de consola/página", errors.slice(0, 3).join(" · "));
} catch (e) {
  ok(false, "la vara corrió sin excepción", String(e && e.message || e));
} finally {
  await browser.close();
  server.kill();
}

console.log(`\n${fails.length === 0 ? "VERDE" : "ROJO"} · ${fails.length} fallo(s)`);
if (fails.length) { fails.forEach((f) => console.log("  ✗ " + f)); process.exit(1); }
