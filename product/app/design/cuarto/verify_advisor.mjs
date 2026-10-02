/* verify_advisor.mjs — TICKET 5 · GATE ADVISOR en vivo (Playwright + STACK REAL).
 * Requiere el stack del worktree: backend :8150 (POST /v1/advisor/classify) + front :8151.
 * Prueba (nada mockeado):
 *   (0) endpoint: envío/escritura/exfil/ambigua consecuentes · lectura no · plata = piso;
 *   (a) FANTASMA en el cable exacto: piezas con tools consecuentes SIN gate → candado
 *       fantasma (api.advisorGhosts); la lectura NO; la plata NO (piso ≠ sugerencia);
 *   (b) FAIL-CLOSED: tool ambigua (frobnicate) → fantasma;
 *   (c) EXFIL: search_web (lectura para el runtime) → fantasma con why de exfiltración;
 *   (d) aceptar la sugerencia (applyGhost = mismo camino que el tap): gate REAL en el
 *       modelo (kind:"gate"), el fantasma de ESA pieza desaparece, microcopy en el say;
 *   (e) inspector: sección "Compuerta sugerida" con why + botón que pone el gate; la
 *       pieza de plata muestra "piso del sistema" SIN botón (no es opción);
 *   (f) lang=en (reload por diseño): section/botón en inglés, fantasma vivo igual;
 *   (g) 0 errores de consola.
 * Run:  node verify_advisor.mjs
 */
import { chromium } from "playwright";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SHOTS = join(HERE, "screenshots");
const FRONT = process.env.ALEPH_FRONT || "http://127.0.0.1:8151";
const CUARTO_URL = `${FRONT}/cuarto/cuarto.pixi.html`;

const fails = [];
const ok = (cond, label, extra) => { console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };

// ── (0) endpoint real ──
const cls = await fetch(`${FRONT}/v1/advisor/classify`, { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ tools: ["send_mail", "get_price", "search_web", "frobnicate", "transfer_funds"] }) }).then((r) => r.json());
const by = Object.fromEntries(cls.tools.map((t) => [t.tool, t]));
ok(by.send_mail.clase === "envio" && by.send_mail.sugerir_gate, "(0) send_mail → envío, gate sugerido");
ok(by.get_price.clase === "lectura" && !by.get_price.consecuente, "(0) get_price → lectura, sin sugerencia");
ok(by.search_web.clase === "exfil" && by.search_web.sugerir_gate, "(0) search_web → EXFIL (lectura que saca datos)");
ok(by.frobnicate.clase === "ambigua" && by.frobnicate.consecuente, "(0) frobnicate → AMBIGUA fail-closed");
ok(by.transfer_funds.piso_server && !by.transfer_funds.sugerir_gate, "(0) transfer_funds → PISO server (no sugerencia)");

const SEED = [
  { id: "env",  label: "mandar mail",   category: "write",   server: "svc-mail",  tools: ["send_mail"],       gx: 1, gy: 1 },
  { id: "lee",  label: "precio",        category: "read",    server: "svc-quote", tools: ["get_price"],       gx: 3, gy: 1 },
  { id: "exf",  label: "buscar web",    category: "read",    server: "svc-web",   tools: ["search_web"],      gx: 5, gy: 1 },
  { id: "amb",  label: "frobnicate",    category: "process", server: "svc-x",     tools: ["frobnicate"],      gx: 1, gy: 3 },
  { id: "pla",  label: "transferir",    category: "write",   server: "svc-bank",  tools: ["transfer_funds"],  gx: 3, gy: 3 },
];
const seedAndWait = async (page) => {
  await page.evaluate((seed) => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    for (const s of seed) c.placeTile(s, s.gx, s.gy);
    window.__sync();                                        // dispara advisorSync (debounced)
  }, SEED);
  // el barrido es async (debounce + fetch) → poll hasta que el fantasma del envío exista
  await page.waitForFunction(() => (window.__cuarto.advisorGhosts() || []).includes("env"), null, { timeout: 10000 });
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));

