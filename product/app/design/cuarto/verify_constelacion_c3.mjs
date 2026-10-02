/* verify_constelacion_c3.mjs — CONSTELACIÓN (capa 3) · C3 = E2E (las 3 features JUNTAS sobre el fixture).
 * Headless, SIN backend (puerto ≠ :8091). Carga el fixture de constelación y prueba las 3 capas a la vez:
 *   (1) las 3 VISTAS reagrupan correctamente (servicio 5 · funcion 3 · relacion 4) — captura de cada una;
 *   (2) el BRILLO por relevancia está VIVO en la escena real (recinto-agente + conexiones con fan-out > 0);
 *   (3) toggle entre vistas SIN tocar el modelo (pieces/relationships byte-idéntico tras todo el ciclo);
 *   (4) los RECINTOS estructurales siguen visibles DEBAJO de los cúmulos efímeros;
 *   (5) theme claro/oscuro + 0 errores. Capturas: constelacion-c3-{servicio,funcion,relacion,off}-*.png
 * Run:  node verify_constelacion_c3.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { CONSTELACION_FIXTURE, buildConstelacion } from "./fixture_constelacion.mjs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const SHOTS = join(HERE, "screenshots");
const PORT = 8101;                                // ≠ :8091
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
const shotCanvas = async (name) => { const el = await page.$("#cuarto"); if (el) await el.screenshot({ path: join(SHOTS, name) }); };

try {
  await page.goto(PAGE_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 10000 });

  const n = await page.evaluate(buildConstelacion, CONSTELACION_FIXTURE);
  await page.waitForTimeout(150);
  await page.evaluate(() => window.__cuarto.cam.fit()); await page.waitForTimeout(150);
  ok(n === 11, "fixture de constelación cargado (recinto-agente + 6 tools + 2 conexiones)", `placedTiles=${n}`);

  const M0 = await page.evaluate(() => { const m = window.__cuarto.relationModel(); return { pieces: m.pieces, rels: m.relationships }; });

  // ╔══ 1 · las 3 VISTAS reagrupan + captura de CADA una + 3 · modelo intacto por toggle ═════════╗
  const expected = { servicio: 5, funcion: 3, relacion: 4 };
  for (const v of ["servicio", "funcion", "relacion"]) {
    const r = await page.evaluate((vv) => { const c = window.__cuarto; c.view.set(vv); const m = c.relationModel();
      return { groups: c.viewState().groups.length, pieces: m.pieces, rels: m.relationships }; }, v);
    await page.waitForTimeout(450); await shotCanvas(`constelacion-c3-${v}-dark.png`);
    ok(r.groups === expected[v], `1 · vista '${v}' → ${expected[v]} cúmulos`, `grupos=${r.groups}`);
    ok(eq(r.pieces, M0.pieces) && eq(r.rels, M0.rels), `3 · tras '${v}': modelo BYTE-IDÉNTICO (la vista no lo toca)`);
  }

  // ╔══ 1-bis · SIGLAS en la vista servicio (TMDB/SEC EDGAR en MAYÚSCULA, no "Tmdb") ═════════════╗
  const SVlabels = await page.evaluate(() => { const c = window.__cuarto; c.view.set("servicio");
    return Object.fromEntries(c.viewState().groups.map((g) => [g.key, g.label])); });
  ok(SVlabels.tmdb === "TMDB" && SVlabels.sec_edgar === "SEC EDGAR" && SVlabels.kb === "KB",
    "1 · siglas en MAYÚSCULA (TMDB · SEC EDGAR · KB), no titularizadas", JSON.stringify({ tmdb: SVlabels.tmdb, sec_edgar: SVlabels.sec_edgar, kb: SVlabels.kb }));
  ok(SVlabels.gmail === "Gmail" && SVlabels.exa === "Exa",
    "1 · las NO-siglas siguen con titleize normal (Gmail · Exa)", JSON.stringify({ gmail: SVlabels.gmail, exa: SVlabels.exa }));

  // ╔══ 2 · el BRILLO por relevancia está VIVO en la escena real ═════════════════════════════════╗
  const REL = await page.evaluate(() => window.__cuarto.relevance());
  ok(REL.agt === 0.4 && REL.cx_tmdb === 0.4 && REL.cx_gmail === 0.4,
    "2 · relevancia VIVA: recinto-agente (2 hijos) + 2 conexiones (fan-out 2) brillan más", JSON.stringify({ agt: REL.agt, cx_tmdb: REL.cx_tmdb, cx_gmail: REL.cx_gmail }));
  ok(REL.t_exa_p === 0 && REL.t_edgar_r === 0,
    "2 · las tools sueltas siguen en 0 (honesto: el grado es plano en la estrella)");

  // ╔══ 4 · los RECINTOS estructurales siguen visibles DEBAJO de los cúmulos efímeros ════════════╗
  const RD = await page.evaluate(() => window.__cuarto.recintoDraw());
  const agt = RD.find((x) => x.id === "agt");
  ok(RD.length === 1 && agt && agt.haloActive === true && agt.relevance === 0.4,
    "4 · el recinto-agente sigue DIBUJÁNDOSE debajo (muro+halo vivo, relevancia 0.4) — los cúmulos no lo reemplazan", JSON.stringify(agt && { halo: agt.haloActive, rel: agt.relevance }));

  // captura con la vista OFF: se ven los recintos + el brillo de relevancia, sin overlay
  await page.evaluate(() => { window.__cuarto.view.set("off"); window.__cuarto.cam.fit(); });
  await page.waitForTimeout(450); await shotCanvas("constelacion-c3-off-dark.png");

  // ╔══ 3-bis · tras TODO el ciclo de vistas el modelo SIGUE byte-idéntico ═══════════════════════╗
  const Mend = await page.evaluate(() => { const m = window.__cuarto.relationModel(); return { pieces: m.pieces, rels: m.relationships }; });
  ok(eq(Mend.pieces, M0.pieces) && eq(Mend.rels, M0.rels), "3 · tras servicio→funcion→relacion→off: model.pieces/relationships INTACTO");

  // ╔══ 5 · theme CLARO (captura de la vista servicio) + 0 errores ═══════════════════════════════╗
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "light"); window.__cuarto.setTheme("light"); window.__cuarto.view.set("servicio"); window.__cuarto.cam.fit(); });
  await page.waitForTimeout(450); await shotCanvas("constelacion-c3-servicio-light.png");
  const lightOk = await page.evaluate(() => window.__cuarto.viewState().groups.length === 5);
  ok(lightOk, "5 · en theme CLARO la vista 'servicio' agrupa igual (5 cúmulos) sin error");

  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "0 errores JS/render de página", realErrors.length ? "\n  " + realErrors.join("\n  ") : "");
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push("harness: " + e.message);
} finally {
  await browser.close(); server.kill("SIGKILL");
}

console.log("\n" + (fails.length ? `RESULTADO: ROJO (${fails.length})\n - ${fails.join("\n - ")}` : "RESULTADO: VERDE — C3 (e2e constelación) verificada"));
process.exit(fails.length ? 1 : 0);
