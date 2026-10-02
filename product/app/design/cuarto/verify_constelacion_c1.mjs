/* verify_constelacion_c1.mjs — CONSTELACIÓN (capa 3) · C1 = LAS 3 VISTAS (generalizar la lente F4).
 * Headless, SIN backend (puerto ≠ :8091). Prueba:
 *   (A) las 3 vistas (servicio/funcion/relacion) REAGRUPAN el overlay DISTINTO sobre la misma data;
 *   (B) INVARIANTE: model.pieces/relationships BYTE-IDÉNTICO antes/después de CADA toggle (la vista no muta);
 *   (C) F4 SUBSUMIDA: api.lens.toggle() == vista "funcion" (tools por rol), api.lens.on coherente;
 *   (D) REGRESIÓN: al montar la vista = "off" (idéntico a hoy: sin grupos); off no dibuja overlay;
 *   (E) theme claro/oscuro OK + capturas de las 3 vistas. Falla si hay error JS.
 * Run:  node verify_constelacion_c1.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { CONSTELACION_FIXTURE, buildConstelacion } from "./fixture_constelacion.mjs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8099;                                // ≠ :8091
const PAGE_URL = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const sortedKeys = (groups) => groups.map((g) => g.key).sort();
const countMap = (groups) => Object.fromEntries(groups.map((g) => [g.key, g.count]));
// compara dos mapas {clave:conteo} sin importar el ORDEN de las claves (eq por JSON es order-sensitive).
const eqMap = (a, b) => { const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
  return eq(ka, kb) && ka.every((k) => a[k] === b[k]); };

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 700));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.route("**/v1/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
const shotCanvas = async (name) => { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); };

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  // ╔══ D · REGRESIÓN al MONTAR: la vista arranca "off" (idéntico a hoy: sin overlay) ════════════╗
  const mounted = await page.evaluate(() => { const c = window.__cuarto; return { mode: c.view.get(), vs: c.viewState(), lensOn: c.lens.on }; });
  ok(mounted.mode === "off" && eq(mounted.vs.groups, []) && mounted.lensOn === false,
    "D · al montar: view='off', sin grupos, lens.on=false (orbitar crudo idéntico a hoy)", JSON.stringify({ mode: mounted.mode, lensOn: mounted.lensOn }));

  // siembra la escena de constelación
  const n = await page.evaluate(buildConstelacion, CONSTELACION_FIXTURE);
  await page.waitForTimeout(120);
  ok(n === 11, "fixture sembrado: 11 piezas colocadas (recinto+2 hijos + 6 tools + 2 conexiones)", `placedTiles=${n}`);

  // SNAPSHOT del modelo ANTES de tocar ninguna vista (la referencia byte-a-byte).
  const M0 = await page.evaluate(() => { const m = window.__cuarto.relationModel(); return { pieces: m.pieces, rels: m.relationships }; });

  // ╔══ A · las 3 vistas reagrupan DISTINTO + B · el modelo no se mueve en CADA toggle ═══════════╗
  const probe = async (mode) => page.evaluate((mm) => {
    const c = window.__cuarto; c.view.set(mm);
    const m = c.relationModel();
    return { active: c.view.get(), groups: c.viewState().groups, pieces: m.pieces, rels: m.relationships };
  }, mode);

  const SV = await probe("servicio");
  ok(SV.active === "servicio" && eq(sortedKeys(SV.groups), ["exa", "gmail", "kb", "sec_edgar", "tmdb"]),
    "A · SERVICIO → 5 cúmulos por origen (tmdb·exa·gmail·sec_edgar·kb)", JSON.stringify(countMap(SV.groups)));
  ok(eqMap(countMap(SV.groups), { tmdb: 3, exa: 1, gmail: 3, sec_edgar: 1, kb: 2 }),
    "A · SERVICIO → conteos correctos (tmdb=3 incl. su conexión, gmail=3, kb=2 los hijos del recinto)");
  ok(eq(SV.pieces, M0.pieces) && eq(SV.rels, M0.rels), "B · tras 'servicio': model.pieces/relationships BYTE-IDÉNTICO");

  const FN = await probe("funcion");
  ok(FN.active === "funcion" && eq(sortedKeys(FN.groups), ["entrega", "fuentes", "mesa"]),
    "A · FUNCIÓN → 3 cúmulos por rol (lee/procesa/actúa) — sólo tools, sin conexiones", JSON.stringify(countMap(FN.groups)));
  ok(eq(countMap(FN.groups), { fuentes: 3, mesa: 4, entrega: 1 }),
    "A · FUNCIÓN → conteos por rol (fuentes=3, mesa=4, entrega=1); las 2 conexiones (role null) NO entran");
  ok(eq(FN.pieces, M0.pieces) && eq(FN.rels, M0.rels), "B · tras 'funcion': model.pieces/relationships BYTE-IDÉNTICO");

  const RL = await probe("relacion");
  ok(RL.active === "relacion" && eq(sortedKeys(RL.groups), ["agt", "cx_gmail", "cx_tmdb", "—"]),
    "A · RELACIÓN → 4 cúmulos: recinto 'agt' + 2 conexiones (su fan-out) + sueltas", JSON.stringify(countMap(RL.groups)));
  ok(eqMap(countMap(RL.groups), { agt: 2, cx_tmdb: 3, cx_gmail: 3, "—": 2 }),
    "A · RELACIÓN → conteos (agt=2 hijos, cx_tmdb=3, cx_gmail=3, sueltas=2)");
  ok(eq(RL.pieces, M0.pieces) && eq(RL.rels, M0.rels), "B · tras 'relacion': model.pieces/relationships BYTE-IDÉNTICO");

  // las 3 vistas son GENUINAMENTE distintas (no la misma agrupación con otro nombre)
  ok(!eq(sortedKeys(SV.groups), sortedKeys(FN.groups)) && !eq(sortedKeys(FN.groups), sortedKeys(RL.groups)) && !eq(sortedKeys(SV.groups), sortedKeys(RL.groups)),
    "A · las 3 vistas reagrupan la MISMA data de 3 formas distintas (5 vs 3 vs 4 cúmulos)");

  // ╔══ C · F4 SUBSUMIDA en la vista "funcion" (compat cuarto.pixi.html) ═════════════════════════╗
  const offNow = await page.evaluate(() => window.__cuarto.view.set("off"));
  const Llens = await page.evaluate(() => { const c = window.__cuarto; const on = c.lens.toggle(); return { lensReturn: on, mode: c.view.get(), lensOn: c.lens.on, groups: c.viewState().groups }; });
  ok(offNow === "off" && Llens.mode === "funcion" && Llens.lensOn === true && eq(sortedKeys(Llens.groups), ["entrega", "fuentes", "mesa"]),
    "C · lens.toggle() PRENDE la vista 'funcion' (F4 subsumida) — agrupado por rol idéntico", JSON.stringify({ mode: Llens.mode, lensOn: Llens.lensOn }));
  const Loff = await page.evaluate(() => { const c = window.__cuarto; c.lens.toggle(); return { mode: c.view.get(), lensOn: c.lens.on }; });
  ok(Loff.mode === "off" && Loff.lensOn === false, "C · lens.toggle() de nuevo APAGA (vuelve a 'off')");

  // ╔══ B-bis · tras TODO el ciclo de toggles el modelo SIGUE byte-idéntico ══════════════════════╗
  const Mend = await page.evaluate(() => { const m = window.__cuarto.relationModel(); return { pieces: m.pieces, rels: m.relationships }; });
  ok(eq(Mend.pieces, M0.pieces) && eq(Mend.rels, M0.rels), "B · tras off→servicio→funcion→relacion→off→lens: modelo INTACTO (las vistas nunca lo tocan)");

  // ╔══ E · capturas de las 3 vistas (dark) + theme claro ═══════════════════════════════════════╗
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(150);
  for (const v of ["servicio", "funcion", "relacion"]) {
    await page.evaluate((vv) => window.__cuarto.view.set(vv), v);
    await page.waitForTimeout(420); await shotCanvas(`constelacion-c1-${v}-dark.png`);
  }
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light"); window.__cuarto.setTheme("light"); window.__cuarto.view.set("servicio"); });
  await page.waitForTimeout(420); await shotCanvas("constelacion-c1-servicio-light.png");
  const lightOk = await page.evaluate(() => window.__cuarto.viewState().groups.length === 5);
  ok(lightOk, "E · en theme CLARO la vista 'servicio' sigue agrupando (5 cúmulos) sin error");

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — C1 (las 3 vistas) verificada"));
process.exit(fails.length ? 1 : 0);