try {
  await page.goto(CUARTO_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.__atoms, null, { timeout: 20000 });
  await seedAndWait(page);

  // ── (a)+(b)+(c) qué piezas tienen fantasma ──
  const ghosts = await page.evaluate(() => window.__cuarto.advisorGhosts());
  ok(ghosts.includes("env"), "(a) envío sin gate → FANTASMA en su cable", JSON.stringify(ghosts));
  ok(ghosts.includes("amb"), "(b) ambigua → FANTASMA (fail-closed)");
  ok(ghosts.includes("exf"), "(c) exfil → FANTASMA (lectura con canal saliente)");
  ok(!ghosts.includes("lee"), "(a) lectura pura → SIN fantasma");
  ok(!ghosts.includes("pla"), "(a) plata → SIN fantasma (piso del sistema, no sugerencia)");
  const advPla = await page.evaluate(() => window.__cuarto.pieceData("pla")._advisor);
  ok(advPla && advPla.piso, "(a) …pero la pieza de plata SÍ sabe que tiene piso", JSON.stringify(advPla));
  const whyExf = await page.evaluate(() => window.__cuarto.pieceData("exf")._advisor.why);
  ok(whyExf && whyExf.code === "exfil" && /viaja|datos/i.test(whyExf.es), "(c) …con why de exfiltración", whyExf && whyExf.code);
  await page.evaluate(() => window.__cuarto.cam.fit());
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(SHOTS, "advisor-fantasmas.png"), clip: { x: 0, y: 0, width: 1280, height: 860 } });

  // ── (d) aceptar la sugerencia = gate REAL + microcopy ──
  const okApply = await page.evaluate(() => window.__cuarto.applyGhost("env"));
  await page.waitForTimeout(150);   // los fantasmas se re-derivan en el próximo frame del ticker
  const after = await page.evaluate(() => {
    const model = window.__cuarto.relationModel();
    return {
      gated: model.relationships.some((r) => r.kind === "gate" && r.on === "env"),
      ghosts: window.__cuarto.advisorGhosts(),
      say: document.getElementById("status").textContent };
  });
  after.okApply = okApply;
  ok(after.okApply && after.gated, "(d) aceptar → gate REAL en el modelo (kind:'gate' on env)");
  ok(!after.ghosts.includes("env") && after.ghosts.includes("exf"), "(d) el fantasma de ESA pieza se va; los demás quedan", JSON.stringify(after.ghosts));
  ok(/compuerta puesta en/i.test(after.say) && /mail|svc/i.test(after.say), "(d) microcopy del porqué en el say", after.say.slice(0, 90));

  // ── (e) inspector: sugerida (con botón) vs piso (sin botón) ──
  const insSug = await page.evaluate(() => {
    window.__openInspector(window.__cuarto.pieceData("exf"));
    const sec = document.querySelector("#inspector .osec.adv");
    return { has: !!sec, head: sec ? sec.querySelector(".osec-h").textContent : "",
      why: sec ? sec.querySelector(".ro2").textContent : "", btn: !!(sec && sec.querySelector("[data-advgate]")) };
  });
  ok(insSug.has && /sugerida/i.test(insSug.head) && insSug.btn, "(e) inspector exfil → 'Compuerta sugerida' + botón", insSug.head);
  ok(/viaja|datos/i.test(insSug.why), "(e) …con el why visible (microcopy)", insSug.why.slice(0, 70));
  await page.evaluate(() => document.querySelector("#inspector [data-advgate]").click());
  await page.waitForTimeout(150);   // ídem: re-derivación por frame
  const insBtn = await page.evaluate(() => {
    const model = window.__cuarto.relationModel();
    return { gated: model.relationships.some((r) => r.kind === "gate" && r.on === "exf"),
      ghosts: window.__cuarto.advisorGhosts() };
  });
  ok(insBtn.gated && !insBtn.ghosts.includes("exf"), "(e) botón del inspector → mismo camino: gate real + fantasma fuera");
  const insPiso = await page.evaluate(() => {
    window.__openInspector(window.__cuarto.pieceData("pla"));
    const sec = document.querySelector("#inspector .osec.adv");
    return { has: !!sec, head: sec ? sec.querySelector(".osec-h").textContent : "", btn: !!(sec && sec.querySelector("[data-advgate]")) };
  });
  ok(insPiso.has && /piso del sistema/i.test(insPiso.head) && !insPiso.btn, "(e) inspector plata → 'piso del sistema' SIN botón", insPiso.head);

  // ── (f) EN (setLang recarga por diseño → re-seed) ──
  await Promise.all([
    page.waitForNavigation({ waitUntil: "load", timeout: 20000 }),
    page.evaluate(() => window.AlephI18n.setLang("en")),
  ]);
  await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.__atoms
    && window.AlephI18n && window.AlephI18n.lang() === "en", null, { timeout: 20000 });
  await seedAndWait(page);
  const enIns = await page.evaluate(() => {
    window.__openInspector(window.__cuarto.pieceData("exf"));
    const sec = document.querySelector("#inspector .osec.adv");
    return { head: sec ? sec.querySelector(".osec-h").textContent : "",
      why: sec ? sec.querySelector(".ro2").textContent : "",
      btn: sec && sec.querySelector("[data-advgate]") ? sec.querySelector("[data-advgate]").textContent : "",
      ghosts: window.__cuarto.advisorGhosts() };
  });
  ok(/suggested gate/i.test(enIns.head), "(f) lang=en · 'Suggested gate'", enIns.head);
  ok(/travels|data/i.test(enIns.why) && /place the gate/i.test(enIns.btn), "(f) lang=en · why + botón en inglés", enIns.btn);
  ok(enIns.ghosts.includes("env") && enIns.ghosts.includes("exf"), "(f) lang=en · fantasmas vivos igual", JSON.stringify(enIns.ghosts));
  await Promise.all([
    page.waitForNavigation({ waitUntil: "load", timeout: 20000 }),
    page.evaluate(() => window.AlephI18n.setLang("es")),
  ]).catch(() => {});

  // ── (g) consola limpia ──
  const realErrors = errors.filter((e) => !/Failed to load resource|favicon/i.test(e));
  ok(realErrors.length === 0, "(g) 0 errores de consola", realErrors.slice(0, 3).join(" | "));
} finally {
  await browser.close();
}

console.log(fails.length ? `\n✗ FALLARON ${fails.length}` : "\n✓ VERDE — ticket 5 (Gate Advisor) en vivo");
process.exit(fails.length ? 1 : 0);
