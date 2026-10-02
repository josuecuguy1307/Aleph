/* verify_desequipar.mjs — gate quirúrgico al SACAR una pieza delicada en sesión activa.
 * Contrato: antes de quitar una pieza del belt, el frontend confirma SÓLO si
 *   cuarto.running === true  (el agente está trabajando ahora)  Y
 *   pieza.criticality === "high"  (pieza núcleo del nicho, p.ej. FEM/backtester/visor).
 * Cualquier otro caso → saca directo, sin modal (como siempre). El modal NUNCA en equipar.
 * Puerto :8158. Coloca piezas sintéticas (con criticality) vía placeTile → prueba SÓLO la capa de gate.
 * Run: node verify_desequipar.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = 8158;
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => { try { localStorage.setItem("aleph-lang", "en"); localStorage.setItem("aleph-theme", "dark"); } catch (e) {} });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__renderPieces && window.__confirmUnequip, null, { timeout: 12000 });
  // [ola C · item 3] "Las piezas" nace COLAPSADO: la lista y sus ✕ viven un nivel adentro. Se abre
  // como lo hace el usuario (tocar el chip) antes de operar sobre las filas.
  await page.evaluate(() => { try { window.__legendOpen(true); } catch (e) {} });

  // helpers en el page
  const setRunning = (on) => page.evaluate((v) => window.__cuarto.setRunning(v), on);
  const place = (piece) => page.evaluate((p) => { window.__cuarto.placeTile(p); window.__renderPieces(); }, piece);
  const present = (id) => page.evaluate((i) => !!window.__cuarto.pieceData(i), id);
  const modalOpen = () => page.evaluate(() => { const b = document.getElementById("unequipbar"); return !!b && !b.hidden; });
  /* [FIX-P3 · §7] LA FILA MURIÓ — y con ella su ✕. Sacar una pieza es ahora [Quitar] del
   * ARCO de esa pieza, en el diorama. La medición se ENDURECE en dos cosas al mudarse:
   *   · antes bastaba con que existiera un `[data-rm]` en una lista; ahora hay que ABRIR el
   *     arco de ESA pieza y encontrar su [Quitar] — si el arco no lo ofrece, la vara truena;
   *   · y se aprieta con el MOUSE REAL de Playwright, que respeta hit-testing: un botón
   *     tapado, de 0×0 o fuera de pantalla NO se puede tocar, y eso también se mide.
   * El gate de desequipar-en-caliente es el MISMO (quitarPieza → confirmUnequip): lo que
   * cambió es por dónde entra el humano, y eso es exactamente lo que se re-apunta. */
  const clickX = async (id) => {
    await page.evaluate((i) => {
      try { window.__closeAbanico(); } catch (e) {}
      window.__openAbanico(window.__cuarto.pieceData(i));
    }, id);
    await sleep(280);                                   // el arco termina de llegar (~206ms)
    const b = await page.$('#abActs .ab-act[data-act="quitar"]');
    if (!b) throw new Error(`el arco de «${id}» no ofrece [Quitar]`);
    await b.click();                                    // mouse real: hit-testing incluido
  };

  const HIGH = { id: "fem1", label: "Análisis FEM", category: "process", atom: "tool", server: "fem", tools: ["run_fem_analysis"], criticality: "high" };
  const LOW = { id: "excel1", label: "Excel local", category: "process", atom: "tool", server: "excel", tools: ["create_workbook"], criticality: "low" };

  // ── CASO 1 · pieza HIGH + agente trabajando → modal aparece; cancelar mantiene la pieza; confirmar la saca ──
  await place(HIGH); await place(LOW);
  await setRunning(true);
  await clickX("fem1"); await sleep(200);
  ok(await modalOpen(), "(1a) HIGH + trabajando → aparece el modal de confirmación");
  ok(await present("fem1"), "(1b) al abrir el modal la pieza NO se sacó todavía");

  await page.click("#unequipCancel"); await sleep(150);
  ok(!(await modalOpen()) && (await present("fem1")), "(1c) Cancelar → cierra el modal y la pieza SIGUE");

  await clickX("fem1"); await sleep(200);
  ok(await modalOpen(), "(1d) re-intento → modal otra vez");
  await page.click("#unequipConfirm"); await sleep(200);
  ok(!(await modalOpen()) && !(await present("fem1")), "(1e) 'Sacar de todas formas' → cierra el modal y SACA la pieza");

  // ── CASO 2 · pieza HIGH pero agente NO trabajando → sale directo, sin modal ──
  await place(HIGH);
  await setRunning(false);
  await clickX("fem1"); await sleep(200);
  ok(!(await modalOpen()) && !(await present("fem1")), "(2) HIGH sin sesión activa → sale directo, SIN modal");

  // ── CASO 3 · pieza LOW durante sesión activa → sale directo, sin modal ──
  await setRunning(true);
  await clickX("excel1"); await sleep(200);
  ok(!(await modalOpen()) && !(await present("excel1")), "(3) LOW en sesión activa → sale directo, SIN modal");

  // ── CASO 4 · EQUIPAR nunca dispara el modal (aunque sea HIGH y esté trabajando) ──
  await setRunning(true);
  await place({ ...HIGH, id: "fem2" }); await sleep(150);
  ok(!(await modalOpen()) && (await present("fem2")), "(4) equipar una pieza HIGH en sesión activa → SIN modal");

  // ── CASO 5 · el modal habla el idioma del usuario (EN) ──
  await clickX("fem2"); await sleep(200);
  const en = await page.evaluate(() => ({
    head: (document.getElementById("unequipHead") || {}).textContent || "",
    confirm: (document.getElementById("unequipConfirm") || {}).textContent || "",
    cancel: (document.getElementById("unequipCancel") || {}).textContent || "",
    sub: (document.getElementById("unequipSub") || {}).textContent || "",
  }));
  ok(/working on something right now/i.test(en.head) && /Remove anyway/i.test(en.confirm) && /Cancel/i.test(en.cancel) && !/Cancelar|trabajando/i.test(en.head + en.confirm + en.cancel),
     "(5) EN: modal en inglés (sin español)", JSON.stringify(en.confirm + " / " + en.cancel));
  await page.screenshot({ path: join(HERE, "screenshots", "desequipar-modal-en.png") });
  await page.click("#unequipCancel");

  // ── CASO 6 · vocabulario amigable: sin jerga técnica prohibida (MCP/session/criticality/unequip/tool) ──
  const bad = /\b(MCP|session|criticality|unequip|belt|runtime|endpoint|PATCH)\b/i;
  ok(!bad.test(en.head + en.sub + en.confirm + en.cancel), "(6) copy sin jerga técnica prohibida", JSON.stringify(en.sub));

  ok(errors.length === 0, "(7) 0 errores JS/render", errors.slice(0, 2).join(" ; "));
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  await browser.close(); server.kill();
}
console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — gate al desequipar (sólo HIGH + sesión activa · cancelar preserva · confirmar saca · nunca al equipar · bilingüe)"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
