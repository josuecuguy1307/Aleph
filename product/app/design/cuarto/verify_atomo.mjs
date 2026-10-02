/* verify_atomo.mjs — done-bar sub-rama 2a (atomo-aleph): el Núcleo dejó de ser el logo de React.
 *   (a) los BEADS VIAJAN por sus órbitas (posiciones cambian entre muestras)
 *   (b) profundidad frente/atrás REAL (alphas dispares entre beads en una misma muestra)
 *   (c) core = hexágono con CARA (mascota canon) + 3 órbitas
 *   (d) el aro NO rota en plano (ringRotation clavado en 0 — adiós motivo React)
 *   (e) recinto-AGENTE enciende su mini-Aleph · cajón NO
 *   (f) dark + light · (g) 0 errores JS
 * Puerto :8151 (≠ otros verify). Sin backend (route stub /v1/**).   Run: node verify_atomo.mjs */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = 8151;
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

  // (a)+(b)+(c)+(d) · dos muestras del átomo vivo
  const s1 = await page.evaluate(() => window.__cuarto.atomState());
  await sleep(320);
  const s2 = await page.evaluate(() => window.__cuarto.atomState());
  const moved = s1.beads.reduce((acc, b, i) => acc + Math.abs(b.x - s2.beads[i].x) + Math.abs(b.y - s2.beads[i].y), 0);
  ok(s1.beads.length === 3 && moved > 2, "(a) 3 beads VIAJAN por la órbita", `Δ=${moved.toFixed(1)}px`);
  const alphas = s1.beads.map((b) => b.alpha);
  ok(Math.max(...alphas) - Math.min(...alphas) > 0.15, "(b) profundidad frente/atrás (alphas dispares)", `α=[${alphas.join(", ")}]`);
  ok(s1.face === true && s1.orbits === 3, "(c) hex con CARA + 3 órbitas", `face=${s1.face} orbits=${s1.orbits}`);
  ok(s1.ringRotation === 0 && s2.ringRotation === 0, "(d) el aro NO rota en plano (React fuera)", `rot=${s1.ringRotation}→${s2.ringRotation}`);

  // (e) · agente CON mini-Aleph · cajón SIN
  const recs = await page.evaluate(() => {
    const c = window.__cuarto;
    c.placeRecinto({ id: "va-agente", label: "Research", hasNucleo: true, w: 2, h: 2 },
      [{ id: "va-t1", label: "a", category: "read", atom: "tool", server: "arxiv" }]);
    c.placeRecinto({ id: "va-cajon", label: "Cajón", hasNucleo: false, w: 2, h: 1 }, []);
    return c.atomState().recintos;
  });
  ok(recs["va-agente"] && recs["va-agente"].art === true && recs["va-agente"].beads === 3,
     "(e1) recinto-AGENTE enciende mini-Aleph (3 beads)", JSON.stringify(recs["va-agente"]));
  ok(recs["va-cajon"] && recs["va-cajon"].art === false, "(e2) cajón SIN mini-Aleph", JSON.stringify(recs["va-cajon"]));

  // (f) · capturas dark + light
  await page.evaluate(() => window.__cuarto.cam.fit(1.3)); await sleep(400);
  await page.screenshot({ path: join(HERE, "screenshots", "atomo-dark.png") });
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light"); window.__cuarto.setTheme("light"); });
  await sleep(400);
  await page.screenshot({ path: join(HERE, "screenshots", "atomo-light.png") });
  ok(true, "(f) capturas dark+light", "screenshots/atomo-{dark,light}.png");

  ok(errors.length === 0, "(g) 0 errores JS/render", errors.slice(0, 2).join(" ; "));
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  await browser.close(); server.kill();
}
console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — átomo Aleph (beads viajan · profundidad · hex+cara · sin rotación plana · mini en agente)"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
